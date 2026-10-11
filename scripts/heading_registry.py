"""Stable source heading registry; heading labels are always explicit source text."""
import argparse, json
from pathlib import Path
def _pairs(pairs):
    d={}
    for k,v in pairs:
        if k in d: raise ValueError(json.dumps({'error':'duplicate_json_key','key':k}))
        d[k]=v
    return d

def build_registry(records, source_sha256, pages=None):
    headings=[]
    for i,r in enumerate(records,1):
        title=r.get('title') or r.get('text')
        if not isinstance(title,str) or not title.strip(): continue
        if r.get('kind') is None and not r.get('is_heading') and r.get('level') is None: continue
        if r.get('kind') not in (None,'heading','title') and not r.get('is_heading'): continue
        if pages is not None:
            s=r.get('source',{}); page=next((p for p in pages if p.get('locator')==s.get('locator')),None)
            if not page or s.get('sha256')!=source_sha256 or title.strip() not in page.get('text',''):
                raise ValueError('heading is not traceable to source page: '+title.strip())
        if not isinstance(r.get('clause_id'),str) or not r['clause_id'].strip(): raise ValueError('heading requires a clause_id: '+title.strip())
        headings.append({'heading_id':r.get('heading_id') or f'H{i:04d}','title':title.strip(),'clause_id':r['clause_id'],'level':int(r.get('level',1)),'order':int(r.get('order',i)), 'source':dict(r.get('source',{})), **({'block_id':r['block_id']} if r.get('block_id') else {})})
    ids=[h['heading_id'] for h in headings]
    if len(ids)!=len(set(ids)): raise ValueError('duplicate heading_id')
    headings.sort(key=lambda h:h['order'])
    return {'schema_version':'1.0','source_sha256':source_sha256,'headings':headings}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('input'); p.add_argument('--source-sha256',required=True); p.add_argument('--out',required=True); a=p.parse_args(argv)
    data=json.loads(Path(a.input).read_text(encoding='utf-8-sig'),object_pairs_hook=_pairs); rows=data if isinstance(data,list) else data.get('blocks',[]); out=Path(a.out)
    if out.exists(): raise SystemExit(json.dumps({'error':'output_exists','path':str(out)}))
    out.write_text(json.dumps(build_registry(rows,a.source_sha256),ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); return 0
if __name__=='__main__': raise SystemExit(main())
