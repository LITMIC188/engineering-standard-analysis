"""Prepare post-freeze source analysis/translation work packets; performs no translation."""
import argparse, json, hashlib
from pathlib import Path
def _pairs(pairs):
    d={}
    for k,v in pairs:
        if k in d: raise ValueError(json.dumps({'error':'duplicate_json_key','key':k}))
        d[k]=v
    return d

def dispatch(clauses, verified_source):
    if verified_source.get('source_sha256')!=clauses.get('source',{}).get('sha256'): raise ValueError('source hash mismatch')
    canonical=lambda x:json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    ch=hashlib.sha256(canonical(clauses)).hexdigest()
    article=Path(verified_source.get('article_path',''))
    registry=Path(verified_source.get('heading_registry_path',''))
    registry_ok=False
    if registry.is_file():
        reg=json.loads(registry.read_text(encoding='utf-8-sig'),object_pairs_hook=_pairs)
        registry_ok=hashlib.sha256(canonical(reg)).hexdigest()==verified_source.get('heading_registry_sha256')
    article_ok=article.is_file() and hashlib.sha256(article.read_bytes()).hexdigest()==verified_source.get('article_sha256')
    frozen=verified_source.get('review_status')=='source_checked' and verified_source.get('source_complete') is True and verified_source.get('clauses_sha256')==ch and registry_ok and article_ok
    lang=next((b.get('source_lang','und') for b in clauses.get('blocks',[])),'und')
    if lang.lower().startswith('zh'): return {'status':'source_only' if frozen else 'draft_blocked','source_analysis':frozen,'translation_required':False,'parallel':False,'reason':'Chinese source skips translation','blocks':[b['block_id'] for b in clauses.get('blocks',[])]}
    return {'status':'ready' if frozen else 'draft_blocked','source_analysis':frozen,'translation_required':True,'parallel':frozen,'execution_backend':None,'translation_file_protocol':'translation-quality-codex adapter files only; no backend invoked','blocks':[b['block_id'] for b in clauses.get('blocks',[])]}
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('clauses'); p.add_argument('verified_source'); p.add_argument('--out',required=True); a=p.parse_args(argv)
    read=lambda x:json.loads(Path(x).read_text(encoding='utf-8-sig'),object_pairs_hook=_pairs); result=dispatch(read(a.clauses),read(a.verified_source)); out=Path(a.out)
    if out.exists(): raise SystemExit(json.dumps({'error':'output_exists','path':str(out)}))
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); return 0 if result['status'] not in ('draft_blocked',) else 2
if __name__=='__main__': raise SystemExit(main())
