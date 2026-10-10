"""Behavioral tests for ESA's local evidence pipeline and the demo wrapper."""
import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/"scripts"
sys.path.insert(0,str(SCRIPTS))
import esa
import demo
import validate_experiment_audit


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)

    def tearDown(self): self.temp.cleanup()

    def make_bundle(self,text,fields,source_review=None,requirement_count=1):
        source=self.root/"standard.md"; source.write_text(text,encoding="utf-8")
        prep=self.root/"prep"; clauses=esa.prepare(source,prep,"TEST-STD","ED-1","en")
        clauses["blocks"][0]["clause_id"]="1.1"
        esa.write(prep/"clauses.json",clauses)
        rows=[]
        for ix in range(requirement_count):
            rows.append({"requirement_id":f"R{ix+1}","block_id":"B0001","quote":clauses["blocks"][0]["original_text"],
                "summary":"Test-only source requirement","requirement_level":"mandatory","applicability":"applicable",
                "fields":{k:{"quote":v,"value":v} for k,v in fields.items()},
                "not_required":[d for d in esa.DIMENSIONS if d not in fields],
                "source_review":source_review or {}})
        annotations={"schema_version":"2.0","standard_id":"TEST-STD","edition":"ED-1",
            "source_complete":False,"coverage_review":{},"requirements":rows}
        return source,clauses,annotations

    def verified_requirements(self,text,fields):
        review={"reviewer":"TEST FIXTURE ONLY","reviewed_at":"2099-01-01",
            "approval_evidence":"Synthetic metadata for unit-branch coverage only; not an actual source review."}
        _,clauses,ann=self.make_bundle(text,fields,review)
        return clauses,esa.build_requirements(clauses,ann)

    def test_source_hash_quote_and_page_provenance_rejections(self):
        source,clauses,_=self.make_bundle("Fictional source clause with 4 kPa.",{"method":"4 kPa"})
        saved=clauses["blocks"][0]["original_text"]
        clauses["blocks"][0]["original_text"]="invented quote"
        with self.assertRaisesRegex(ValueError,"untraceable block quote"): esa.verify_clauses(clauses)
        clauses["blocks"][0]["original_text"]=saved
        clauses["blocks"][0]["source"]["pdf_page"]=1
        with self.assertRaisesRegex(ValueError,"page provenance mismatch"): esa.verify_clauses(clauses)
        clauses["blocks"][0]["source"]["pdf_page"]=None
        source.write_text("Changed after extraction",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"source hash changed"): esa.verify_clauses(clauses)

    def test_requirement_quote_forgery_is_rejected(self):
        _,clauses,ann=self.make_bundle("Original only text",{"method":"Original"})
        ann["requirements"][0]["quote"]="not in source"
        with self.assertRaisesRegex(ValueError,"requirement quote missing"): esa.build_requirements(clauses,ann)

    def test_unknown_dimension_and_numeric_conflict_never_align(self):
        fields={"method":"run at 5 kPa"}
        clauses,reqs=self.verified_requirements("run at 5 kPa",fields)
        plan={"plan_id":"P","tests":[{"test_id":"T","requirement_ids":["R1"],"quote":"perform at 5 kPa","source":{},
            "fields":{"method":{"quote":"perform at 5 kPa"}}}]}
        result=esa.audit(reqs,plan)
        self.assertEqual(result["items"][0]["status"],"not_assessable")
        self.assertEqual(next(x for x in result["items"][0]["checkpoints"] if x["dimension"]=="method")["status"],"unknown")
        clauses,reqs=self.verified_requirements("run at 5 kPa",fields)
        plan["tests"][0]["quote"]="run at 6 kPa"; plan["tests"][0]["fields"]["method"]["quote"]="run at 6 kPa"
        result=esa.audit(reqs,plan)
        self.assertEqual(result["items"][0]["status"],"conflict")

    def test_plan_missing_and_partial_are_distinguished(self):
        _,reqs=self.verified_requirements("run method; use 23 C",{"method":"run method","conditions":"23 C"})
        self.assertEqual(esa.audit(reqs,{"plan_id":"P","tests":[]})["items"][0]["status"],"missing")
        plan={"plan_id":"P","tests":[{"test_id":"T","requirement_ids":["R1"],"quote":"run method","source":{},
            "fields":{"method":{"quote":"run method"}}}]}
        self.assertEqual(esa.audit(reqs,plan)["items"][0]["status"],"partial")

    def test_full_equal_review_fixture_aligns_but_remains_draft(self):
        fields={d:f"evidence for {d}" for d in esa.DIMENSIONS}
        text="; ".join(fields.values())
        _,reqs=self.verified_requirements(text,fields)
        plan={"plan_id":"P","tests":[{"test_id":"T","requirement_ids":["R1"],"quote":text,"source":{},
            "fields":{d:{"quote":v} for d,v in fields.items()}}]}
        result=esa.audit(reqs,plan)
        self.assertEqual(result["items"][0]["status"],"aligned")
        self.assertEqual(result["items"][0]["review_status"],"draft")
        self.assertEqual(validate_experiment_audit.check(reqs,plan,result),[])
        # `source_review` above is synthetic test-only metadata; it proves a branch and is not evidence.

    def test_study_requires_complete_real_shaped_review_record(self):
        _,reqs=self.verified_requirements("clause quote",{"method":"clause quote"})
        good={"reviewer":"TEST FIXTURE ONLY","reviewed_at":"2099-01-01",
            "approval_evidence":"Synthetic unit-test metadata only; no formal approval."}
        reqs["requirements"].append({**reqs["requirements"][0],"requirement_id":"R2","review_status":"approved","review_record":good})
        out=self.root/"study"; self.assertEqual(esa.export_study(reqs,out),1)
        handoff=json.loads((out/"handoff.json").read_text(encoding="utf-8"))
        self.assertEqual(handoff["approved_count"],1); self.assertIn("R1",handoff["excluded_ids"])
        self.assertTrue(list((out/"source").glob("*.md")))
        with self.assertRaisesRegex(ValueError,"study output exists"): esa.export_study(reqs,out)

    def test_csv_formula_injection_prefix_is_applied(self):
        target=self.root/"safe.csv"; esa.csv_out(target,[{"text":"=2+2"}], ["text"])
        with target.open(encoding="utf-8-sig",newline="") as f: row=next(csv.DictReader(f))
        self.assertEqual(row["text"],"'=2+2")

    def test_end_to_end_demo_is_fictional_unreviewed_and_reproducible(self):
        out=self.root/"demo-run"
        result=demo.run(out,"md")
        self.assertEqual(result["source_type"],"markdown_non_pdf")
        self.assertEqual(result["study_approved_counts"],{"en":0,"ja":0})
        self.assertTrue((out/"en"/"requirements-matrix.csv").is_file())
        self.assertTrue((out/"ja"/"experiment_audit.csv").is_file())
        self.assertTrue((out/"DEMO-ONLY.md").is_file())
        for lang in ("en","ja"):
            requirements=esa.read(out/lang/"requirements.json")
            self.assertFalse(requirements["requirements"][0]["source_verified"])
            self.assertEqual(requirements["requirements"][0]["source_review"],{})
            manifest=esa.read(out/lang/"manifest.json")
            self.assertTrue(all(Path(x["file"]).is_file() for x in manifest["inputs"]))
            seg=esa.read(out/lang/"translations"/"segments.json")["segments"][0]
            self.assertFalse(seg["human_reviewed"])
            self.assertTrue(seg["source"] and seg["source_quote"])
            source=Path(requirements["requirements"][0]["source"]["file"])
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),requirements["requirements"][0]["source"]["sha256"])
        with self.assertRaisesRegex(ValueError,"demo output exists"): demo.run(out,"md")


if __name__=="__main__": unittest.main()
