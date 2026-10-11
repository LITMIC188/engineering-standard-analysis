"""Attach table/figure/footnote anchors and cross-page provenance without guessing cell structure."""
import argparse, json
from pathlib import Path
def _pairs(pairs):
    d={}
    for k,v in pairs:
        if k in d: raise ValueError(json.dumps({'error':'duplicate_json_key','key':k}))
        d[k]=v
    return d
def detect_layout(blocks):
    result=[]
    for b in blocks:
        x=dict(b); kind=x.get('kind','paragraph'); text=x.get('original_text',x.get('text',''))
        detected='table' if text.lower().lstrip().startswith('table ') else ('figure' if text.lower().lstrip().startswith(('figure ','fig. ')) else kind)
        if detected in ('table','figure','footnote'):
            x['layout_anchor']=x.get('layout_anchor') or detected.upper()
            attachment=x.get('attachment') or x.get('image')
            missing_attachment=bool(attachment and not __import__('pathlib').Path(attachment).is_file())
            x['layout_status']='unknown' if detected in ('table','figure') and (not x.get('structure') or not attachment or missing_attachment) else 'identified'
        result.append(x)
    # Cross-page regions may be explicitly grouped by region_id; do not infer continuity.
    groups={}
    for i,x in enumerate(result):
        if x.get('region_id'): groups.setdefault(x['region_id'],[]).append(i)
    for rid,indexes in groups.items():
        ordered=sorted(indexes,key=lambda i:result[i].get('read_order',i))
        pages=[result[i].get('source',{}).get('pdf_page') for i in ordered]
        for pos,i in enumerate(ordered):
            result[i]['region_id']=rid; result[i]['region_part']=pos+1; result[i]['region_pages']=pages
    return result

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('input'); p.add_argument('--out',required=True); a=p.parse_args(argv)
    data=json.loads(Path(a.input).read_text(encoding='utf-8-sig'),object_pairs_hook=_pairs); rows=data if isinstance(data,list) else data.get('blocks',[])
    out=Path(a.out)
    if out.exists(): raise SystemExit(json.dumps({'error':'output_exists','path':str(out)}))
    out.write_text(json.dumps(detect_layout(rows),ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); return 0
if __name__=='__main__': raise SystemExit(main())
