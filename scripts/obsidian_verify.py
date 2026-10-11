#!/usr/bin/env python3
"""Verify staging links locally or read back exact paths through Obsidian CLI."""
import argparse, hashlib, json, os, re, subprocess, sys
from pathlib import Path
from obsidian_render import AdapterError, safe_relative
from json_io import loads as strict_json_loads

def verify(req):
    if not isinstance(req,dict):raise AdapterError("INPUT_INVALID","请求必须是对象")
    public=("interface_id","interface_name","job_id","schema_version","vault_root","target_scope","source_sha256","dry_run","payload")
    if tuple(list(req)[:len(public)])!=public or (req.get("interface_id"),req.get("interface_name"),req.get("schema_version"))!=("B-接口-04","verify_obsidian_publish","1.0"):
        raise AdapterError("INPUT_INVALID","请求不符合 B-接口-04 公共字段顺序或标识")
    if not isinstance(req.get("dry_run"),bool) or not isinstance(req.get("payload"),dict) or any(not isinstance(req.get(k),str) or not req[k] for k in ("job_id","vault_root","target_scope")):
        raise AdapterError("INPUT_INVALID","公共字段类型无效")
    p=req["payload"]; root=Path(req["vault_root"]).resolve(); env=os.environ.get("OBSIDIAN_VAULT_ROOT")
    if not re.fullmatch(r"[0-9a-fA-F]{64}",str(req["source_sha256"])):raise AdapterError("INPUT_INVALID","source_sha256 格式无效")
    if not req.get("dry_run",True) and (not env or Path(env).resolve()!=root or not root.is_dir()):
        raise AdapterError("VAULT_ROOT_MISMATCH","vault_root 与 OBSIDIAN_VAULT_ROOT 不一致")
    scope=safe_relative(req["target_scope"].rstrip("/")); stage=Path(p["staging_dir"]).resolve()
    if not stage.is_dir(): raise AdapterError("INPUT_INVALID","staging_dir 不存在或不是目录")
    stage_files={x.relative_to(stage).as_posix():x for x in stage.rglob("*") if x.is_file() and x.name!=".esa_staging_manifest.json"}
    if any(x.is_symlink() for x in stage.rglob("*")):raise AdapterError("PATH_OUTSIDE_VAULT","staging 目录包含符号链接")
    try:manifest=strict_json_loads((stage/".esa_staging_manifest.json").read_text(encoding="utf-8"))
    except (OSError,ValueError) as e:raise AdapterError("SOURCE_NOT_VERIFIED","缺少有效 staging manifest") from e
    listed={x.get("path"):x.get("sha256") for x in manifest.get("files",[]) if isinstance(x,dict)}
    actual={k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in stage_files.items() if Path(k).name!=".esa_staging_manifest.json"}
    if manifest.get("job_id")!=req["job_id"] or manifest.get("target_scope")!=str(scope) or manifest.get("source_sha256")!=req["source_sha256"] or listed!=actual:
        raise AdapterError("SOURCE_NOT_VERIFIED","staging 文件哈希或绑定元数据不匹配")
    issues=[]
    for rel, path in stage_files.items():
        safe_relative(rel)
        if tuple(Path(rel).parts[:len(scope.parts)])!=scope.parts:
            raise AdapterError("PATH_OUTSIDE_VAULT","staging 文件超出 target_scope")
        try: content=path.read_text(encoding="utf-8")
        except UnicodeDecodeError: continue
        for target in re.findall(r"!?\[\[([^\]]+)\]\]",content):
            target=target.split("|",1)[0].split("#",1)[0]
            if not target: continue
            try: safe_relative(target)
            except AdapterError:
                issues.append(Path(target).name); continue
            # Resolve only inside this staged scope, allowing basename links.
            candidate=Path(rel).parent/target
            candidates={candidate.as_posix(),(candidate.with_suffix(".md")).as_posix(),(candidate.with_suffix(".pdf")).as_posix()}
            explicit_dir="/" in target
            if not any(c in stage_files for c in candidates) and (explicit_dir or Path(target).stem not in {Path(k).stem for k in stage_files}):
                issues.append(Path(target).name)
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)",content):
            target=target.strip().strip("<>").split("#",1)[0]
            if not target or re.match(r"(?i)^(?:https?|mailto):",target):continue
            if re.match(r"^[A-Za-z]:[\\/]",target) or target.startswith("/"):
                issues.append(Path(target).name);continue
            candidate=(Path(rel).parent/target).as_posix()
            if candidate not in stage_files and Path(candidate).with_suffix(".md").as_posix() not in stage_files:
                issues.append(Path(target).name)
    if issues: raise AdapterError("LINK_TARGET_MISSING","staging 中存在无法解析的内部链接",details={"targets":sorted(set(issues))})
    if req["dry_run"]:
        return {"interface_id":"B-接口-04","interface_name":"verify_obsidian_publish","job_id":req["job_id"],"schema_version":"1.0","result":{"ok":False,"status":"pending_cli_validation","output_files":[],"details":{"local_link_check":True,"cli_checked":False,"readback_count":0}}}
    binary=p.get("obsidian_executable","obsidian"); vault=p.get("vault_name")
    if not vault: raise AdapterError("CLI_UNAVAILABLE","必须提供明确 vault_name",True,"pending_cli_validation")
    def run(args,text=True):
        try:
            kw={"capture_output":True,"timeout":20,"check":False}
            if text:kw.update(text=True,encoding="utf-8",errors="replace")
            return subprocess.run(args,**kw)
        except (OSError,subprocess.TimeoutExpired) as e: raise AdapterError("CLI_UNAVAILABLE","Obsidian CLI 不可用",True,"pending_cli_validation") from e
    h=run([binary,"help"])
    if h.returncode or "read" not in h.stdout+h.stderr or "vault" not in h.stdout+h.stderr or "info" not in h.stdout+h.stderr:
        raise AdapterError("CLI_UNAVAILABLE","Obsidian CLI help 不支持已确认语法",True,"pending_cli_validation")
    info=run([binary,f"vault={vault}","info"])
    reported=info.stdout.replace("\\","/").strip().rstrip("/").casefold()
    expected=root.as_posix().replace("\\","/").rstrip("/").casefold()
    if info.returncode or reported!=expected:
        raise AdapterError("VAULT_ROOT_MISMATCH","CLI 指定 vault 根目录不匹配",True,"pending_cli_validation")
    checked=0
    for rel,path in stage_files.items():
        actual=root.joinpath(*Path(rel).parts)
        # Verify only files that have already been transactionally published.
        if not actual.is_file(): raise AdapterError("CLI_UNAVAILABLE","目标文件尚未写入，不能回读",True,"pending_cli_validation")
        expected_hash=hashlib.sha256(path.read_bytes()).hexdigest()
        if hashlib.sha256(actual.read_bytes()).hexdigest()!=expected_hash:
            raise AdapterError("CLI_READBACK_MISMATCH","Vault 本地文件字节哈希与 staging 不一致",True,"rolled_back",{"path":rel})
        if path.suffix.lower() not in (".md",".base"):continue
        rr=run([binary,f"vault={vault}","read",f"path={rel}"],text=False)
        if rr.returncode or hashlib.sha256(rr.stdout).hexdigest()!=expected_hash:
            raise AdapterError("CLI_READBACK_MISMATCH","CLI 回读哈希不一致",True,"rolled_back",{"path":rel,"exit_code":rr.returncode})
        checked+=1
    return {"interface_id":"B-接口-04","interface_name":"verify_obsidian_publish","job_id":req["job_id"],"schema_version":"1.0","result":{"ok":True,"status":"ok","output_files":[],"details":{"local_link_check":True,"cli_checked":True,"readback_count":checked,"vault_name":vault}}}

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("request",nargs="?");a=ap.parse_args()
    if not a.request:return 0
    try:r=verify(strict_json_loads(Path(a.request).read_text(encoding="utf-8-sig")))
    except AdapterError as e:r={"interface_id":"B-接口-04","interface_name":"verify_obsidian_publish","job_id":"","schema_version":"1.0","result":{"ok":False,"status":e.status,"output_files":[],"details":{},"error":{"code":e.code,"message":str(e),"retryable":e.retryable,"details":e.details}}}
    except Exception:r={"interface_id":"B-接口-04","interface_name":"verify_obsidian_publish","job_id":"","schema_version":"1.0","result":{"ok":False,"status":"blocked","output_files":[],"details":{},"error":{"code":"INPUT_INVALID","message":"输入处理失败","retryable":False,"details":{}}}}
    print(json.dumps(r,ensure_ascii=False,indent=2));return 0 if r["result"]["ok"] else 2
if __name__=="__main__":sys.exit(main())
