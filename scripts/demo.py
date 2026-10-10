#!/usr/bin/env python3
"""Run an offline end-to-end demonstration with clearly fictional sources."""
import argparse
import json
import secrets
import shutil
import sys
from datetime import datetime
from pathlib import Path

import esa


EN = """DEMO ONLY — FICTIONAL STANDARD.\n4.1 Shall run thermal test at 23 °C ± 2 °C with 3 samples.\nMeasure peak temperature; accept when drift ≤ 2 °C; record results."""
JA = """デモ専用—架空標準。\n4.1 23 °C ± 2 °Cで3個の試料を用いて熱試験を実施する。\nピーク温度を測定し、ドリフトが ≤ 2 °Cの場合に受け入れ、結果を記録する。"""
PLAN = """# DEMO ONLY — FICTIONAL TEST PLAN\n\n## English demonstration test\nthermal test; run thermal test; conditions 23 °C ± 2 °C; sample 3 samples; measurement peak temperature; acceptance drift ≤ 2 °C; records record results.\n\n## Japanese demonstration test\n熱試験; 熱試験を実施; conditions 23 °C ± 2 °C; sample 3個の試料; measurement ピーク温度; acceptance ドリフトが ≤ 2 °C; records 結果を記録.\n"""
EN_FIELDS = {
    "test_item":"thermal test", "method":"run thermal test", "conditions":"23 °C ± 2 °C",
    "sample":"3 samples", "measurement":"peak temperature", "acceptance_criteria":"drift ≤ 2 °C", "records":"record results"
}
JA_FIELDS = {
    "test_item":"熱試験", "method":"熱試験を実施", "conditions":"23 °C ± 2 °C",
    "sample":"3個の試料", "measurement":"ピーク温度", "acceptance_criteria":"ドリフトが ≤ 2 °C", "records":"結果を記録"
}
EN_ZH = "仅演示—虚构标准。4.1 应在 23 °C ± 2 °C 条件下使用 3 个样品进行热试验。测量峰值温度；当漂移 ≤ 2 °C 时接受；记录结果。"
JA_ZH = "仅演示—虚构标准。4.1 在 23 °C ± 2 °C 条件下使用 3 个样品实施热试验。测量峰值温度；漂移 ≤ 2 °C 时接受；记录结果。"


def write_pdf(path, content, language):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas
    font="HeiseiMin-W3"
    pdfmetrics.registerFont(UnicodeCIDFont(font))
    c=canvas.Canvas(str(path), pagesize=(612,792), pageCompression=0)
    c.setTitle("DEMO ONLY — FICTIONAL STANDARD")
    c.setFont(font,11)
    y=740
    for line in content.splitlines():
        c.drawString(45,y,line); y-=24
    c.showPage(); c.save()


def _fields(texts):
    return {k:{"quote":v,"value":v} for k,v in texts.items()}


def _make_run(source, language, standard_id, fields, translation, stage, plan_path):
    prep=stage/"prepare"
    clauses=esa.prepare(source,prep,standard_id,"DEMO-ONLY-1",language)
    clauses["blocks"][0]["clause_id"]="4.1"
    esa.write(prep/"clauses.json",clauses)
    block=clauses["blocks"][0]
    annotations={"schema_version":"2.0","standard_id":standard_id,"edition":"DEMO-ONLY-1",
        "source_complete":False,"coverage_review":{},"requirements":[{
            "requirement_id":"DEMO-REQ-1","block_id":block["block_id"],"quote":block["original_text"],
            "summary":"Fictional demonstration requirement; not a real standard clause.",
            "requirement_level":"unknown","applicability":"applicable","fields":_fields(fields),
            "not_required":[],"source_review":{}
        }]}
    ann_path=stage/"annotations.json"; esa.write(ann_path,annotations)
    plan_doc=__import__("local_parser").extract_document(plan_path)
    plan_quote=plan_doc["pages"][0]["text"]
    locator=plan_doc["pages"][0]["locator"]
    plan_fields={k:{"quote":v,"value":v} for k,v in fields.items()}
    plan_annotations={"plan_id":"DEMO-PLAN","plan_version":"DRAFT-1","source_sha256":plan_doc["sha256"],"tests":[{
        "test_id":"DEMO-TEST-1","title":"Fictional demonstration test","locator":locator,"quote":plan_quote,"requirement_ids":["DEMO-REQ-1"],"fields":plan_fields
    }]}
    plan_ann_path=stage/"plan_annotations.json"; esa.write(plan_ann_path,plan_annotations)
    seg={"block_id":block["block_id"],"clause_id":block["clause_id"],"pdf_page":block["source"]["pdf_page"],
        "source_lang":language,"target_lang":"zh-CN","original_text":block["original_text"],
        "translated_text":translation,"protected_tokens":[],"source":block["source"],
        "source_quote":block["original_text"],"human_reviewed":False}
    trans=stage/"translations.json"; esa.write(trans,{"schema_version":"2.0","segments":[seg]})
    return prep/"clauses.json",ann_path,plan_ann_path,trans


def run(out, mode="auto"):
    out=Path(out).expanduser().resolve()
    if out.exists(): raise ValueError("demo output exists; choose a new path")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.mkdir()
    source_dir=out/"inputs"
    source_dir.mkdir()
    stage=source_dir/"work"; stage.mkdir()
    plan_path=source_dir/"experiment-plan.md"; plan_path.write_text(PLAN,encoding="utf-8")
    use_pdf=mode!="md"
    if use_pdf:
        try: import reportlab  # noqa: F401
        except ImportError:
            if mode=="pdf": raise RuntimeError("PDF demo requires the bundled/local reportlab runtime; no download attempted")
            use_pdf=False
    ext="pdf" if use_pdf else "md"
    sources=[]
    for lang,content in (("en",EN),("ja",JA)):
        source=source_dir/f"fictional-standard-{lang}.{ext}"
        if use_pdf: write_pdf(source,content,lang)
        else: source.write_text(content,encoding="utf-8")
        sources.append(source)
    produced=[]
    for lang,source,stdid,fields,trtext in (("en",sources[0],"DEMO-EN",EN_FIELDS,EN_ZH),("ja",sources[1],"DEMO-JA",JA_FIELDS,JA_ZH)):
        prep=stage/lang; prep.mkdir()
        clause_path,ann_path,plan_ann_path,trans=_make_run(source,lang,stdid,fields,trtext,prep,plan_path)
        result=out/lang
        esa.run(clause_path,ann_path,plan_path,plan_ann_path,result,translations_path=trans)
        produced.append(result)
    for lang,source,result in zip(("en","ja"),sources,produced):
        shutil.copy2(source,out/source.name)
    shutil.copy2(plan_path,out/plan_path.name)
    study_counts={}
    for lang in ("en","ja"):
        study_counts[lang]=esa.export_study(esa.read(out/lang/"requirements.json"),out/f"study-{lang}")
    summary={"demo_only":True,"fictional_sources":True,"source_type":"pdf" if use_pdf else "markdown_non_pdf",
        "network_used":False,"source_review":"intentionally empty; requirements remain unverified",
        "translations_human_reviewed":False,"study_approved_counts":study_counts,
        "runs":{"en":str(out/"en"),"ja":str(out/"ja")}}
    (out/"demo-summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (out/"DEMO-ONLY.md").write_text("# DEMO ONLY\n\nAll standards and experiment details are fictional demonstration text. They are not ISO/JIS/IEC content. No source review or translation review is claimed. Any status is a text-evidence draft, not conformity.\n\nSource type: `"+summary["source_type"]+"`.\n",encoding="utf-8")
    return summary


def main(argv=None):
    ap=argparse.ArgumentParser(description="Run the offline ESA demo using fictional standard-like material.")
    ap.add_argument("--out",default=None); ap.add_argument("--format",choices=("auto","pdf","md"),default="auto")
    args=ap.parse_args(argv)
    if args.out is None:
        args.out=str(Path(__file__).resolve().parents[1]/"run"/("demo-"+datetime.now().strftime("%Y%m%d-%H%M%S")+"-"+secrets.token_hex(3)))
    try:
        result=run(args.out,args.format); print(json.dumps({"output":str(Path(args.out).resolve()),**result},ensure_ascii=False,indent=2)); return 0
    except (ValueError,RuntimeError,OSError) as exc:
        print(json.dumps({"error":str(exc),"status":"blocked"},ensure_ascii=False),file=sys.stderr); return 2


if __name__=="__main__": raise SystemExit(main())
