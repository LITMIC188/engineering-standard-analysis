"""Local parser status probes and structural imports; this never executes OCR tools."""
import argparse, json, shutil
from pathlib import Path

def probe():
    return {name:{'available':bool(shutil.which(name)),'execution_performed':False} for name in ('docling','mineru')}

def _unique_pairs(pairs):
    d={}
    for k,v in pairs:
        if k in d: raise ValueError(json.dumps({'error':'duplicate_json_key','key':k}))
        d[k]=v
    return d

def import_structure(path, source_file=None, source_sha256=None):
    data=json.loads(Path(path).read_text(encoding='utf-8-sig'),object_pairs_hook=_unique_pairs)
    if isinstance(data,list): rows=data; backend='generic exported structure'
    elif 'pdf_info' in data or 'content_list' in data: rows=data.get('content_list',data.get('pdf_info',[])); backend='mineru-export'
    elif any(k in data for k in ('texts','tables','pictures')):
        rows=[]
        for key,kind in (('texts','text'),('tables','table'),('pictures','figure')):
            for item in data.get(key,[]): rows.append(dict(item,_import_kind=kind))
        backend='docling-export'
    else: rows=data.get('blocks',data.get('items',[])); backend='generic exported structure'
    out=[]
    for i,r in enumerate(rows,1):
        kind=r.get('_import_kind',r.get('kind',r.get('label',r.get('type','paragraph'))))
        if kind in ('section_header','title'): kind='heading'
        elif kind in ('picture','image'): kind='figure'
        text=r.get('text',r.get('content',r.get('table_body',r.get('latex',''))))
        provs=r.get('prov',r.get('provenance',[])); provs=provs if isinstance(provs,list) else [provs]
        if not provs: provs=[{}]
        for part,prov in enumerate(provs,1):
            if not isinstance(prov,dict): prov={}
            page_no=prov.get('pdf_page')
            if page_no is None and prov.get('page_no') is not None: page_no=prov['page_no']
            if page_no is None and r.get('page_idx') is not None: page_no=r['page_idx']+1
            locator=prov.get('locator') or (f'PDF page {page_no}' if page_no is not None else None)
            if not locator: raise ValueError(f'page provenance missing for imported layout block {i}; refusing to assume page 1')
            out.append({'block_id':r.get('block_id') or f'B{i:04d}'+(f'-{part}' if len(provs)>1 else ''),'kind':kind,'original_text':text,'raw_text':text,'bbox':r.get('bbox') or prov.get('bbox'),'coord_origin':r.get('coord_origin',prov.get('coord_origin')),'page_height':r.get('page_height',prov.get('page_height')),'read_order':r.get('read_order',r.get('order',i)),'source':{'file':prov.get('file',source_file),'sha256':prov.get('sha256',source_sha256),'pdf_page':page_no,'page_kind':prov.get('page_kind','pdf'),'locator':locator},'structure':r.get('structure',r.get('table_cells')),'attachment':r.get('image_path',r.get('path')),'layout_status':'unknown' if kind in ('table','figure') and not r.get('structure') else 'identified'})
    return {'blocks':out,'backend_execution':False,'imported_backend':backend,'source_sha256':source_sha256,'blockers':[b['block_id'] for b in out if b.get('layout_status')=='unknown']}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); s=p.add_subparsers(dest='cmd',required=True); s.add_parser('probe'); q=s.add_parser('import'); q.add_argument('input'); q.add_argument('--source-file'); q.add_argument('--source-sha256'); q.add_argument('--out',required=True); a=p.parse_args(argv)
    x=probe() if a.cmd=='probe' else import_structure(a.input,a.source_file,a.source_sha256)
    if a.cmd=='probe': print(json.dumps(x,indent=2))
    else:
        out=Path(a.out)
        if out.exists(): raise SystemExit(json.dumps({'error':'output_exists','path':str(out)}))
        out.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0
if __name__=='__main__': raise SystemExit(main())
