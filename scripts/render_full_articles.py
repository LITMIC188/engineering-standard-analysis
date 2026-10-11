"""Render full source/Chinese/bilingual reading articles in stable source block order."""
import argparse, hashlib, json
from pathlib import Path
from validate_translation import validate_bundle
def _pairs(pairs):
    d={}
    for k,v in pairs:
        if k in d: raise ValueError(json.dumps({'error':'duplicate_json_key','key':k}))
        d[k]=v
    return d

def render(clauses, translations=None, verified_source=None):
    blocks=clauses.get('blocks',[]); ids=[b.get('block_id') for b in blocks]
    if not all(ids) or len(ids)!=len(set(ids)): raise ValueError('missing/duplicate source block IDs')
    source_hash=clauses.get('source',{}).get('sha256')
    if verified_source and verified_source.get('source_sha256')!=source_hash: raise ValueError('verified source hash mismatch')
    from verify_source import canonical_source_article
    source=canonical_source_article(clauses).decode('utf-8'); source_hash_actual=hashlib.sha256(source.encode()).hexdigest()
    mapping={}
    if translations:
        segs=translations.get('segments',[]); sids=[s.get('block_id') for s in segs]
        if len(sids)!=len(set(sids)) or set(sids)!=set(ids): raise ValueError('translation IDs missing/extra/duplicate')
        for s in segs:
            b=next(x for x in blocks if x['block_id']==s['block_id'])
            if s.get('original_text')!=b.get('original_text') or s.get('source',b.get('source'))!=b.get('source'): raise ValueError('translation source provenance mismatch')
            mapping[s['block_id']]=s.get('translated_text','')
            if not mapping[s['block_id']]: raise ValueError('translation text missing')
    clause_hash=hashlib.sha256(json.dumps(clauses,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    registry_ok=False
    if verified_source and verified_source.get('heading_registry_path') and Path(verified_source['heading_registry_path']).is_file():
        reg=json.loads(Path(verified_source['heading_registry_path']).read_text(encoding='utf-8-sig'),object_pairs_hook=_pairs)
        registry_ok=hashlib.sha256(json.dumps(reg,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()==verified_source.get('heading_registry_sha256')
    source_checked=bool(verified_source and verified_source.get('review_status')=='source_checked' and verified_source.get('source_complete') is True and verified_source.get('source_sha256')==source_hash and verified_source.get('article_sha256')==source_hash_actual and verified_source.get('clauses_sha256')==clause_hash and registry_ok)
    if source_checked:
        source_path=verified_source.get('article_path')
        if not source_path or not Path(source_path).is_file() or hashlib.sha256(Path(source_path).read_bytes()).hexdigest()!=source_hash_actual:
            raise ValueError('frozen source article missing or hash changed')
    lang=(blocks[0].get('source_lang') or '').lower() if blocks else ''
    if lang.startswith('zh'):
        chinese=source
        bilingual=source
        translation_approved=False
        validation={}
    else:
        approval={}; validation={}
        for s in (translations or {}).get('segments',[]):
            rr=s.get('review_record')
            result=validate_bundle({'schema_version':'2.0','segments':[s]})
            validation[s['block_id']]={'errors':result['errors'],'warnings':result['warnings'],'token_differences':result.get('token_differences',[])}
            approval[s['block_id']]=bool(s.get('human_reviewed') is True and isinstance(rr,dict) and all(isinstance(rr.get(k),str) and rr[k].strip() for k in ('reviewer','reviewed_at','approval_evidence')) and not result['errors'])
        translation_approved=bool(translations) and len(approval)==len(blocks) and all(approval.values())
        zh_rows=[]; bi_rows=[]
        for b in blocks:
            bid=b['block_id']; approved=approval.get(bid,False); marker='' if approved else '> DRAFT — translation pending human review\n\n'
            if bid in mapping:
                zh_rows.append(f"{marker}<!-- block_id:{bid} -->\n{mapping[bid]}")
                bi_rows.append(f"<!-- block_id:{bid} -->\n{b.get('original_text','')}\n\n{marker}{mapping[bid]}")
            else:
                zh_rows.append(f"> DRAFT — translation missing\n\n<!-- block_id:{bid} -->\n[translation missing]")
        chinese='\n\n'.join(zh_rows)+'\n' if translations else None
        bilingual='\n\n'.join(bi_rows)+'\n' if translations else None
    if not source_checked:
        if chinese is not None: chinese='> DRAFT — source not checked\n\n'+chinese
        if bilingual is not None: bilingual='> DRAFT — source not checked\n\n'+bilingual
    return {'source':source,'source_article_sha256':source_hash_actual,'chinese':chinese,'bilingual':bilingual,'source_status':'source_checked' if source_checked else 'draft','translation_status':'translation_approved' if translation_approved else 'draft','translation_validation':validation if translations and not lang.startswith('zh') else {},'status':'source_checked' if source_checked else 'DRAFT — source not checked','blocks':len(blocks)}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('clauses'); p.add_argument('--translations'); p.add_argument('--verified-source'); p.add_argument('--out-dir',required=True); a=p.parse_args(argv)
    read=lambda x:json.loads(Path(x).read_text(encoding='utf-8-sig'),object_pairs_hook=_pairs)
    r=render(read(a.clauses),read(a.translations) if a.translations else None,read(a.verified_source) if a.verified_source else None); out=Path(a.out_dir)
    names=['03_Original_DRAFT.md' if r['source_status']!='source_checked' else None,'04_Translation_Complete.md','05_Bilingual_Complete.md','article_manifest.json']
    if out.exists(): raise SystemExit(json.dumps({'error':'output_exists','directory':str(out)},ensure_ascii=False))
    out.mkdir(parents=True,exist_ok=True)
    if names[0]: (out/names[0]).write_bytes(('> DRAFT — source not checked\n\n'+r['source']).encode('utf-8'))
    zh=(r['chinese'] or '> DRAFT — translation unavailable\n'); bi=(r['bilingual'] or '> DRAFT — translation unavailable\n')
    if r['source_status']!='source_checked':
        if r['chinese'] is None: zh='> DRAFT — source not checked\n\n'+zh
        if r['bilingual'] is None: bi='> DRAFT — source not checked\n\n'+bi
    (out/names[1]).write_bytes(zh.encode('utf-8')); (out/names[2]).write_bytes(bi.encode('utf-8'))
    manifest={k:v for k,v in r.items() if k not in ('source','chinese','bilingual')}
    manifest.update({'source_article_sha256':r['source_article_sha256'],'chinese_sha256':hashlib.sha256(zh.encode('utf-8')).hexdigest(),'bilingual_sha256':hashlib.sha256(bi.encode('utf-8')).hexdigest(),'source_status':r['source_status'],'translation_status':r['translation_status'],'blocks':r['blocks']})
    (out/names[3]).write_bytes((json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode('utf-8')); return 0
if __name__=='__main__': raise SystemExit(main())
