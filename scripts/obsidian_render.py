#!/usr/bin/env python3
"""Offline Obsidian renderer for the B-接口-02/03 adapter contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from urllib.parse import quote
from verify_source import canonical_source_article
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
COMMON_IN = ("interface_id", "interface_name", "job_id", "schema_version", "vault_root", "target_scope", "source_sha256", "dry_run", "payload")
COMMON_OUT = ("ok", "status", "output_files", "details")
REQ_STATUS = {"draft", "source_checked", "engineering_reviewed", "approved", "blocked"}


class AdapterError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False, status: str = "blocked", details=None):
        super().__init__(message)
        self.code, self.retryable, self.status, self.details = code, retryable, status, details or {}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_clauses_sha(clauses: dict) -> str:
    return sha(json.dumps(clauses,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8"))

def canonical_object_sha(value: dict) -> str:
    return sha(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8"))


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterError("INPUT_INVALID", "无法读取所需 JSON 输入", details={"input": path.name}) from exc


def safe_relative(raw: str) -> PurePosixPath:
    if not isinstance(raw, str) or not raw or "\\" in raw or raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise AdapterError("PATH_OUTSIDE_VAULT", "路径必须是 Vault 内的 POSIX 相对路径")
    if raw in (".", "./") or any(part in ("", ".") for part in raw.split("/")):
        raise AdapterError("PATH_OUTSIDE_VAULT", "路径不能为空或代表整个 Vault")
    p = PurePosixPath(raw)
    if any(part in ("..", "") for part in p.parts) or p.is_absolute():
        raise AdapterError("PATH_OUTSIDE_VAULT", "路径包含越界片段")
    reserved={"CON","PRN","AUX","NUL",*(f"COM{i}" for i in range(1,10)),*(f"LPT{i}" for i in range(1,10))}
    for part in p.parts:
        stem=part.split(".",1)[0].upper()
        if ":" in part or part.endswith(("."," ")) or stem in reserved:
            raise AdapterError("PATH_OUTSIDE_VAULT", "路径包含 Windows 非法或保留名称")
    return p


def yaml_text(obj) -> str:
    # JSON is a strict YAML 1.2 subset, so generated metadata stays valid YAML
    # while validation remains available in a stdlib-only installation.
    return json.dumps(obj, ensure_ascii=False, indent=2)


def validate_requirements(reqs):
    if not isinstance(reqs, dict) or reqs.get("schema_version") != "2.0":
        raise AdapterError("INPUT_INVALID", "requirements 必须符合 schemas/requirements.schema.json 的 2.0 契约")
    if not all(isinstance(reqs.get(k), str) and reqs[k] for k in ("standard_id", "edition")) or not isinstance(reqs.get("requirements"), list):
        raise AdapterError("INPUT_INVALID", "requirements 缺少标准号、版次或 requirements 数组")
    for row in reqs["requirements"]:
        required = ("requirement_id", "clause_id", "summary", "applicability", "source", "source_verified", "review_status")
        if not isinstance(row, dict) or any(k not in row for k in required):
            raise AdapterError("INPUT_INVALID", "requirements 条目缺少现有 schema 必填字段")
        if any(not isinstance(row.get(k), str) or not row[k] for k in ("requirement_id", "clause_id", "summary")) or row["applicability"] not in {"applicable", "conditional", "not_applicable", "unknown"} or row["review_status"] not in REQ_STATUS or not isinstance(row["source_verified"], bool):
            raise AdapterError("INPUT_INVALID", "requirements 条目枚举或布尔字段无效")
        if "requirement_level" in row and row["requirement_level"] not in {"mandatory", "recommended", "permitted", "informative", "unknown"}:
            raise AdapterError("INPUT_INVALID", "requirement_level 不符合现有 schema")
        source = row["source"]
        if not isinstance(source, dict) or any(k not in source for k in ("file", "sha256", "standard_id", "edition", "pdf_page")):
            raise AdapterError("INPUT_INVALID", "requirements.source 不符合现有 schema")
        if any(not isinstance(source.get(k),str) or not source[k] for k in ("file","sha256","standard_id","edition")) or (source["pdf_page"] is not None and (not isinstance(source["pdf_page"],int) or source["pdf_page"] < 1)):
            raise AdapterError("INPUT_INVALID", "requirements.source 类型或页码无效")
    ids = [r["requirement_id"] for r in reqs["requirements"]]
    if len(ids) != len(set(ids)):
        raise AdapterError("INPUT_INVALID", "requirement_id 重复")


def gate(req: dict, reqs: dict, verified: dict, article_path: Path, clauses_path: Path, registry: dict):
    if verified.get("source_complete") is not True or verified.get("review_status") != "source_checked":
        raise AdapterError("SOURCE_NOT_VERIFIED", "冻结源未完整且经核验", details={"gate": "verified_source"})
    sr = verified.get("source_review")
    if not isinstance(sr, dict) or not all(isinstance(sr.get(k), str) and sr[k].strip() for k in ("reviewer", "reviewed_at", "approval_evidence")):
        raise AdapterError("SOURCE_NOT_VERIFIED", "缺少有效的源审核记录", details={"gate": "source_review"})
    if verified.get("blockers")!=[] or not isinstance(verified.get("checklist"),list) or not verified["checklist"] or any(not isinstance(x,dict) or x.get("status") not in ("reviewed","complete","pass","not_applicable") for x in verified["checklist"]):
        raise AdapterError("SOURCE_NOT_VERIFIED","verified_source 存在 blocker 或覆盖清单未完成")
    inventory=verified.get("expected_inventory")
    if not isinstance(inventory,dict) or any(k not in inventory or not isinstance(inventory[k],list) for k in ("pages","chapters","normative_annexes","tables","figures","references")):
        raise AdapterError("SOURCE_NOT_VERIFIED","verified_source 缺少完整 expected_inventory")
    if verified.get("source_sha256") != req["source_sha256"]:
        raise AdapterError("SOURCE_NOT_VERIFIED", "请求哈希与冻结源不一致")
    try: clauses=json.loads(clauses_path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc:raise AdapterError("SOURCE_NOT_VERIFIED","clauses.json 无法解析") from exc
    canonical_hash=canonical_clauses_sha(clauses)
    source_path = Path(verified.get("source_file", "")).expanduser().resolve()
    if not source_path.is_file() or sha(source_path.read_bytes()) != req["source_sha256"] or clauses.get("source",{}).get("sha256")!=req["source_sha256"] or str(Path(clauses.get("source",{}).get("file", "")).resolve())!=str(source_path):
        raise AdapterError("SOURCE_NOT_VERIFIED", "源文件不存在或实际 SHA256 与冻结记录不一致")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(verified.get("clauses_sha256", ""))) or canonical_hash != verified.get("clauses_sha256"):
        raise AdapterError("SOURCE_NOT_VERIFIED", "clauses.json canonical SHA256 与冻结记录不一致")
    actual_article = sha(article_path.read_bytes())
    canonical_article=canonical_source_article(clauses)
    if verified.get("article_sha256") != actual_article or article_path.read_bytes()!=canonical_article or actual_article!=sha(canonical_article):
        raise AdapterError("SOURCE_NOT_VERIFIED", "文章与 clauses canonical article 或冻结哈希不一致")
    if reqs.get("source_complete") is not True or reqs.get("standard_id")!=clauses.get("standard_id") or str(reqs.get("edition"))!=str(clauses.get("edition")):
        raise AdapterError("SOURCE_NOT_VERIFIED", "requirements 标准或版次与 clauses 不一致")
    validate_requirements(reqs)
    if not reqs.get("requirements"):
        raise AdapterError("INPUT_INVALID", "requirements 为空")
    for row in reqs["requirements"]:
        if row.get("review_status") not in REQ_STATUS:
            raise AdapterError("INPUT_INVALID", "要求审核状态无效")
        if row.get("source", {}).get("sha256") != req["source_sha256"]:
            raise AdapterError("SOURCE_NOT_VERIFIED", "要求引用的源文件哈希不匹配")
        block=next((b for b in clauses.get("blocks",[]) if b.get("block_id")==row.get("block_id")),None)
        if not block or block.get("clause_id")!=row.get("clause_id") or not row.get("quote") or row["quote"] not in block.get("original_text",""):
            raise AdapterError("SOURCE_NOT_VERIFIED", "要求的 block_id、clause_id 或逐字 quote 无法回溯到 clauses")
        bs=block.get("source",{}); rs=row.get("source",{})
        for key in ("file","sha256","pdf_page","page_kind","locator"):
            if rs.get(key)!=bs.get(key):raise AdapterError("SOURCE_NOT_VERIFIED", "要求来源定位与 clauses block 不一致",details={"field":key,"requirement_id":row.get("requirement_id")})
        if rs.get("standard_id")!=reqs["standard_id"] or str(rs.get("edition"))!=str(reqs["edition"]):raise AdapterError("SOURCE_NOT_VERIFIED","要求来源标准/版次与 requirements 不一致")
        if row.get("review_status") in {"source_checked","engineering_reviewed","approved"} and (row.get("source_verified") is not True or not isinstance(row.get("source_review"),dict) or not all(isinstance(row["source_review"].get(k),str) and row["source_review"][k].strip() for k in ("reviewer","reviewed_at","approval_evidence"))):
            raise AdapterError("SOURCE_NOT_VERIFIED","已核验或 approved 要求缺少 source_verified/source_review")
        if row.get("review_status") == "approved":
            rr = row.get("review_record")
            if not isinstance(rr, dict) or not all(isinstance(rr.get(k), str) and rr[k].strip() for k in ("reviewer", "reviewed_at", "approval_evidence")):
                raise AdapterError("SOURCE_NOT_VERIFIED", "approved 要求缺少真实审核记录")
    headings={h.get("block_id"):h for h in registry.get("headings",[]) if h.get("block_id") and h.get("title")}
    blocks={b.get("block_id"):b for b in clauses.get("blocks",[])}
    for row in reqs["requirements"]:
        heading=headings.get(row.get("block_id")); block=blocks.get(row.get("block_id"))
        hs=heading.get("source",{}) if heading else {};bs=block.get("source",{}) if block else {}
        if not heading or not block or heading.get("clause_id")!=row.get("clause_id") or any(hs.get(k)!=bs.get(k) for k in ("file","sha256","pdf_page","page_kind","locator")) or heading["title"] not in block.get("original_text",""):
            raise AdapterError("SOURCE_NOT_VERIFIED","标题登记项未在对应源语 block 中找到")
    if not re.fullmatch(r"[0-9a-fA-F]{64}",str(verified.get("heading_registry_sha256",""))) or canonical_object_sha(registry)!=verified.get("heading_registry_sha256"):
        raise AdapterError("SOURCE_NOT_VERIFIED","titles registry canonical SHA256 与冻结源不一致")


def quote_yaml(s: str) -> str:
    return json.dumps(str(s), ensure_ascii=False)


def render_note(req: dict, job_id: str, standard_id: str, edition: str, source_hash: str, titles: dict, article_name: str) -> str:
    rid = req["requirement_id"]
    clause = req["clause_id"]
    title = titles.get(clause)
    if not title:
        raise AdapterError("SOURCE_NOT_VERIFIED", "缺少该条款的已核验源语标题", details={"clause_id": clause})
    source = req["source"]
    status = req["review_status"]
    fm = {
        "title": f"{clause} · {title}", "esa_doc_kind": "requirement", "esa_job_id": job_id,
        "esa_standard_id": standard_id, "esa_edition": str(edition), "esa_source_sha256": source_hash,
        "esa_clause_id": clause, "esa_requirement_id": rid, "esa_review_status": status,
        "esa_requirement_level": req.get("requirement_level", "unknown"), "esa_pdf_page": source.get("pdf_page"),
        "tags": ["standard/requirement", f"esa/{status}"],
    }
    body = [f"# {clause} {title}", "", f"> [!warning] {status}", "> 此笔记仅反映冻结源及其审核状态；未批准内容不得用于正式符合性判断。", "", "## 原文证据"]
    original_quote = req.get("quote") or source.get("quote")
    if original_quote:
        body.extend(["> " + str(original_quote).replace("\n", "\n> "), ""])
    else:
        body.extend(["原文证据尚未提供。", ""])
    body.extend(["## 要求摘要", str(req.get("summary", "")), "", "## 来源追溯", f"- PDF 页码：{source.get('pdf_page')}", f"- 冻结源哈希：`{source_hash}`", f"- 源语全文：[[{article_name}]]", ""])
    return "---\n" + yaml_text(fm) + "\n---\n\n" + "\n".join(body)


def make_base(job_id: str, standard_id: str, folder: str, approved_view: bool = True) -> str:
    safe_relative(folder)
    views = [
        {"type": "table", "name": "要求总览", "order": ["file.name", "esa_clause_id", "esa_requirement_id", "esa_requirement_level", "esa_review_status", "esa_pdf_page"]},
        {"type": "table", "name": "待复核", "filters": {"and": ['esa_review_status != "approved"']}, "order": ["file.name", "esa_clause_id", "esa_review_status"]},
    ]
    if approved_view:
        views.append({"type": "table", "name": "已批准要求", "filters": {"and": ['esa_review_status == "approved"']}, "order": ["file.name", "esa_clause_id", "esa_requirement_id"]})
    return yaml_text({"filters": {"and": [f'file.inFolder("{folder}")', 'file.ext == "md"', 'esa_doc_kind == "requirement"', f'esa_job_id == "{job_id}"', f'esa_standard_id == "{standard_id}"']}, "views": views}) + "\n"


def render(request: dict) -> dict:
    if list(request.keys())[:len(COMMON_IN)] != list(COMMON_IN):
        raise AdapterError("INPUT_INVALID", "接口公共字段顺序不符合 B 契约")
    if request.get("interface_id") == "B-接口-03" and request.get("interface_name") == "render_obsidian_base":
        return render_base(request)
    if request.get("interface_id") != "B-接口-02" or request.get("interface_name") != "render_obsidian_markdown" or request.get("schema_version") != "1.0":
        raise AdapterError("INPUT_INVALID", "接口标识或契约版本错误")
    if not isinstance(request.get("job_id"),str) or not request["job_id"] or not isinstance(request.get("vault_root"),str) or not request["vault_root"] or not isinstance(request.get("target_scope"),str) or not isinstance(request.get("dry_run"),bool) or not isinstance(request.get("payload"),dict) or not re.fullmatch(r"[0-9a-fA-F]{64}",str(request.get("source_sha256",""))):
        raise AdapterError("INPUT_INVALID","B-接口-02 公共字段类型或哈希格式无效")
    payload = request["payload"]
    req_path = Path(payload["requirements_path"]).resolve()
    verified_path = Path(payload["verified_source_path"]).resolve()
    clauses_path = Path(payload["clauses_path"]).resolve()
    article_path = Path(payload.get("article_path") or load_json(verified_path).get("article_path", "")).resolve()
    reqs, verified = load_json(req_path), load_json(verified_path)
    registry = load_json(Path(payload["titles_registry_path"]).resolve())
    gate(request, reqs, verified, article_path, clauses_path, registry)
    registry_path = Path(payload["titles_registry_path"]).resolve()
    if registry.get("source_sha256") != request["source_sha256"]:
        raise AdapterError("SOURCE_NOT_VERIFIED", "标题登记表源哈希不匹配")
    titles = {}
    for h in registry.get("headings", []):
        if not h.get("title"):
            continue
        if h.get("source", {}).get("sha256") != request["source_sha256"]:
            continue
        for key in (h.get("clause_id"), h.get("heading_id"), h.get("block_id")):
            if key:
                titles[str(key)] = h["title"]
    outdir = Path(payload["staging_dir"]).resolve()
    scope = safe_relative(request["target_scope"].rstrip("/"))
    requirement_dir = str(scope / "04_要求")
    article_name = "01_原文"
    outputs = []
    # Validate generated YAML with the installed parser before staging.
    notes = []
    for row in reqs["requirements"]:
        lookup = dict(titles)
        if row.get("heading_id") and row["heading_id"] in titles:
            lookup[row["clause_id"]] = titles[row["heading_id"]]
        if row.get("block_id") and row["block_id"] in titles:
            lookup[row["clause_id"]] = titles[row["block_id"]]
        text = render_note(row, request["job_id"], reqs["standard_id"], reqs["edition"], request["source_sha256"], lookup, article_name)
        front = text.split("---", 2)[1]
        json.loads(front)
        notes.append((row["requirement_id"], text))
    base = make_base(request["job_id"], reqs["standard_id"], requirement_dir)
    json.loads(base)
    for rid, text in notes:
        filename=quote(rid,safe="-_.()")+".md"
        outputs.append((str(scope / "04_要求" / filename), text))
    outputs.append((str(scope / "标准要求总览.base"), base))
    article_text = article_path.read_text(encoding="utf-8")
    translation_content=[]
    translation_path=payload.get("translations_path")
    if translation_path:
        try:
            from render_full_articles import render as render_articles
            translations=load_json(Path(translation_path).resolve())
            rendered=render_articles(json.loads(clauses_path.read_text(encoding="utf-8")),translations,verified)
            article_manifest_path=Path(payload["article_manifest_path"]).resolve()
            article_manifest=load_json(article_manifest_path)
        except (KeyError,ValueError,AdapterError) as exc:
            raise AdapterError("SOURCE_NOT_VERIFIED","翻译全文或 article_manifest 校验失败") from exc
        if article_manifest.get("source_article_sha256")!=verified.get("article_sha256") or article_manifest.get("source_status")!="source_checked" or article_manifest.get("translation_status")!=rendered.get("translation_status"):
            raise AdapterError("SOURCE_NOT_VERIFIED","article_manifest 与冻结源/翻译审核状态不一致")
        manifest_dir=article_manifest_path.parent
        for srcname, targetname, field in (("04_Translation_Complete.md","04_Translation_Complete.md","chinese"),("05_Bilingual_Complete.md","05_Bilingual_Complete.md","bilingual")):
            actual=manifest_dir/srcname
            if not actual.is_file() or rendered.get(field) is None or actual.read_text(encoding="utf-8")!=rendered[field]:
                raise AdapterError("SOURCE_NOT_VERIFIED","全文译文与 article_manifest 输入不一致",details={"file":srcname})
            if re.search(r"(?i)\b(?:TODO|TBD|PLACEHOLDER)\b|\[translation missing\]",rendered[field]):
                raise AdapterError("SOURCE_NOT_VERIFIED","全文译文仍含占位内容",details={"file":srcname})
            translation_content.append((str(scope/targetname),rendered[field]))
    # Every declared attachment must be relative to the bundle and match its recorded byte hash.
    attachment_outputs = []
    for item in payload.get("attachments", []):
        src = Path(item["source_path"]).resolve()
        if not src.is_file():
            raise AdapterError("LINK_TARGET_MISSING", "附件源文件不存在")
        rel = safe_relative(item["target_path"])
        actual = sha(src.read_bytes())
        if item.get("sha256") != actual:
            raise AdapterError("LINK_TARGET_MISSING", "附件哈希不匹配", details={"attachment": rel.as_posix()})
        attachment_outputs.append((str(scope / rel), src.read_bytes()))
    # Convert absolute source image references to portable Vault embeds using
    # the explicit attachment map. Unknown drive/root paths are rejected.
    attachment_map = {os.path.normcase(str(Path(x["source_path"]).resolve())): x["target_path"] for x in payload.get("attachments", [])}
    def replace_image(match):
        raw = match.group(2).strip().strip("<>")
        if re.match(r"^[A-Za-z]:[\\/]", raw) or raw.startswith("/"):
            target = attachment_map.get(os.path.normcase(str(Path(raw).resolve())))
            if not target:
                raise AdapterError("LINK_TARGET_MISSING", "全文含未映射的绝对附件路径", details={"target": Path(raw).name})
            rel = safe_relative(target)
            return f"![[{rel.as_posix()}]]"
        return match.group(0)
    # Greedy line-local destination preserves literal parentheses in Windows paths.
    article_text = re.sub(r"!\[([^\]]*)\]\(([^\n]+)\)", replace_image, article_text)
    if re.search(r"(?i)(?:[A-Z]:[\\/]|file://)", article_text):
        raise AdapterError("LINK_TARGET_MISSING", "源语全文保留绝对文件路径")
    article_links = re.findall(r"!?\[\[([^\]]+)\]\]", article_text)
    known = {"01_原文", "01_原文.md"} | {Path(p).stem for p, _ in outputs}
    known |= {PurePosixPath(rel).stem for rel, _ in attachment_outputs}
    known_paths={str(PurePosixPath(p)) for p,_ in outputs}|{str(PurePosixPath(p)) for p,_ in attachment_outputs}|{str(scope/"01_原文.md")}
    for target in article_links:
        target = target.split("|", 1)[0].split("#", 1)[0]
        if target:
            safe_relative(target)
            staged_target = str(scope / PurePosixPath(target))
            if "/" in target and staged_target not in known_paths and (staged_target + ".md") not in known_paths:
                raise AdapterError("LINK_TARGET_MISSING", "显式目录内链未命中已知文件", details={"target": Path(target).name})
        if target and Path(target).stem not in known:
            raise AdapterError("LINK_TARGET_MISSING", "源语全文含无法解析的 Vault 内链", details={"target": Path(target).name})
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", article_text):
        target = target.strip().strip("<>").split("#",1)[0]
        if not target or re.match(r"(?i)^(?:https?|mailto):",target):
            continue
        if re.match(r"^[A-Za-z]:[\\/]",target) or target.startswith("/"):
            raise AdapterError("LINK_TARGET_MISSING", "全文含绝对 Markdown 链接")
        norm=PurePosixPath(target)
        resolved=(PurePosixPath(str(scope))/norm)
        if ".." in norm.parts or str(resolved) not in known_paths:
            raise AdapterError("LINK_TARGET_MISSING", "源语全文含无法解析的相对 Markdown 链接", details={"target": Path(target).name})
    outputs.append((str(scope / "01_原文.md"), article_text))
    outputs.extend(translation_content)
    outputs.extend((path, data.decode("utf-8") if PurePosixPath(path).suffix.lower() in (".md", ".base", ".txt") else data) for path, data in attachment_outputs)
    run_root=Path(payload.get("run_root",req_path.parent)).resolve()
    try:outdir.relative_to(run_root)
    except ValueError:raise AdapterError("PATH_OUTSIDE_VAULT","staging_dir 必须位于当前 RUN/publish staging 内")
    try:outdir.relative_to(Path(request["vault_root"]).resolve())
    except ValueError:pass
    else:raise AdapterError("PATH_OUTSIDE_VAULT","staging_dir 必须位于 vault_root 外的 RUN staging")
    body_bytes=[(p,t.encode("utf-8") if isinstance(t,str) else t) for p,t in outputs]
    manifest={"schema_version":"1.0","job_id":request["job_id"],"target_scope":str(scope),"source_sha256":request["source_sha256"],"clauses_sha256":verified["clauses_sha256"],"heading_registry_sha256":verified["heading_registry_sha256"],"files":[{"path":p,"sha256":sha(data)} for p,data in body_bytes]}
    manifest_bytes=(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    plan=[]
    folded=set()
    for rel,data in body_bytes:
        safe_relative(rel);key=rel.casefold()
        if key in folded:raise AdapterError("PATH_OUTSIDE_VAULT","staging 输出存在大小写路径碰撞")
        folded.add(key);dest=outdir.joinpath(*PurePosixPath(rel).parts)
        current=outdir
        for part in PurePosixPath(rel).parts:
            current=current/part
            if current.is_symlink():raise AdapterError("PATH_OUTSIDE_VAULT","staging 目标包含符号链接")
        if dest.exists() and (not dest.is_file() or sha(dest.read_bytes())!=sha(data)):
            raise AdapterError("WRITE_CONFLICT","staging 文件已存在且内容不同",details={"path":rel})
        plan.append((dest,data))
    mpath=outdir/".esa_staging_manifest.json"
    if mpath.exists() and (not mpath.is_file() or mpath.read_bytes()!=manifest_bytes):raise AdapterError("WRITE_CONFLICT","staging manifest 已存在且内容不同")
    created=[]
    try:
        for dest,data in plan:
            if dest.exists():continue
            dest.parent.mkdir(parents=True,exist_ok=True);fd=os.open(dest,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            created.append((dest,sha(data)))
            with os.fdopen(fd,"wb") as f:
                try:f.write(data);f.flush();os.fsync(f.fileno())
                except Exception:
                    try:f.flush()
                    except OSError:pass
                    created[-1]=(dest,sha(dest.read_bytes()))
                    raise
        if not mpath.exists():
            outdir.mkdir(parents=True,exist_ok=True);fd=os.open(mpath,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            created.append((mpath,sha(manifest_bytes)))
            with os.fdopen(fd,"wb") as f:
                try:f.write(manifest_bytes);f.flush();os.fsync(f.fileno())
                except Exception:
                    try:f.flush()
                    except OSError:pass
                    created[-1]=(mpath,sha(mpath.read_bytes()))
                    raise
    except Exception as exc:
        for dest,h in reversed(created):
            try:
                if dest.is_file() and sha(dest.read_bytes())==h:dest.unlink()
            except OSError:pass
        if isinstance(exc,AdapterError):raise
        raise AdapterError("PARTIAL_WRITE","staging 输出中断，已清除本次创建文件",status="rolled_back") from exc
    return {"interface_id": "B-接口-02", "interface_name": "render_obsidian_markdown", "job_id": request["job_id"], "schema_version": "1.0", "result": {"ok": True, "status": "ok", "output_files": [p for p, _ in outputs], "details": {"rendered_count": len(notes) + 2, "dry_run": request["dry_run"], "staging_written": True, "vault_written": False, "yaml_valid": True}}}


def render_base(request: dict) -> dict:
    if list(request.keys())[:len(COMMON_IN)] != list(COMMON_IN):
        raise AdapterError("INPUT_INVALID", "接口公共字段顺序不符合 B 契约")
    if request.get("schema_version") != "1.0" or not re.fullmatch(r"[0-9a-fA-F]{64}", str(request.get("source_sha256", ""))):
        raise AdapterError("INPUT_INVALID", "Bases 接口契约版本或源哈希无效")
    if not isinstance(request.get("job_id"),str) or not request["job_id"] or not isinstance(request.get("vault_root"),str) or not request["vault_root"] or not isinstance(request.get("target_scope"),str) or not isinstance(request.get("dry_run"),bool) or not isinstance(request.get("payload"),dict):raise AdapterError("INPUT_INVALID","B-接口-03 公共字段类型无效")
    p=request["payload"]
    scope=safe_relative(request["target_scope"].rstrip("/"))
    folder=safe_relative(p.get("frontmatter_dir", str(scope/"04_要求")))
    if tuple(folder.parts[:len(scope.parts)]) != scope.parts:
        raise AdapterError("PATH_OUTSIDE_VAULT", "frontmatter_dir 必须位于目标作用域内")
    name=p.get("base_name", "标准要求总览.base")
    if Path(name).name != name or not name.endswith(".base"):
        raise AdapterError("PATH_OUTSIDE_VAULT", "base_name 必须是单一 .base 文件名")
    standard=p.get("standard_id")
    if not standard:
        raise AdapterError("INPUT_INVALID", "B-接口-03 payload.standard_id 必填")
    content=make_base(request["job_id"],standard,str(folder))
    json.loads(content)
    rel=str(scope/name); outdir=Path(p.get("staging_dir", "")).resolve()
    run_root=Path(p.get("run_root",outdir.parent)).resolve()
    try:outdir.relative_to(run_root)
    except ValueError:raise AdapterError("PATH_OUTSIDE_VAULT","staging_dir 必须位于当前 RUN staging 内")
    try:outdir.relative_to(Path(request["vault_root"]).resolve())
    except ValueError:pass
    else:raise AdapterError("PATH_OUTSIDE_VAULT","staging_dir 必须位于 vault_root 外的 RUN staging")
    data=content.encode("utf-8");dest=outdir.joinpath(*PurePosixPath(rel).parts);manifest_path=outdir/".esa_staging_manifest.json"
    if dest.exists() and dest.read_bytes()!=data:raise AdapterError("WRITE_CONFLICT","staging Bases 文件已存在且内容不同")
    manifest={"schema_version":"1.0","job_id":request["job_id"],"target_scope":str(scope),"source_sha256":request["source_sha256"],"files":[{"path":rel,"sha256":sha(data)}]}
    mdata=(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n").encode()
    if manifest_path.exists() and manifest_path.read_bytes()!=mdata:raise AdapterError("WRITE_CONFLICT","staging manifest 已存在且内容不同")
    if not dest.exists():
        dest.parent.mkdir(parents=True,exist_ok=True);fd=os.open(dest,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())
    if not manifest_path.exists():
        outdir.mkdir(parents=True,exist_ok=True);fd=os.open(manifest_path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"wb") as f:f.write(mdata);f.flush();os.fsync(f.fileno())
    return {"interface_id":"B-接口-03","interface_name":"render_obsidian_base","job_id":request["job_id"],"schema_version":"1.0","result":{"ok":True,"status":"ok","output_files":[rel],"details":{"views":3,"yaml_valid":True,"dry_run":request["dry_run"]}}}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("request", nargs="?", help="B-接口-02 JSON request")
    args = ap.parse_args()
    if not args.request:
        return 0
    try:
        result = render(load_json(Path(args.request)))
    except AdapterError as exc:
        result = {"interface_id": "B-接口-02", "interface_name": "render_obsidian_markdown", "job_id": "", "schema_version": "1.0", "result": {"ok": False, "status": exc.status, "output_files": [], "details": {}, "error": {"code": exc.code, "message": str(exc), "retryable": exc.retryable, "details": exc.details}}}
    except Exception:
        result = {"interface_id": "B-接口-02", "interface_name": "render_obsidian_markdown", "job_id": "", "schema_version": "1.0", "result": {"ok": False, "status": "blocked", "output_files": [], "details": {}, "error": {"code": "INPUT_INVALID", "message": "输入处理失败", "retryable": False, "details": {}}}}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["result"]["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
