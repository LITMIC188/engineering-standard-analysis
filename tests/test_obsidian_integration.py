import hashlib, importlib.util, json, os, tempfile, unittest
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
TEMP_ROOT=ROOT/"run"/"obsidian-tests"
TEMP_ROOT.mkdir(parents=True,exist_ok=True)
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/"scripts"/(name+".py"));mod=importlib.util.module_from_spec(spec);sys.modules[name]=mod;spec.loader.exec_module(mod);return mod
render=load("obsidian_render"); publish=load("obsidian_publish"); verify=load("obsidian_verify")
local_parser=load("local_parser"); verify_source_module=load("verify_source")

class ObsidianAdapterTests(unittest.TestCase):
    def setup_bundle(self, td, status="draft"):
        fixture=json.loads((ROOT/"tests/fixtures/obsidian_bundle.json").read_text(encoding="utf-8"))
        base=Path(td); source=base/"synthetic.txt";source.write_bytes(fixture["source_text"].encode("utf-8"))
        extraction=local_parser.extract_document(source)
        source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
        loc=extraction["pages"][0]["locator"]; block={"block_id":fixture["block_id"],"clause_id":fixture["clause_id"],"kind":"clause","source_lang":"en","original_text":fixture["source_text"],"source":{"file":str(source),"sha256":source_hash,"pdf_page":None,"page_kind":"text","locator":loc}}
        clauses_obj={"schema_version":"2.0","standard_id":fixture["standard_id"],"edition":fixture["edition"],"source":{"file":str(source),"sha256":source_hash},"blocks":[block]}
        clauses=base/"clauses.json";clauses.write_text(json.dumps(clauses_obj,ensure_ascii=False,indent=2),encoding="utf-8")
        art=base/"article.md";from verify_source import canonical_source_article
        art.write_bytes(canonical_source_article(clauses_obj))
        review={"reviewer":"synthetic fixture reviewer","reviewed_at":"2099-01-01T00:00:00Z","approval_evidence":"synthetic source page checked"}
        inventory={"pages":[loc],"chapters":[fixture["clause_id"]],"normative_annexes":[],"tables":[],"figures":[],"references":[]}
        extraction["expected_inventory"]=inventory
        checklist=[{"inventory_kind":"pages","inventory_id":loc,"status":"reviewed"},{"inventory_kind":"chapters","inventory_id":fixture["clause_id"],"status":"reviewed"}]
        reg={"schema_version":"1.0","source_sha256":source_hash,"headings":[{"heading_id":"H0001","block_id":fixture["block_id"],"clause_id":fixture["clause_id"],"title":fixture["heading_title"],"level":1,"order":1,"source":dict(block["source"])}]}
        verified=verify_source_module.verify_source(clauses_obj,extraction,checklist,review,str(art),heading_registry=reg)
        row={"requirement_id":"R-1","block_id":fixture["block_id"],"clause_id":fixture["clause_id"],"quote":fixture["requirement_quote"],"summary":fixture["requirement_summary"],"applicability":"applicable","source_verified":True,"source_review":review,"review_status":status,"requirement_level":"mandatory","source":{**block["source"],"standard_id":fixture["standard_id"],"edition":fixture["edition"]}}
        if status=="approved":row["review_record"]={"reviewer":"synthetic fixture reviewer","reviewed_at":"2099-01-01T00:00:00Z","approval_evidence":"synthetic engineering approval"}
        reqs={"schema_version":"2.0","standard_id":fixture["standard_id"],"edition":fixture["edition"],"source_complete":True,"requirements":[row]}
        vp=base/"verified.json";rp=base/"requirements.json";tp=base/"titles.json"
        vp.write_text(json.dumps(verified),encoding="utf-8");rp.write_text(json.dumps(reqs),encoding="utf-8");tp.write_text(json.dumps(reg),encoding="utf-8")
        out=base/"stage"; scope="Synthetic/Job/"; vault=base/"vault";vault.mkdir()
        request={"interface_id":"B-接口-02","interface_name":"render_obsidian_markdown","job_id":"JOB-1","schema_version":"1.0","vault_root":str(vault),"target_scope":scope,"source_sha256":source_hash,"dry_run":False,"payload":{"verified_source_path":str(vp),"clauses_path":str(clauses),"requirements_path":str(rp),"titles_registry_path":str(tp),"article_path":str(art),"staging_dir":str(out)}}
        return base,request,out

    def test_staging_fsync_failure_removes_created_files(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            _,req,stage=self.setup_bundle(td)
            with patch.object(render.os,"fsync",side_effect=OSError("synthetic staging fsync failure")):
                with self.assertRaises(render.AdapterError):render.render(req)
            self.assertFalse(any(p.is_file() for p in stage.rglob("*")))

    def test_render_b_interface_order_frontmatter_title_and_base_scope(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            _,req,out=self.setup_bundle(td);r=render.render(req)
            self.assertTrue(r["result"]["ok"]);self.assertEqual(r["result"]["details"]["rendered_count"],3)
            note=(out/"Synthetic/Job/04_要求/R-1.md").read_text(encoding="utf-8")
            self.assertIn("Synthetic title",note);self.assertIn('"esa_requirement_id": "R-1"',note)
            self.assertNotIn("# X.1 X.1",note)
            base=(out/"Synthetic/Job/标准要求总览.base").read_text(encoding="utf-8")
            base_obj=json.loads(base)
            self.assertIn('file.inFolder("Synthetic/Job/04_要求")',base_obj["filters"]["and"])
            self.assertTrue(any('esa_review_status == "approved"' in v.get("filters",{}).get("and",[]) for v in base_obj["views"]))

    def test_incomplete_source_and_bad_registry_block(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            base,req,_=self.setup_bundle(td);v=json.loads((base/"verified.json").read_text());v["source_complete"]=False;(base/"verified.json").write_text(json.dumps(v))
            with self.assertRaises(render.AdapterError) as e:render.render(req)
            self.assertEqual(e.exception.code,"SOURCE_NOT_VERIFIED")

    def test_path_traversal_absolute_and_symlink_are_blocked(self):
        for value in (".","../outside","C:/outside","/outside","folder/file:stream","CON.txt","bad."):
            with self.assertRaises(render.AdapterError):render.safe_relative(value)
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            root=Path(td);outside=root.parent/(root.name+"-outside");outside.mkdir()
            link=root/"escape"
            try:link.symlink_to(outside,target_is_directory=True)
            except OSError:return
            with self.assertRaises(publish.AdapterError):publish.resolve_inside(root,"escape/file.md")

    def test_dry_run_stages_and_copies_hashed_relative_attachment(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            base,req,stage=self.setup_bundle(td)
            source_img=base/"page.jpg";source_img.write_bytes(b"synthetic image bytes")
            clauses=json.loads(Path(req["payload"]["clauses_path"]).read_text(encoding="utf-8"))
            clauses["blocks"][0]["kind"]="figure";clauses["blocks"][0]["attachment"]=str(source_img)
            Path(req["payload"]["clauses_path"]).write_text(json.dumps(clauses,ensure_ascii=False),encoding="utf-8")
            from verify_source import canonical_source_article
            article=canonical_source_article(clauses);Path(req["payload"]["article_path"]).write_bytes(article)
            verified=json.loads(Path(req["payload"]["verified_source_path"]).read_text(encoding="utf-8"))
            verified["clauses_sha256"]=render.canonical_clauses_sha(clauses);verified["article_sha256"]=hashlib.sha256(article).hexdigest()
            Path(req["payload"]["verified_source_path"]).write_text(json.dumps(verified),encoding="utf-8")
            req["payload"]["attachments"]=[{"source_path":str(source_img),"target_path":"assets/page.jpg","sha256":hashlib.sha256(source_img.read_bytes()).hexdigest()}]
            req["dry_run"]=True
            r=render.render(req);self.assertTrue(r["result"]["ok"])
            article_out=(stage/"Synthetic/Job/01_原文.md").read_text(encoding="utf-8")
            self.assertIn("![[assets/page.jpg]]",article_out)
            self.assertEqual((stage/"Synthetic/Job/assets/page.jpg").read_bytes(),source_img.read_bytes())
            self.assertTrue((stage/".esa_staging_manifest.json").is_file())

    def test_tampered_staging_and_root_mismatch_block_before_write(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            base,req,stage=self.setup_bundle(td,status="approved");render.render(req)
            note=stage/"Synthetic/Job/04_要求/R-1.md";note.write_text(note.read_text(encoding="utf-8")+"\nchanged\n",encoding="utf-8")
            root=base/"vault";os.environ["OBSIDIAN_VAULT_ROOT"]=str(root)
            preq={**req,"vault_root":str(root),"dry_run":False,"payload":{**req["payload"],"staging_dir":str(stage),"allow_write":True,"publish_policy":{"require_cli_validation":False},"runtime_dir":str(base/"runtime")}}
            with self.assertRaises(publish.AdapterError) as e:publish.publish(preq)
            self.assertEqual(e.exception.code,"SOURCE_NOT_VERIFIED")
            # Restore the staged bundle through the renderer, then prove root mismatch is blocked.
            import shutil;shutil.rmtree(stage);render.render(req)
            os.environ["OBSIDIAN_VAULT_ROOT"]=str(base/"other-vault")
            with self.assertRaises(publish.AdapterError) as e:publish.publish(preq)
            self.assertEqual(e.exception.code,"VAULT_ROOT_MISMATCH")
            self.assertFalse((root/"Synthetic/Job/01_原文.md").exists())

    def test_rollback_preserves_file_changed_after_our_write(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            base,req,stage=self.setup_bundle(td,status="approved");render.render(req)
            root=base/"vault";os.environ["OBSIDIAN_VAULT_ROOT"]=str(root)
            preq={**req,"vault_root":str(root),"dry_run":False,"payload":{**req["payload"],"staging_dir":str(stage),"allow_write":True,"publish_policy":{"require_cli_validation":True},"obsidian_executable":"fake","vault_name":"Fixture","runtime_dir":str(base/"runtime")}}
            external=root/"Synthetic/Job/01_原文.md"
            def fake_run(args,**kwargs):
                if args[-1]=="help":return type("R",(),{"returncode":0,"stdout":"read vault info","stderr":""})()
                if args[-1]=="info":return type("R",(),{"returncode":0,"stdout":str(root),"stderr":""})()
                external.write_text("external user edit",encoding="utf-8")
                return type("R",(),{"returncode":0,"stdout":b"wrong","stderr":b""})()
            with patch.object(publish.subprocess,"run",side_effect=fake_run):
                with self.assertRaises(publish.AdapterError) as e:publish.publish(preq)
            self.assertEqual(e.exception.code,"PARTIAL_WRITE")
            self.assertTrue(external.exists(),str(list(root.rglob("*"))))
            self.assertEqual(external.read_text(encoding="utf-8"),"external user edit")
            rb=json.loads((base/"runtime/rollback_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("Synthetic/Job/01_原文.md",rb["restore_failures"])

    def test_conflict_does_not_overwrite(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            base,req,stage=self.setup_bundle(td,status="approved");self.assertTrue(render.render(req)["result"]["ok"])
            root=base/"vault";root.mkdir(exist_ok=True);target=root/"Synthetic/Job/01_原文.md";target.parent.mkdir(parents=True);target.write_text("keep",encoding="utf-8")
            os.environ["OBSIDIAN_VAULT_ROOT"]=str(root)
            preq={**req,"vault_root":str(root),"dry_run":False,"payload":{**req["payload"],"staging_dir":str(stage),"allow_write":True,"publish_policy":{"require_cli_validation":False},"runtime_dir":str(base/"runtime")}}
            with self.assertRaises(publish.AdapterError) as e:publish.publish(preq)
            self.assertEqual(e.exception.code,"WRITE_CONFLICT");self.assertEqual(target.read_text(),"keep")

    def test_b04_manifest_excluded_and_dry_run_pending(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            _,req,stage=self.setup_bundle(td);render.render(req)
            vreq={"interface_id":"B-接口-04","interface_name":"verify_obsidian_publish","job_id":req["job_id"],"schema_version":"1.0","vault_root":req["vault_root"],"target_scope":req["target_scope"],"source_sha256":req["source_sha256"],"dry_run":True,"payload":{"staging_dir":str(stage)}}
            result=verify.verify(vreq)
            self.assertFalse(result["result"]["ok"])
            self.assertEqual(result["result"]["status"],"pending_cli_validation")

    def test_cli_root_prefix_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            base,req,stage=self.setup_bundle(td,status="approved");render.render(req)
            root=base/"vault";os.environ["OBSIDIAN_VAULT_ROOT"]=str(root)
            preq={**req,"vault_root":str(root),"dry_run":False,"payload":{**req["payload"],"staging_dir":str(stage),"allow_write":True,"publish_policy":{"require_cli_validation":True},"obsidian_executable":"fake","vault_name":"Fixture","runtime_dir":str(base/"runtime")}}
            def fake_run(args,**kwargs):
                if args[-1]=="help":return type("R",(),{"returncode":0,"stdout":"read vault info","stderr":""})()
                return type("R",(),{"returncode":0,"stdout":str(root)+"-other","stderr":""})()
            with patch.object(publish.subprocess,"run",side_effect=fake_run):
                with self.assertRaises(publish.AdapterError) as e:publish.publish(preq)
            self.assertEqual(e.exception.code,"VAULT_ROOT_MISMATCH")
            self.assertFalse((root/"Synthetic/Job/01_原文.md").exists())

    def test_b04_image_link_missing_blocks_even_with_valid_manifest(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            base,req,stage=self.setup_bundle(td)
            rel="Synthetic/Job/01_原文.md";dest=stage/rel;dest.parent.mkdir(parents=True)
            data=b"![missing](assets/missing.png)\n"
            dest.write_bytes(data)
            manifest={"schema_version":"1.0","job_id":req["job_id"],"target_scope":req["target_scope"].rstrip("/"),"source_sha256":req["source_sha256"],"files":[{"path":rel,"sha256":hashlib.sha256(data).hexdigest()}]}
            (stage/".esa_staging_manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
            vreq={"interface_id":"B-接口-04","interface_name":"verify_obsidian_publish","job_id":req["job_id"],"schema_version":"1.0","vault_root":req["vault_root"],"target_scope":req["target_scope"],"source_sha256":req["source_sha256"],"dry_run":True,"payload":{"staging_dir":str(stage)}}
            with self.assertRaises(verify.AdapterError) as e:verify.verify(vreq)
            self.assertEqual(e.exception.code,"LINK_TARGET_MISSING")

    def test_b04_actual_vault_attachment_hash_mismatch_fails(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            base,req,stage=self.setup_bundle(td);root=base/"vault";os.environ["OBSIDIAN_VAULT_ROOT"]=str(root)
            mdrel="Synthetic/Job/01_原文.md";assetrel="Synthetic/Job/assets/page.png"
            files={mdrel:b"![[assets/page.png]]\n",assetrel:b"expected image"}
            entries=[]
            for rel,data in files.items():
                dst=stage/rel;dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(data)
                actual=root/rel;actual.parent.mkdir(parents=True,exist_ok=True);actual.write_bytes(b"tampered image" if rel==assetrel else data)
                entries.append({"path":rel,"sha256":hashlib.sha256(data).hexdigest()})
            (stage/".esa_staging_manifest.json").write_text(json.dumps({"schema_version":"1.0","job_id":req["job_id"],"target_scope":req["target_scope"].rstrip("/"),"source_sha256":req["source_sha256"],"files":entries}),encoding="utf-8")
            vreq={"interface_id":"B-接口-04","interface_name":"verify_obsidian_publish","job_id":req["job_id"],"schema_version":"1.0","vault_root":str(root),"target_scope":req["target_scope"],"source_sha256":req["source_sha256"],"dry_run":False,"payload":{"staging_dir":str(stage),"vault_name":"Fixture","obsidian_executable":"fake"}}
            def fake_run(args,**kwargs):
                if args[-1]=="help":return type("R",(),{"returncode":0,"stdout":"read vault info","stderr":""})()
                if args[-1]=="info":return type("R",(),{"returncode":0,"stdout":str(root),"stderr":""})()
                return type("R",(),{"returncode":0,"stdout":files[mdrel],"stderr":b""})()
            with patch.object(verify.subprocess,"run",side_effect=fake_run):
                with self.assertRaises(verify.AdapterError) as e:verify.verify(vreq)
            self.assertEqual(e.exception.code,"CLI_READBACK_MISMATCH")

    def test_b04_rejects_non_boolean_dry_run_and_duplicate_manifest_keys(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            base,req,stage=self.setup_bundle(td);render.render(req)
            vreq={"interface_id":"B-接口-04","interface_name":"verify_obsidian_publish","job_id":req["job_id"],"schema_version":"1.0","vault_root":req["vault_root"],"target_scope":req["target_scope"],"source_sha256":req["source_sha256"],"dry_run":"false","payload":{"staging_dir":str(stage)}}
            with self.assertRaises(verify.AdapterError):verify.verify(vreq)
            (stage/".esa_staging_manifest.json").write_text('{"job_id":"a","job_id":"b"}',encoding="utf-8")
            vreq["dry_run"]=True
            with self.assertRaises(verify.AdapterError) as e:verify.verify(vreq)
            self.assertEqual(e.exception.code,"SOURCE_NOT_VERIFIED")

    def test_failed_cli_readback_rolls_back_real_write(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as td:
            base,req,stage=self.setup_bundle(td,status="approved");self.assertTrue(render.render(req)["result"]["ok"])
            root=base/"vault";root.mkdir(exist_ok=True);os.environ["OBSIDIAN_VAULT_ROOT"]=str(root)
            # A disposable fake CLI reports supported syntax but wrong readback bytes.
            preq={**req,"vault_root":str(root),"dry_run":False,"payload":{**req["payload"],"staging_dir":str(stage),"allow_write":True,"publish_policy":{"require_cli_validation":True},"obsidian_executable":"fake-obsidian","vault_name":"Fixture","runtime_dir":str(base/"runtime")}}
            def fake_run(args,**kwargs):
                if args[-1]=="help":return type("R",(),{"returncode":0,"stdout":"read vault info","stderr":""})()
                if args[-1]=="info":return type("R",(),{"returncode":0,"stdout":str(root),"stderr":""})()
                return type("R",(),{"returncode":0,"stdout":b"wrong","stderr":b""})()
            with patch.object(publish.subprocess,"run",side_effect=fake_run):
                with self.assertRaises(publish.AdapterError) as e:publish.publish(preq)
            self.assertEqual(e.exception.status,"rolled_back")
            self.assertFalse((root/"Synthetic/Job/01_原文.md").exists())
            rb=json.loads((base/"runtime/rollback_manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(rb["restored"])

if __name__=="__main__":unittest.main()
