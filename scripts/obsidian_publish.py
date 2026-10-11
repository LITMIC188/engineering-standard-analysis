#!/usr/bin/env python3
"""Transactional publisher for offline Obsidian staging bundles.

Writes are opt-in (dry_run defaults true); a caller must set allow_write=true.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path, PurePosixPath

from obsidian_render import AdapterError, safe_relative, render as render_bundle, canonical_clauses_sha
from json_io import loads as strict_json_loads

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def log_event(path: Path, event: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Deliberately record metadata and hashes only; never note contents.
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

def resolve_inside(root: Path, relative: str, must_exist=False) -> Path:
    rel = safe_relative(relative)
    cur = root
    for part in rel.parts:
        cur = cur / part
        if cur.exists() and cur.is_symlink():
            raise AdapterError("PATH_OUTSIDE_VAULT", "目标路径包含符号链接")
    resolved = cur.resolve(strict=must_exist)
    try: resolved.relative_to(root.resolve())
    except ValueError as exc: raise AdapterError("PATH_OUTSIDE_VAULT", "目标路径超出 Vault 根目录") from exc
    return resolved

def cli_help(binary: str):
    try:
        return subprocess.run([binary, "help"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AdapterError("CLI_UNAVAILABLE", "Obsidian CLI help 不可用", True, "pending_cli_validation") from exc

def publish(req: dict):
    payload=req.get("payload",{})
    required=("interface_id","interface_name","job_id","schema_version","vault_root","target_scope","source_sha256","dry_run","payload")
    if tuple(list(req)[:len(required)])!=required or any(k not in req for k in required) or (req.get("interface_id"),req.get("interface_name"),req.get("schema_version"))!=("B-接口-02","render_obsidian_markdown","1.0"):
        raise AdapterError("INPUT_INVALID","发布请求必须沿用 B-接口-02 公共接口外壳")
    if not isinstance(req["dry_run"],bool) or not isinstance(payload.get("allow_write",False),bool):
        raise AdapterError("INPUT_INVALID","dry_run/allow_write 类型无效")
    root=Path(req["vault_root"]).expanduser().resolve(); scope=safe_relative(req["target_scope"].rstrip("/"));stage=Path(payload.get("staging_dir","")).resolve()
    if not stage.is_dir():raise AdapterError("INPUT_INVALID","staging_dir 不存在或不是目录")
    manifest_path=stage/".esa_staging_manifest.json"
    try:sm=strict_json_loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc:raise AdapterError("SOURCE_NOT_VERIFIED","缺少有效 staging manifest") from exc
    clauses_path=Path(payload.get("clauses_path","")).resolve()
    if not clauses_path.is_file():raise AdapterError("SOURCE_NOT_VERIFIED","发布需要原 clauses.json")
    try:actual_clauses=canonical_clauses_sha(strict_json_loads(clauses_path.read_text(encoding="utf-8")))
    except (OSError,json.JSONDecodeError) as exc:raise AdapterError("SOURCE_NOT_VERIFIED","clauses.json 无法解析") from exc
    try:verified_meta=strict_json_loads(Path(payload["verified_source_path"]).read_text(encoding="utf-8"));registry_meta=strict_json_loads(Path(payload["titles_registry_path"]).read_text(encoding="utf-8"))
    except (KeyError,OSError,json.JSONDecodeError) as exc:raise AdapterError("SOURCE_NOT_VERIFIED","verified_source/标题登记表缺失或无效") from exc
    from obsidian_render import canonical_object_sha
    if sm.get("schema_version")!="1.0" or sm.get("job_id")!=req["job_id"] or sm.get("target_scope")!=str(scope) or sm.get("source_sha256")!=req["source_sha256"] or sm.get("clauses_sha256")!=actual_clauses or sm.get("heading_registry_sha256")!=verified_meta.get("heading_registry_sha256") or canonical_object_sha(registry_meta)!=verified_meta.get("heading_registry_sha256"):
        raise AdapterError("SOURCE_NOT_VERIFIED","staging manifest 与作业、范围、源或 clauses 哈希不匹配")
    # TemporaryDirectory guarantees cleanup on every return and exception.
    with tempfile.TemporaryDirectory(prefix="esa-obsidian-preflight-",dir=str(stage.parent)) as preflight_name:
        preflight=Path(preflight_name)
        rerun=dict(req);rp=dict(payload);rp["staging_dir"]=str(preflight);rerun["payload"]=rp;rerun["dry_run"]=False
        render_bundle(rerun)
        def content_map(folder):
            return {p.relative_to(folder).as_posix():digest(p) for p in folder.rglob("*") if p.is_file() and p.name!=".esa_staging_manifest.json"}
        expected=content_map(preflight)
        if not isinstance(sm.get("files"),list) or any(not isinstance(x,dict) or not isinstance(x.get("path"),str) or not re.fullmatch(r"[0-9a-f]{64}",str(x.get("sha256",""))) for x in sm.get("files",[])):
            raise AdapterError("SOURCE_NOT_VERIFIED","staging manifest files 字段无效")
        listed={x["path"]:x["sha256"] for x in sm["files"]}
        if len(listed)!=len(sm["files"]):raise AdapterError("SOURCE_NOT_VERIFIED","staging manifest 包含重复路径")
        present=content_map(stage)
        if expected!=listed or present!=listed:
            raise AdapterError("SOURCE_NOT_VERIFIED","staging 清单与重新渲染内容不一致，可能被修改")
        if not expected:raise AdapterError("INPUT_INVALID","staging bundle 为空")
        policy=payload.get("publish_policy",{});require_approved=policy.get("require_approved",True)
        for rel in sorted(expected):
            p=stage.joinpath(*PurePosixPath(rel).parts)
            safe_relative(rel)
            if tuple(PurePosixPath(rel).parts[:len(scope.parts)])!=scope.parts:raise AdapterError("PATH_OUTSIDE_VAULT","发布文件超出 target_scope")
            if p.suffix.lower()==".md":
                text=p.read_text(encoding="utf-8")
                if re.search(r"(?i)\b(?:TODO|TBD|PLACEHOLDER|DRAFT PLACEHOLDER)\b|<\s*(?:actual|placeholder|占位|待填)",text):raise AdapterError("SOURCE_NOT_VERIFIED","生产发布文件含占位内容")
                if '"esa_doc_kind": "requirement"' in text:
                    approved='"esa_review_status": "approved"' in text
                    if require_approved and not approved:raise AdapterError("SOURCE_NOT_VERIFIED","生产发布要求笔记尚未 approved")
                    if not approved and "draft" not in scope.parts:raise AdapterError("SOURCE_NOT_VERIFIED","草案只能发布到独立 draft 作用域")
        # Validate staging tree has no symlink, aliases or case-insensitive collisions.
        folded=set()
        for node in stage.rglob("*"):
            if node.is_symlink():raise AdapterError("PATH_OUTSIDE_VAULT","staging 目录包含符号链接")
            if node.is_file() and node.name!=".esa_staging_manifest.json":
                rel=node.relative_to(stage).as_posix();key=rel.casefold()
                if key in folded:raise AdapterError("PATH_OUTSIDE_VAULT","staging 中存在大小写冲突路径")
                folded.add(key)
        if req["dry_run"] or not payload.get("allow_write",False):
            return {"interface_id":"B-接口-05","interface_name":"publish_obsidian_bundle","job_id":req["job_id"],"schema_version":"1.0","result":{"ok":True,"status":"ok","output_files":list(expected),"details":{"dry_run":True,"preflight_valid":True,"write_count":0}}}
        envroot=os.environ.get("OBSIDIAN_VAULT_ROOT")
        if not envroot or Path(envroot).expanduser().resolve()!=root or not root.is_dir():raise AdapterError("VAULT_ROOT_MISMATCH","vault_root 必须与 OBSIDIAN_VAULT_ROOT 一致且为目录")
        policy=payload.get("publish_policy",{});require_cli=policy.get("require_cli_validation",True);binary=payload.get("obsidian_executable","obsidian");vault=payload.get("vault_name")
        if require_cli:
            if not vault:raise AdapterError("CLI_UNAVAILABLE","强制 CLI 策略需要 vault_name",True,"pending_cli_validation")
            h=cli_help(binary)
            if h.returncode or "read" not in h.stdout+h.stderr or "vault" not in h.stdout+h.stderr or "info" not in h.stdout+h.stderr:
                raise AdapterError("CLI_UNAVAILABLE","CLI 未证明 help/read/vault info 能力，写入前阻断",True,"pending_cli_validation")
            try:probe=subprocess.run([binary,f"vault={vault}","info"],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=15,check=False)
            except (OSError,subprocess.TimeoutExpired) as exc:raise AdapterError("CLI_UNAVAILABLE","无法探测指定 vault 根目录",True,"pending_cli_validation") from exc
            reported = probe.stdout.replace("\\", "/").strip().rstrip("/").casefold()
            expected_root = root.as_posix().replace("\\", "/").rstrip("/").casefold()
            if probe.returncode or reported != expected_root:raise AdapterError("VAULT_ROOT_MISMATCH","指定 vault CLI 回报的根目录不匹配，写入前阻断",True,"pending_cli_validation")
    plan=[]
    for rel,new_hash in sorted(expected.items()):
        dest=resolve_inside(root,rel);old_hash=digest(dest) if dest.is_file() else None
        if old_hash and old_hash!=new_hash:raise AdapterError("WRITE_CONFLICT","目标文件存在不同内容，拒绝静默覆盖",details={"path":rel})
        plan.append((stage.joinpath(*PurePosixPath(rel).parts),dest,rel,new_hash,old_hash))
    runtime=Path(payload.get("runtime_dir") or tempfile.mkdtemp(prefix="esa-obsidian-transaction-",dir=str(stage.parent))).resolve();snapdir=runtime/"snapshots";snapdir.mkdir(parents=True,exist_ok=True);log=runtime/"publish_log.jsonl"
    snapshot={}
    for src,dest,rel,nh,old in plan:
        if old:
            snap=snapdir/(hashlib.sha256(rel.encode()).hexdigest()+".bak");shutil.copy2(dest,snap);snapshot[rel]=str(snap)
        else:snapshot[rel]=None
    log_event(log,{"event":"snapshot_created","count":len(plan),"paths":[x[2] for x in plan],"time":time.time()})
    written=[]
    try:
        for src,dest,rel,nh,old in plan:
            if old==nh:continue
            dest.parent.mkdir(parents=True,exist_ok=True)
            try:fd=os.open(dest,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            except FileExistsError as exc:raise AdapterError("WRITE_CONFLICT","目标在写入前被其他进程创建",details={"path":rel}) from exc
            written.append((rel,nh))
            with os.fdopen(fd,"wb") as f:
                data=src.read_bytes()
                try:
                    f.write(data);f.flush();os.fsync(f.fileno())
                except Exception:
                    # This file was created by our exclusive open. Capture the
                    # exact partial bytes so rollback can safely remove it.
                    f.flush()
                    written[-1]=(rel,hashlib.sha256(dest.read_bytes()).hexdigest())
                    raise
        if require_cli:
            for _,dest,rel,nh,_ in plan:
                if dest.suffix.lower() not in (".md",".base"):continue
                r=subprocess.run([binary,f"vault={vault}","read",f"path={rel}"],capture_output=True,text=False,timeout=20,check=False)
                if r.returncode or hashlib.sha256(r.stdout).hexdigest()!=nh:raise AdapterError("CLI_READBACK_MISMATCH","CLI 回读失败或字节哈希不一致",True,"rolled_back",{"path":rel,"exit_code":r.returncode})
        committed={"job_id":req["job_id"],"target_scope":str(scope),"source_sha256":req["source_sha256"],"clauses_sha256":actual_clauses,"files":[{"path":rel,"sha256":nh} for _,_,rel,nh,_ in plan],"cli_verified":bool(require_cli)}
        (runtime/"publish_manifest.json").write_text(json.dumps(committed,ensure_ascii=False,indent=2),encoding="utf-8")
        log_event(log,{"event":"commit","count":len(written),"cli_verified":bool(require_cli),"time":time.time()})
        return {"interface_id":"B-接口-05","interface_name":"publish_obsidian_bundle","job_id":req["job_id"],"schema_version":"1.0","result":{"ok":bool(require_cli),"status":"ok" if require_cli else "pending_cli_validation","output_files":[x[2] for x in plan],"details":{"published_count":len(written),"cli_verified":bool(require_cli),"manifest":str(runtime/"publish_manifest.json")}}}
    except Exception as exc:
        failures=[]
        for rel,nh in reversed(written):
            try:
                dest=resolve_inside(root,rel)
                if not dest.is_file() or digest(dest)!=nh:failures.append(rel);continue
                old=snapshot[rel]
                if old is None:dest.unlink()
                else:shutil.copy2(old,dest)
            except Exception:failures.append(rel)
        rb={"restored":not failures,"paths":[p[0] for p in written],"restore_failures":failures,"error_code":getattr(exc,"code","PARTIAL_WRITE")}
        (runtime/"rollback_manifest.json").write_text(json.dumps(rb,ensure_ascii=False,indent=2),encoding="utf-8")
        log_event(log,{"event":"rollback","count":len(written),"restore_failures":failures,"code":rb["error_code"],"time":time.time()})
        if isinstance(exc,AdapterError):raise AdapterError(exc.code if not failures else "PARTIAL_WRITE",str(exc),exc.retryable,"rolled_back",{"rollback_complete":not failures,"external_modifications":failures})
        raise AdapterError("PARTIAL_WRITE","发布失败，已按快照条件回滚",False,"rolled_back",{"rollback_complete":not failures,"external_modifications":failures}) from exc

def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("request",nargs="?"); args=ap.parse_args()
    if not args.request: return 0
    try:
        req=json.loads(Path(args.request).read_text(encoding="utf-8")); result=publish(req)
    except AdapterError as e:
        result={"interface_id":"B-接口-05","interface_name":"publish_obsidian_bundle","job_id":"","schema_version":"1.0","result":{"ok":False,"status":e.status,"output_files":[],"details":{},"error":{"code":e.code,"message":str(e),"retryable":e.retryable,"details":e.details}}}
    except Exception:
        result={"interface_id":"B-接口-05","interface_name":"publish_obsidian_bundle","job_id":"","schema_version":"1.0","result":{"ok":False,"status":"blocked","output_files":[],"details":{},"error":{"code":"INPUT_INVALID","message":"输入处理失败","retryable":False,"details":{}}}}
    print(json.dumps(result,ensure_ascii=False,indent=2)); return 0 if result["result"]["ok"] else 2
if __name__=="__main__":
    from json_io import configure_utf8_output
    configure_utf8_output()
    sys.exit(main())
