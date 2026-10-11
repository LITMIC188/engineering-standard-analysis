"""Coverage and provenance gate. A verified snapshot requires genuine supplied review evidence."""
import argparse, hashlib, json
import re
from pathlib import Path

def _hash_bytes(b): return hashlib.sha256(b).hexdigest()
INVENTORY_KINDS=('pages','chapters','normative_annexes','tables','figures','references')
def canonical_source_article(clauses):
    rows=[]
    for b in clauses.get('blocks',[]):
        s=b.get('source',{}); text=f"<!-- block_id:{b['block_id']} -->\n<!-- source:{s.get('locator','unknown')} page:{s.get('pdf_page')} -->\n{b.get('original_text','')}"
        if b.get('kind') in ('table','figure'):
            attachment=b.get('attachment') or b.get('image')
            text+=f"\n![{b['kind']}]({attachment})" if attachment else f"\n> UNKNOWN layout: {b['kind']} source region requires image attachment/review."
        rows.append(text)
    return ('\n\n'.join(rows)+'\n').encode('utf-8')

def verify_source(clauses, extraction, checklist, review_record=None, article_path=None, output_path=None, expected_inventory=None, heading_registry=None, heading_registry_path=None):
    source=clauses.get('source',{}); expected=source.get('sha256'); blocks=clauses.get('blocks',[])
    if not expected or extraction.get('sha256')!=expected: raise ValueError('source hash mismatch')
    source_file=source.get('file') or extraction.get('file')
    if not extraction.get('file') or Path(extraction['file']).resolve()!=Path(source_file).resolve(): raise ValueError('extraction file does not match clauses source file')
    source_exists=bool(source_file and Path(source_file).is_file())
    source_bytes_match=source_exists and _hash_bytes(Path(source_file).read_bytes())==expected
    if source_exists:
        from local_parser import extract_document
        reparsed=extract_document(source_file)
        if reparsed.get('sha256')!=expected: raise ValueError('re-extracted source SHA256 mismatch')
        supplied={(p.get('page_kind'),p.get('locator')):p for p in extraction.get('pages',[])}
        actual={(p.get('page_kind'),p.get('locator')):p for p in reparsed.get('pages',[])}
        if set(supplied)!=set(actual): raise ValueError('extraction page inventory differs from local re-extraction')
        text_diff=any(supplied[k].get('text')!=actual[k].get('text') for k in actual)
        if reparsed.get('format')!='pdf' and text_diff: raise ValueError('extraction text differs from local re-extraction')
        if reparsed.get('format')=='pdf' and text_diff:
            # External OCR is a declared artifact import, never an assumed local backend run.
            artifact=extraction.get('raw_ocr_artifact'); artifact_path=Path(artifact) if artifact else None
            raw_digest=_hash_bytes(artifact_path.read_bytes()) if artifact_path and artifact_path.is_file() else None
            if extraction.get('kind')!='raw_ocr' or not raw_digest or raw_digest!=extraction.get('raw_ocr_sha256'):
                raise ValueError('scanned PDF OCR requires an immutable raw_ocr artifact with matching SHA256')
            actual_pages=[p.get('page') for p in reparsed.get('pages',[]) if p.get('page_kind')=='pdf']
            if extraction.get('physical_page_count')!=len(actual_pages): raise ValueError('OCR physical_page_count does not match local PDF re-extraction')
            reviews={r.get('page'):r for r in extraction.get('page_image_reviews',[]) if isinstance(r,dict)}
            for page_no in actual_pages:
                record=reviews.get(page_no); img=Path(record['image_file']) if record and record.get('image_file') else None
                image_hash=_hash_bytes(img.read_bytes()) if img and img.is_file() else None
                rr=record.get('review_record',{}) if record else {}
                if not record or image_hash!=record.get('image_sha256') or not all(isinstance(rr.get(k),str) and rr[k].strip() for k in ('reviewer','reviewed_at','approval_evidence')):
                    raise ValueError(f'OCR page {page_no} lacks verified local page image and human review record')
    ids=[b.get('block_id') for b in blocks]
    if not all(ids) or len(ids)!=len(set(ids)): raise ValueError('missing/duplicate block_id')
    page_rows=extraction.get('pages',[]); known={p.get('locator'):p for p in page_rows}; known_pages={p.get('page') for p in page_rows}
    missing=[]; issues=[]
    for b in blocks:
        s=b.get('source',{}); loc=s.get('locator')
        if s.get('sha256')!=expected or (known and loc not in known): issues.append({'id':b['block_id'],'reason':'source provenance mismatch'})
        page0=known.get(loc)
        if page0 and (Path(s.get('file','')).resolve()!=Path(source_file).resolve() or s.get('pdf_page')!=(page0.get('page') if page0.get('page_kind')=='pdf' else None) or s.get('page_kind')!=page0.get('page_kind')):
            issues.append({'id':b['block_id'],'reason':'block file/page/page_kind mismatch'})
        spans=b.get('spans') or [{'source':s,'quote':b.get('original_text','')}]
        if not isinstance(spans,list) or not spans: issues.append({'id':b['block_id'],'reason':'missing source spans'}); continue
        if b.get('spans') and b.get('original_text')!='\n'.join(x.get('quote','') for x in spans): issues.append({'id':b['block_id'],'reason':'multi-page text differs from source spans'})
        for span in spans:
            loc2=span.get('source',{}).get('locator'); page=known.get(loc2)
            if not page or not span.get('quote') or span['quote'] not in page.get('text',''):
                issues.append({'id':b['block_id'],'reason':'untraceable source quote/span'}); continue
            ss=span.get('source',{})
            span_page=page.get('page') if page.get('page_kind')=='pdf' else None
            if ss.get('sha256')!=expected or Path(ss.get('file','')).resolve()!=Path(source_file).resolve() or ss.get('pdf_page')!=span_page or ss.get('page_kind')!=page.get('page_kind'):
                issues.append({'id':b['block_id'],'reason':'span file/hash/page/page_kind mismatch'})
        if b.get('kind') in ('table','figure') and (b.get('layout_status')=='unknown' or not (b.get('attachment') or b.get('image'))):
            issues.append({'id':b['block_id'],'reason':'table/figure structure or source image unresolved','critical':True})
    # Inventory must explicitly declare every coverage domain; a missing domain is unknown.
    inventory=expected_inventory or extraction.get('expected_inventory')
    inventory_reviews={}
    for row in checklist:
        if row.get('inventory_kind') and row.get('inventory_id'): inventory_reviews.setdefault(row['inventory_kind'],{})[row['inventory_id']]=row
    if not isinstance(inventory,dict):
        issues.append({'id':'expected_inventory','reason':'explicit inventory required for pages/chapters/annexes/tables/figures/references','critical':True})
    else:
        for kind in INVENTORY_KINDS:
            if kind not in inventory or not isinstance(inventory[kind],list):
                issues.append({'id':kind,'reason':'inventory domain missing or malformed','critical':True}); continue
            for item in inventory[kind]:
                iid=item if isinstance(item,str) else item.get('id')
                review=inventory_reviews.get(kind,{}).get(iid)
                if not review or review.get('status') not in ('reviewed','complete','pass','not_applicable'):
                    issues.append({'id':iid or kind,'reason':'inventory item lacks completed review','critical':True})
                if kind in ('tables','figures') and isinstance(item,dict) and item.get('attachment'):
                    attachment=Path(article_path).parent/item['attachment'] if article_path else None
                    if not attachment or not attachment.is_file(): issues.append({'id':iid,'reason':'layout attachment missing','critical':True})
        declared_pages={str(x if isinstance(x,str) else x.get('id',x.get('locator',''))) for x in inventory.get('pages',[])}
        for p in page_rows:
            if p.get('text','').strip() and p.get('locator') not in declared_pages and f"PDF page {p.get('page')}" not in declared_pages:
                issues.append({'id':p.get('locator'),'reason':'extracted page absent from explicit inventory','critical':True})
        text='\n'.join(p.get('text','') for p in page_rows)
        annex_hits=list(re.finditer(r'(?im)^\s*(?:#{1,6}\s*)?((?:(?:normative|informative)\s+)?(?:annex|appendix)\s+[A-Z0-9]+|附录\s*[A-Z0-9一二三四五六七八九十]+|附属書\s*[A-Z0-9一二三四五六七八九十]+)',text))
        for hit in annex_hits:
            label=hit.group(1).strip(); context=text[max(0,hit.start()-160):min(len(text),hit.end()+240)].lower()
            explicit_informative=('informative' in context or 'non-normative' in context or '资料性' in context or '参考' in context)
            explicit_normative=('normative' in context or '规范性' in context or '規定' in context)
            if explicit_normative and not explicit_informative:
                declared={str(x if isinstance(x,str) else x.get('id','')).lower() for x in inventory.get('normative_annexes',[])}
                if label.lower() not in declared: issues.append({'id':label,'reason':'normative annex absent from declared inventory','critical':True})
            else:
                reviewed=any(row.get('kind')=='appendix' and str(row.get('id','')).lower()==label.lower() and row.get('status') in ('reviewed','complete','pass','not_applicable') for row in checklist)
                if not reviewed: issues.append({'id':label,'reason':'annex nature unknown/informative; explicit review required','critical':True})
        detected={'normative_annexes':set(),
                  'tables':set(re.findall(r'(?im)^\s*(table\s+[A-Z0-9.-]+)',text)),
                  'figures':set(re.findall(r'(?im)^\s*((?:figure|fig\.)\s+[A-Z0-9.-]+)',text))}
        for kind,items in detected.items():
            declared={str(x if isinstance(x,str) else x.get('id','')).lower() for x in inventory.get(kind,[])}
            for found in items:
                if found.lower() not in declared: issues.append({'id':found,'reason':'source text contains unregistered inventory item','critical':True})
        reference_headers=set(re.findall(r'(?im)^\s*(?:#{1,6}\s*)?(References|Bibliography|参考文献|引用文献)\s*$',text))
        declared_refs={str(x if isinstance(x,str) else x.get('id','')).lower() for x in inventory.get('references',[])}
        for ref in reference_headers:
            if ref.lower() not in declared_refs: issues.append({'id':ref,'reason':'reference section absent from inventory','critical':True})
    for row in checklist:
        if row.get('status') not in ('reviewed','complete','pass','not_applicable'):
            issues.append({'id':row.get('id'),'reason':'review item unresolved','critical':row.get('critical',False)})
        if row.get('kind') in ('appendix','page','figure','table','formula','number','unit') and row.get('status') in ('missing','unreviewed','open'):
            missing.append(row.get('id'))
    if page_rows:
        covered={b.get('source',{}).get('locator') for b in blocks}
        covered.update(span.get('source',{}).get('locator') for b in blocks for span in b.get('spans',[]))
        for p in page_rows:
            body=p.get('text','')
            if not body.strip():
                issues.append({'id':p.get('locator'),'reason':'empty extraction page requires explicit page review','critical':True})
                continue
            if p.get('locator') not in covered: missing.append(p.get('locator')); continue
            cursor=0; page_quotes=[]
            for b in blocks:
                spans=b.get('spans') or [{'source':b.get('source',{}),'quote':b.get('original_text','')}]
                page_quotes.extend(x.get('quote','') for x in spans if x.get('source',{}).get('locator')==p.get('locator'))
            for quote in page_quotes:
                pos=body.find(quote,cursor) if quote else -1
                if pos<0:
                    issues.append({'id':p.get('locator'),'reason':'page source quotes overlap, are out of order, or are not exact','critical':True}); break
                if body[cursor:pos].strip():
                    issues.append({'id':p.get('locator'),'reason':'unrepresented non-whitespace text remains between source quotes','critical':True}); break
                cursor=pos+len(quote)
            else:
                if body[cursor:].strip(): issues.append({'id':p.get('locator'),'reason':'unrepresented non-whitespace text remains after source quotes','critical':True})
    for warning in extraction.get('warnings',[]) or []:
        closed=any(row.get('status') in ('reviewed','complete','pass') and (row.get('warning')==warning or row.get('id')==warning) for row in checklist)
        if not closed: issues.append({'id':'extraction_warning','reason':str(warning),'critical':True})
    valid_review=isinstance(review_record,dict) and all(isinstance(review_record.get(k),str) and review_record[k].strip() for k in ('reviewer','reviewed_at','approval_evidence'))
    registry_hash=None
    if not isinstance(heading_registry,dict) or heading_registry.get('source_sha256')!=expected or not isinstance(heading_registry.get('headings'),list):
        issues.append({'id':'heading_registry','reason':'source-bound heading registry required','critical':True})
    else:
        registry_hash=_hash_bytes(json.dumps(heading_registry,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
        seen=[]; registry_blocks={h.get('block_id'):h for h in heading_registry['headings']}
        for b in blocks:
            if b.get('kind') in ('heading','title'):
                h=registry_blocks.get(b.get('block_id'))
                if not h or h.get('clause_id')!=b.get('clause_id'):
                    issues.append({'id':b.get('block_id'),'reason':'source heading missing from clause heading registry','critical':True})
        for h in heading_registry['headings']:
            hs=h.get('source',{}); hp=known.get(hs.get('locator')); block=next((b for b in blocks if b.get('block_id')==h.get('block_id')),None)
            if not h.get('title') or not h.get('clause_id') or not hp or h.get('title') not in hp.get('text','') or not block or block.get('clause_id')!=h.get('clause_id'):
                issues.append({'id':h.get('heading_id'),'reason':'heading title/clause/source binding mismatch','critical':True})
            hpage=hp.get('page') if hp and hp.get('page_kind')=='pdf' else None
            if hs.get('file')!=source_file or hs.get('sha256')!=expected or not hp or hs.get('page_kind')!=hp.get('page_kind') or hs.get('pdf_page')!=hpage:
                issues.append({'id':h.get('heading_id'),'reason':'heading source file/page provenance mismatch','critical':True})
            seen.append(h.get('heading_id'))
        if len(seen)!=len(set(seen)): issues.append({'id':'heading_registry','reason':'duplicate heading IDs','critical':True})
        declared_chapters={str(x if isinstance(x,str) else x.get('id','')) for x in (inventory or {}).get('chapters',[])}
        for h in heading_registry['headings']:
            if h.get('clause_id') not in declared_chapters: issues.append({'id':h.get('clause_id'),'reason':'heading clause absent from chapter inventory','critical':True})
    if not source_exists: issues.append({'id':'source_file','reason':'source file unavailable for byte-level verification','critical':True})
    elif not source_bytes_match: issues.append({'id':'source_file','reason':'source file SHA256 differs from extraction','critical':True})
    article=None; article_hash=None; canonical=canonical_source_article(clauses)
    if article_path:
        article=Path(article_path).read_bytes(); article_hash=_hash_bytes(article)
        if article!=canonical: issues.append({'id':'article','reason':'article content differs from canonical source renderer','critical':True})
    else: issues.append({'id':'article','reason':'canonical source article required','critical':True})
    critical_open=any(x.get('critical') for x in issues)
    complete=bool(extraction.get('complete')) and bool(checklist) and not missing and not issues and valid_review and not critical_open and article_hash is not None
    # Canonical clauses digest binds the frozen snapshot to its actual reviewed input.
    clauses_bytes=json.dumps(clauses,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    frozen={'schema_version':'1.0','source_file':source_file,'source_sha256':expected,'source_complete':complete,'review_status':'source_checked' if complete else 'draft','source_review':review_record if valid_review else None,'article_path':str(Path(article_path).resolve()) if article_path else None,'article_sha256':article_hash,'clauses_sha256':_hash_bytes(clauses_bytes),'heading_registry_sha256':registry_hash,'checklist':checklist,'expected_inventory':inventory,'blockers':missing+issues}
    if output_path:
        out=Path(output_path)
        if out.exists(): raise FileExistsError(json.dumps({'error':'output_exists','path':str(out)}))
        verified_article=out.parent/'03_Original_Verified.md'
        if complete and verified_article.exists(): raise FileExistsError(json.dumps({'error':'output_exists','path':str(verified_article)}))
        if complete:
            verified_article.write_bytes(canonical)
            frozen['article_path']=str(verified_article.resolve())
        if heading_registry_path: frozen['heading_registry_path']=str(Path(heading_registry_path).resolve())
        out.write_text(json.dumps(frozen,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return frozen

def _unique_pairs(pairs):
    d={}
    for k,v in pairs:
        if k in d: raise ValueError(json.dumps({'error':'duplicate_json_key','key':k}))
        d[k]=v
    return d

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('clauses'); p.add_argument('extraction'); p.add_argument('checklist'); p.add_argument('--review-record'); p.add_argument('--article'); p.add_argument('--inventory'); p.add_argument('--heading-registry',required=True); p.add_argument('--out',required=True); a=p.parse_args(argv)
    read=lambda x:json.loads(Path(x).read_text(encoding='utf-8-sig'),object_pairs_hook=_unique_pairs)
    try:
        r=verify_source(read(a.clauses),read(a.extraction),read(a.checklist),read(a.review_record) if a.review_record else None,a.article,a.out,read(a.inventory) if a.inventory else None,read(a.heading_registry),a.heading_registry)
        print(json.dumps({'review_status':r['review_status'],'blockers':r['blockers']},ensure_ascii=False)); return 0 if r['source_complete'] else 2
    except Exception as e: print(json.dumps({'error':'verification_failed','message':str(e)},ensure_ascii=False)); return 2
if __name__=='__main__': raise SystemExit(main())
