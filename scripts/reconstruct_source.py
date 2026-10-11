"""Rebuild readable source Markdown while preserving raw OCR and source geometry."""
import argparse, hashlib, json, re
from pathlib import Path
from layout_tables import detect_layout
from ocr_space_restore import restore
from heading_registry import build_registry
from verify_source import canonical_source_article

def reconstruct(extraction, clauses=None):
    src=extraction; raw_blocks=src.get('blocks') or src.get('items')
    if raw_blocks is None:
        # A page-only extraction is a valid minimal input. Preserve only its
        # explicit provenance; the sequence number is an internal stable ID,
        # never a claim that the source is a PDF or that page 1 exists.
        raw_blocks=[]
        for i,p in enumerate(src.get('pages',[]),1):
            row=dict(p)
            row.setdefault('original_text',p.get('text',''))
            row.setdefault('raw_text',p.get('text',''))
            row.setdefault('read_order',i)
            raw_blocks.append(row)
    blocks=restore(raw_blocks)
    for i,b in enumerate(blocks,1):
        b.setdefault('block_id',f'B{i:04d}')
        b.setdefault('original_text',b.get('text',b.get('raw_text','')))
        s=b.setdefault('source',{})
        s.setdefault('file',src.get('file')); s.setdefault('sha256',src.get('sha256'))
        if s.get('locator') is None and b.get('locator') is not None: s['locator']=b.get('locator')
        if s.get('pdf_page') is None and b.get('page_kind')=='pdf': s['pdf_page']=b.get('page')
        if s.get('page_kind') is None: s['page_kind']=b.get('page_kind','unknown')
        if s.get('page_kind')=='unknown' or not s.get('locator'):
            b.setdefault('provenance_status','unknown')
        if b.get('read_order') is None: b['read_order']=b.get('order',1)
    blocks=detect_layout(blocks)
    byid={b.get('block_id'):b for b in blocks if b.get('block_id')}
    byloc={b.get('source',{}).get('locator'):b for b in blocks if b.get('source',{}).get('locator')}
    if clauses:
        merged=[]
        for clause in clauses.get('blocks',[]):
            locator=(clause.get('source') or {}).get('locator')
            row=dict(byid.get(clause.get('block_id')) or byloc.get(locator) or {}); row.update(clause)
            row['raw_text']=row.get('raw_text',row.get('original_text',''))
            row.setdefault('restoration',restore([{'text':row['raw_text']}])[0]['restoration'])
            merged.append(row)
        blocks=merged
    def position(b):
        bbox=b.get('bbox') or []; origin=(b.get('coord_origin') or (bbox.get('coord_origin') if isinstance(bbox,dict) else None) or 'UNKNOWN').upper()
        try:
            if not bbox: raise IndexError('no geometry')
            if isinstance(bbox,dict):
                x=float(bbox.get('l',bbox.get('x0'))); y0=float(bbox.get('t',bbox.get('y0')))
                if origin=='BOTTOMLEFT':
                    height=b.get('page_height')
                    if height is None: raise ValueError('missing page height for bottom-left bbox')
                    y=float(height)-float(bbox.get('b',bbox.get('y1')))
                elif origin=='TOPLEFT': y=y0
                else: raise ValueError('unknown bbox origin')
            else:
                if origin!='TOPLEFT': raise ValueError('cannot transform bbox origin')
                y,x=float(bbox[1]),float(bbox[0])
        except (TypeError,ValueError,IndexError):
            y=x=float('inf')
            if bbox: b['geometry_status']='unknown'
        return (b.get('source',{}).get('pdf_page') or 0,b.get('read_order',10**9),y,x)
    blocks.sort(key=position)
    registry=build_registry(blocks,src.get('sha256',''),src.get('pages'))
    for b in blocks:
        if b.get('kind') in ('table','figure'):
            attachment=b.get('attachment') or b.get('image')
            if not attachment or not Path(attachment).is_file(): b['layout_status']='unknown'; b['attachment_missing']=True
    article=canonical_source_article({'blocks':blocks}).decode('utf-8')
    blockers=[b.get('block_id') for b in blocks if b.get('attachment_missing') or b.get('geometry_status')=='unknown' or b.get('provenance_status')=='unknown']
    return {'schema_version':'1.0','source':{'file':src.get('file'),'sha256':src.get('sha256')},'blocks':blocks,'heading_registry':registry,'article':article,'article_sha256':hashlib.sha256(article.encode()).hexdigest(),'complete':bool(src.get('complete',False)) and not blockers,'blockers':blockers,'warnings':list(src.get('warnings',[]))}

def _unique_pairs(pairs):
    d={}
    for k,v in pairs:
        if k in d: raise ValueError(json.dumps({'error':'duplicate_json_key','key':k}))
        d[k]=v
    return d

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('extraction'); p.add_argument('--clauses'); p.add_argument('--out-dir',required=True); a=p.parse_args(argv)
    read=lambda x:json.loads(Path(x).read_text(encoding='utf-8-sig'),object_pairs_hook=_unique_pairs)
    r=reconstruct(read(a.extraction),read(a.clauses) if a.clauses else None); out=Path(a.out_dir)
    if out.exists(): raise SystemExit(json.dumps({'error':'output_exists','directory':str(out)}))
    out.mkdir(parents=True,exist_ok=True)
    for n,d in [('reconstruction.json',r),('clause_heading_registry.json',r['heading_registry']),('ocr_diffs.json',[b['restoration'] for b in r['blocks']])]: (out/n).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'02_Original_Reconstructed.md').write_bytes(r['article'].encode('utf-8')); return 0
if __name__=='__main__': raise SystemExit(main())
