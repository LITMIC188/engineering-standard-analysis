"""Read-only local capability report. Does not install or execute parser backends."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

SKILLS=('obsidian-markdown','obsidian-bases','obsidian-cli','translation-quality-codex','tutor-setup')

def doctor(roots=None,check_cli=False):
    repo=Path(__file__).resolve().parents[1]
    roots=[Path(p).expanduser() for p in roots] if roots else [Path.home()/'.codex/skills',Path.home()/'.agents/skills',repo.parent/'.agents/skills']
    skills={}
    for name in SKILLS:
        candidates=[r/name/'SKILL.md' for r in roots]
        found=[p for p in candidates if p.is_file()]
        skills[name]={'available':bool(found),'paths':[str(p.resolve()) for p in found],
            'sha256':[hashlib.sha256(p.read_bytes()).hexdigest() for p in found],
            'execution_performed':False,'duplicate_installation':len(found)>1}
    cli=shutil.which('obsidian')
    status={'available':bool(cli),'path':cli,'help_checked':False,'status':'pending_cli_validation'}
    if cli and check_cli:
        try:
            result=subprocess.run([cli,'help'],capture_output=True,text=True,timeout=10,encoding='utf-8',errors='replace')
            status.update(help_checked=True,exit_code=result.returncode,status='available' if result.returncode==0 else 'pending_cli_validation')
        except (OSError,subprocess.TimeoutExpired) as error:
            status['error']=type(error).__name__
    return {'schema_version':'1.0','esa_local':str(repo),'python':sys.executable,
        'dependencies':{m:bool(importlib.util.find_spec(m)) for m in ('yaml','jsonschema','pypdf','reportlab')},
        'skills':skills,'parsers':{m:shutil.which(m) for m in ('docling','mineru','pdftotext')},
        'obsidian_cli':status,'vault_root':os.environ.get('OBSIDIAN_VAULT_ROOT'),
        'vault_write_performed':False,'network_performed':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--skill-root',action='append');p.add_argument('--check-cli',action='store_true');p.add_argument('--out')
    a=p.parse_args();result=doctor(a.skill_root,a.check_cli);content=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if a.out:
        target=Path(a.out);target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('x',encoding='utf-8') as f:f.write(content)
    print(content);return 0

if __name__=='__main__':raise SystemExit(main())
