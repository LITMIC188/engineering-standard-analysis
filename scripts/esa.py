#!/usr/bin/env python3
"""Offline evidence pipeline. Exact quotations are checked; semantics stay with reviewers."""
import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

DIMENSIONS = ('test_item','method','sequence','conditions','sample','equipment',
              'calibration','preconditioning','environment','measurement','duration',
              'acceptance_criteria','records')
DISCLAIMER = '本报告仅核对所提供方案的文本证据；不认定实际试验完成、产品符合标准或认证通过。'

def read(path):
    from json_io import load
    return load(path)

def write(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def review_ok(record):
    return isinstance(record, dict) and all(isinstance(record.get(k),str) and record[k].strip()
        for k in ('reviewer','reviewed_at','approval_evidence'))

def extract_source_inventory(clauses, validated=False):
    blocks=clauses.get('blocks',[]) if isinstance(clauses,dict) else []
    sections={}; annexes={}; tables={}; figures={}; refs={}
    for block in blocks:
        text=block.get('original_text','')
        src=block.get('source',{})
        for line in text.splitlines():
            m=re.match(r'^\s*(?:#{1,6}\s*)?(\d{1,2})\s+(?![.\d])[^\r\n]*$',line)
            if m: sections.setdefault(m.group(1),{'id':m.group(1),'block_id':block.get('block_id'),'source':src})
            m=re.match(r'^\s*(?:#{1,6}\s*)?(?:(normative)\s+)?(annex|appendix)\s+([A-Z0-9]+)\b([^\r\n]*)$',line,re.I)
            if m:
                ident=m.group(3).upper(); tail=m.group(4)
                normative=bool(m.group(1)) or bool(re.search(r'\bnormative\b',tail,re.I))
                annexes.setdefault(ident,{'id':ident,'kind':'appendix' if m.group(2).lower()=='appendix' else 'annex',
                    'normative':normative,'block_id':block.get('block_id'),'source':src})
            for kind,pattern,dest in (('table',r'\btable\s+([A-Z0-9][A-Z0-9.-]*)',tables),('figure',r'\bfig(?:ure)?\s+([A-Z0-9][A-Z0-9.-]*)',figures)):
                for match in re.finditer(pattern,text,re.I):
                    ident=match.group(1).rstrip('.,:)').upper()
                    dest.setdefault(ident,{'id':ident,'block_id':block.get('block_id'),'source':src})
            for match in re.finditer(r'^\s*\[([A-Z][A-Z0-9._-]*)\]',text,re.I|re.M):
                ident=match.group(1).upper(); refs.setdefault(ident,{'id':ident,'block_id':block.get('block_id'),'source':src})
        if block.get('kind') in ('table','figure'):
            match=re.search(r'\b(table|fig(?:ure)?)\s+([A-Z0-9][A-Z0-9.-]*)',text,re.I)
            if match:
                dest=tables if match.group(1).lower()=='table' else figures; ident=match.group(2).rstrip('.,:)').upper()
                dest.setdefault(ident,{'id':ident,'block_id':block.get('block_id'),'source':src})
    source=clauses.get('source',{}) if isinstance(clauses,dict) else {}
    return {'validated':validated,'standard_id':clauses.get('standard_id') if isinstance(clauses,dict) else None,
        'edition':clauses.get('edition') if isinstance(clauses,dict) else None,'file':source.get('file'),'sha256':source.get('sha256'),
        'sections':sorted(sections.values(),key=lambda x:x['id']),'annexes':sorted(annexes.values(),key=lambda x:x['id']),
        'normative_annex_ids':sorted(k for k,v in annexes.items() if v['normative']),
        'table_ids':sorted(tables),'figure_ids':sorted(figures),'reference_ids':sorted(refs)}

def inventory_from_document(clauses, document):
    """Expected inventory comes from every extracted source page, never the modeled subset."""
    page_blocks=[]
    for i,page in enumerate(document.get('pages',[])):
        if page.get('text','').strip():
            page_blocks.append({'block_id':f'SOURCE-{i+1}', 'original_text':page['text'],
                'source':source_for(document,page), 'kind':'clause'})
    source={'file':document.get('file'),'sha256':document.get('sha256')}
    return extract_source_inventory({'standard_id':clauses.get('standard_id'),
        'edition':clauses.get('edition'),'source':source,'blocks':page_blocks},
        validated=bool(document.get('complete') is True and not document.get('warnings')))

def modeled_page_coverage(clauses, document):
    """Require each nonblank extracted page to be represented exactly by verified spans."""
    by_page={}
    for block in clauses.get('blocks',[]):
        spans=block.get('spans') or [{'source':block.get('source',{}),'quote':block.get('original_text','')}]
        for span in spans:
            loc=span.get('source',{}).get('locator')
            pages=[p for p in document.get('pages',[]) if p.get('locator')==loc]
            if len(pages)==1 and span.get('quote') and span['quote'] in pages[0].get('text',''):
                by_page.setdefault(loc,[]).append(span['quote'])
    required={p.get('locator') for p in document.get('pages',[]) if p.get('text','').strip()}
    norm=lambda s: re.sub(r'\s+',' ',s).strip()
    missing=[]
    for page in document.get('pages',[]):
        loc=page.get('locator')
        if loc not in required: continue
        quotes=by_page.get(loc,[])
        if not quotes or norm('\n'.join(quotes))!=norm(page.get('text','')):
            missing.append(loc)
    missing=sorted(missing)
    return {'complete':not missing and document.get('complete') is True and not document.get('warnings'),
        'expected_page_locators':sorted(required), 'modeled_page_locators':sorted(set(by_page)),
        'missing_page_locators':missing}

def global_coverage(clauses, requirements):
    """Keep local extraction status separate from global clauses/objects/reference closure."""
    coverage=requirements.get('coverage',{})
    closure=requirements.get('reference_closure',{})
    inventory=requirements.get('source_inventory',{})
    # Older v2 requirement bundles predate modeled_inventory; retain their local
    # reference-check behavior while new bundles always carry the explicit model.
    modeled_inventory=requirements.get('modeled_inventory',inventory)
    if clauses:
        modeled_inventory=extract_source_inventory(clauses,validated=False)
    inventory_review=requirements.get('source_inventory_review',{})
    inv_ok=isinstance(inventory,dict) and inventory.get('validated') is True and review_ok(inventory_review) and inventory_review.get('status')=='source_checked' and inventory_review.get('source_sha256')==inventory.get('sha256')
    actual_sections=set(inventory.get('section_ids',[])) if inventory.get('section_ids') is not None else {x.get('id') for x in inventory.get('sections',[])}
    modeled_inventory_sections={x.get('id') for x in modeled_inventory.get('sections',[])}
    modeled_raw=coverage.get('modeled_sections'); required=coverage.get('required_sections')
    modeled=set(map(str,modeled_raw)) if isinstance(modeled_raw,list) else set()
    expected_sections=set(map(str,required)) if isinstance(required,list) else set()
    expected_chapters={x for x in expected_sections if re.fullmatch(r'\d{1,2}',x)}
    modeled_chapters={x for x in modeled if re.fullmatch(r'\d{1,2}',x)}
    page_cov=requirements.get('source_page_coverage',{})
    chapter_ok=inv_ok and isinstance(required,list) and bool(required) and expected_chapters==actual_sections and modeled_chapters==actual_sections and modeled_inventory_sections==actual_sections and expected_sections<=modeled and page_cov.get('complete') is True and review_ok(coverage.get('chapter_review'))
    missing_sections=sorted(expected_sections-modeled) if isinstance(required,list) else ['inventory_missing']
    annex_expected=coverage.get('normative_annexes'); annex_modeled=coverage.get('modeled_annexes')
    actual_annexes=set(inventory.get('normative_annex_ids',[]))
    modeled_annexes=set(modeled_inventory.get('normative_annex_ids',[]))
    annex_ok=inv_ok and isinstance(annex_expected,list) and isinstance(annex_modeled,list) and set(map(str,annex_expected))==actual_annexes and set(map(str,annex_modeled))==modeled_annexes and modeled_annexes==actual_annexes and review_ok(coverage.get('annex_review'))
    def object_inventory(name):
        inv=coverage.get(name)
        if not isinstance(inv,dict): return False, ['inventory_missing'], []
        expected=inv.get('expected_ids'); actual=inv.get('modeled_ids')
        if not isinstance(expected,list) or not isinstance(actual,list): return False, ['inventory_missing'], []
        actual_ids=set(map(str,actual)); expected_ids=set(map(str,expected)); source_ids=set(inventory.get(name[:-1]+'_ids',[])); modeled_ids=set(modeled_inventory.get(name[:-1]+'_ids',[]))
        missing=sorted((source_ids-expected_ids)|(expected_ids-actual_ids))
        extra=sorted((expected_ids-source_ids)|(actual_ids-expected_ids))
        return inv_ok and expected_ids==source_ids and actual_ids==expected_ids and modeled_ids==source_ids and review_ok(inv.get('review')), missing, extra
    tables_ok,missing_tables,extra_tables=object_inventory('tables'); figures_ok,missing_figures,extra_figures=object_inventory('figures')
    refs=closure.get('references'); actual_ref_ids=set(inventory.get('reference_ids',[])); modeled_ref_ids=set(modeled_inventory.get('reference_ids',[]))
    verified_refs=[]
    if isinstance(refs,list):
        for ref in refs:
            if not isinstance(ref,dict) or ref.get('status')!='resolved' or not review_ok(ref.get('resolution_review')): continue
            path=ref.get('file'); expected_hash=ref.get('sha256')
            if not isinstance(path,str) or not isinstance(expected_hash,str): continue
            try:
                resolved=Path(path).resolve(strict=True)
                if resolved.is_file() and digest(resolved)==expected_hash: verified_refs.append((str(resolved),expected_hash,ref.get('reference_id')))
            except (OSError,RuntimeError): pass
    ref_ids={r.get('reference_id') for r in refs} if isinstance(refs,list) else set()
    references_ok=inv_ok and isinstance(refs,list) and len(verified_refs)==len(refs) and len(ref_ids)==len(refs) and ref_ids==actual_ref_ids and modeled_ref_ids==actual_ref_ids and review_ok(closure.get('review'))
    source_ok=requirements.get('source_complete') is True and inv_ok and page_cov.get('complete') is True
    return {'chapters_complete':chapter_ok,'missing_sections':missing_sections,
        'normative_annexes_complete':annex_ok,
        'missing_normative_annexes':sorted((actual_annexes-set(map(str,annex_expected)))|(set(map(str,annex_expected))-set(map(str,annex_modeled)))) if isinstance(annex_expected,list) and isinstance(annex_modeled,list) else ['inventory_missing'],
        'tables_complete':tables_ok,'missing_tables':missing_tables,'unexpected_tables':extra_tables,
        'figures_complete':figures_ok,'missing_figures':missing_figures,'unexpected_figures':extra_figures,
        'references_complete':references_ok,'verified_references':[{'file':p,'sha256':h,'reference_id':rid} for p,h,rid in verified_refs],
        'source_complete':source_ok,
        'complete':chapter_ok and annex_ok and tables_ok and figures_ok and references_ok and source_ok}

def unique(items, key):
    ids = [x.get(key) for x in items]
    if any(not isinstance(x,str) or not x.strip() for x in ids) or len(ids)!=len(set(ids)):
        raise ValueError('missing/duplicate '+key)

def source_for(document, page):
    return {'file':document['file'],'sha256':document['sha256'],
            'pdf_page':page['page'] if page['page_kind']=='pdf' else None,
            'page_kind':page['page_kind'],'locator':page['locator']}

def canonical_span(locator, quote, sources, sequence=1):
    matches=[s for s in sources if s.get('source',{}).get('locator')==locator and quote and quote in s.get('quote','')]
    if len(matches)!=1: raise ValueError('untraceable source span')
    real=matches[0]['source']
    supplied=next((s for s in sources if s.get('source',{}).get('locator')==locator),{})
    src=supplied.get('source',{})
    for key in ('file','sha256','pdf_page','page_kind','locator'):
        if key in src and src[key]!=real.get(key): raise ValueError('source span provenance mismatch: '+key)
    return {'sequence':sequence,'locator':locator,'quote':quote,'source':real}

def requirement_obligation(row, source_verified):
    level=row.get('requirement_level','unknown')
    nature=row.get('normative_nature','unknown')
    if level in ('mandatory','recommended','permitted'): return level
    if nature=='normative': return 'unknown' if level in ('informative','unknown') else 'mandatory'
    if level=='informative' or nature=='informative':
        return 'informative' if source_verified else 'unknown'
    return 'unknown'

def verify_plan_field_spans(fields, root_spans, document):
    pages=document['pages']; output={}
    for dim,field in fields.items():
        quote=field['quote']; supplied=field.get('source_spans')
        if supplied is None:
            candidates=[s for s in root_spans if quote in s['quote']]
            if len(candidates)!=1: raise ValueError(f'{dim} field requires explicit source_spans')
            src=candidates[0]
            output[dim]={**field,'source_spans':[{'sequence':1,'locator':src['locator'],'quote':quote,'source':src['source']}]}
            continue
        if not isinstance(supplied,list) or not supplied: raise ValueError(f'{dim} source_spans must be non-empty')
        ordered=sorted(supplied,key=lambda s:s.get('sequence',0))
        if [s.get('sequence') for s in ordered]!=list(range(1,len(ordered)+1)):
            raise ValueError(f'{dim} source_spans sequence must be contiguous')
        normalized=[]
        for span in ordered:
            matches=[p for p in pages if p['locator']==span.get('locator')]
            if len(matches)!=1 or not isinstance(span.get('quote'),str) or not span['quote'] or span['quote'] not in matches[0]['text']:
                raise ValueError(f'untraceable {dim} field source span')
            real=source_for(document,matches[0]); claim=span.get('source')
            if claim is not None and (not isinstance(claim,dict) or any(claim.get(k)!=real.get(k) for k in ('file','sha256','pdf_page','page_kind','locator'))):
                raise ValueError(f'{dim} field source span provenance mismatch')
            normalized.append({'sequence':span['sequence'],'locator':span['locator'],'quote':span['quote'],'source':real})
        if quote!='\n'.join(s['quote'] for s in normalized): raise ValueError(f'{dim} field quote must exactly join its source_spans')
        output[dim]={**field,'source_spans':normalized}
    return output

def prepare(source, out, standard_id, edition, language):
    from local_parser import extract_document
    document = extract_document(source)
    blocks=[]
    for page in document['pages']:
        # Whole page/section candidates preserve tables; clause splitting needs review.
        if not page['text'].strip(): continue
        blocks.append({'block_id':f'B{len(blocks)+1:04}', 'clause_id':'UNRESOLVED',
            'kind':'clause','source_lang':language,'original_text':page['text'],
            'protected_tokens':[], 'source':source_for(document,page)})
    clauses={'schema_version':'2.0','standard_id':standard_id,'edition':edition,
        'source':{'file':document['file'],'sha256':document['sha256']},'blocks':blocks}
    write(Path(out)/'extraction.json',document); write(Path(out)/'clauses.json',clauses)
    write(Path(out)/'annotations.template.json', {'schema_version':'2.0',
        'standard_id':standard_id,'edition':edition,'source_complete':False,
        'requirements':[], 'instructions':'按 contract.md 填写带原文引用的原子要求；不得自动设置人工审核。'})
    return clauses

def verify_clauses(clauses):
    from local_parser import extract_document
    if not clauses.get('standard_id') or not clauses.get('edition'): raise ValueError('standard identity required')
    document=extract_document(clauses['source']['file'])
    if digest(document['file'])!=clauses['source']['sha256']: raise ValueError('source hash changed')
    unique(clauses['blocks'],'block_id')
    for block in clauses['blocks']:
        src=block['source']
        if Path(src['file']).resolve()!=Path(document['file']).resolve() or src['sha256']!=document['sha256']:
            raise ValueError('block source mismatch: '+block['block_id'])
        quote=block.get('original_text','')
        spans=block.get('spans') or [{'source':src,'quote':quote}]
        if not isinstance(spans,list):raise ValueError('spans must be list')
        for span in spans:
            location=span['source'];pages=[p for p in document['pages'] if p['locator']==location['locator']]
            if location.get('sha256')!=document['sha256'] or Path(location['file']).resolve()!=Path(document['file']).resolve():
                raise ValueError('span source mismatch')
            if len(pages)!=1 or not span.get('quote') or span['quote'] not in pages[0]['text']:
                raise ValueError('untraceable block quote: '+block['block_id'])
            p=pages[0]; expected=p['page'] if p['page_kind']=='pdf' else None
            if location.get('pdf_page')!=expected or location.get('page_kind')!=p['page_kind']:
                raise ValueError('page provenance mismatch: '+block['block_id'])
        if block.get('spans') and (src!=spans[0]['source'] or quote!='\n'.join(s['quote'] for s in spans)):
            raise ValueError('multi-page original_text must exactly join spans with newline')
        if not block.get('clause_id') or block['clause_id']=='UNRESOLVED':
            block['needs_clause_review']=True
    document['_esa_verified_clauses']=True
    return document

def quote_fields(item, text):
    fields=item.get('fields',{})
    if not isinstance(fields,dict): raise ValueError('fields must be object')
    if set(fields)-set(DIMENSIONS): raise ValueError('unsupported dimensions: '+str(set(fields)-set(DIMENSIONS)))
    for dim,field in fields.items():
        if not isinstance(field,dict) or not isinstance(field.get('quote'),str) or not field['quote'] or field['quote'] not in text:
            raise ValueError('untraceable '+dim+' quote')
        if field.get('value',field['quote'])!=field['quote']:
            raise ValueError('normalized values are not accepted as source evidence')
    return fields

def build_requirements(clauses, annotations, source_document=None):
    if (annotations.get('standard_id'),annotations.get('edition'))!=(clauses['standard_id'],clauses['edition']):
        raise ValueError('annotation standard/version mismatch')
    unique(annotations['requirements'],'requirement_id')
    blocks={b['block_id']:b for b in clauses['blocks']}; requirements=[]
    for row in annotations['requirements']:
        b=blocks.get(row.get('block_id'))
        if b is None: raise ValueError('unknown requirement block_id')
        quote=row.get('quote','')
        if not quote or quote not in b['original_text']: raise ValueError('requirement quote missing from block')
        fields=quote_fields(row,quote)
        provided_spans=row.get('source_spans')
        known=b.get('spans') or [{'source':b['source'],'quote':b['original_text']}]
        if provided_spans is None:
            matches=[s for s in known if quote in s.get('quote','')]
            if len(matches)!=1: raise ValueError('multi-span requirement quote requires explicit source_spans')
            source_spans=[canonical_span(matches[0]['source']['locator'],quote,known)]
        else:
            if not isinstance(provided_spans,list) or not provided_spans: raise ValueError('requirement source_spans must be non-empty')
            ordered=sorted(provided_spans,key=lambda s:s.get('sequence',0))
            if [s.get('sequence') for s in ordered] != list(range(1,len(ordered)+1)):
                raise ValueError('requirement source_spans sequence must be contiguous')
            source_spans=[]
            for span in ordered:
                normalized=canonical_span(span.get('locator'),span.get('quote'),known,span['sequence'])
                claim=span.get('source')
                if claim is not None:
                    if not isinstance(claim,dict) or any(claim.get(k)!=normalized['source'].get(k) for k in ('file','sha256','pdf_page','page_kind','locator')):
                        raise ValueError('requirement source span provenance mismatch')
                source_spans.append(normalized)
            if quote != '\n'.join(s['quote'] for s in source_spans):
                raise ValueError('requirement quote must exactly join source_spans')
        absent=row.get('not_required',[])
        if not isinstance(absent,list) or set(absent)-set(DIMENSIONS) or set(absent)&set(fields):
            raise ValueError('invalid/contradictory not_required dimensions')
        verified=review_ok(row.get('source_review')) and not b.get('needs_clause_review',False)
        req={**row,'clause_id':b['clause_id'],'summary':row.get('summary',quote),
             'source':{**b['source'],'standard_id':clauses['standard_id'],'edition':clauses['edition']},
             'source_verified':verified,'review_status':'source_checked' if verified else 'draft','fields':fields,
             'source_spans':source_spans,
             'audit_obligation':requirement_obligation(row,verified)}
        if req.get('applicability') not in ('applicable','conditional','not_applicable','unknown'):
            raise ValueError('invalid requirement applicability')
        if req.get('requirement_level') not in ('mandatory','recommended','permitted','informative','unknown'):
            raise ValueError('invalid normative strength')
        if row.get('review_status')=='approved':
            if not verified or not review_ok(row.get('review_record')): raise ValueError('approval lacks review evidence')
            req['review_status']='approved'
        requirements.append(req)
    source=clauses.get('source',{})
    validated=bool(source_document and source_document.get('_esa_verified_clauses') is True and source_document.get('sha256')==source.get('sha256') and source_document.get('file')==source.get('file'))
    modeled_inventory=extract_source_inventory(clauses,validated=False)
    inventory=inventory_from_document(clauses,source_document) if validated else extract_source_inventory(clauses,validated=False)
    page_coverage=modeled_page_coverage(clauses,source_document) if validated else {'complete':False,'expected_page_locators':[],'modeled_page_locators':[],'missing_page_locators':['source_document_unverified']}
    return {'schema_version':'2.0','standard_id':clauses['standard_id'],'edition':clauses['edition'],
        'source_complete':bool(annotations.get('source_complete')) and review_ok(annotations.get('coverage_review')),
        'coverage_review':annotations.get('coverage_review'),'requirements':requirements,
        'coverage':annotations.get('coverage',{}),
        'reference_closure':annotations.get('reference_closure',{}),'source_inventory':inventory,
        'modeled_inventory':modeled_inventory,'source_page_coverage':page_coverage,
        'source_inventory_review':annotations.get('source_inventory_review',{})}

def build_plan(path, annotations):
    from local_parser import extract_document
    document=extract_document(path)
    if annotations.get('source_sha256')!=document['sha256']: raise ValueError('plan annotation hash mismatch')
    if not annotations.get('plan_id') or not annotations.get('plan_version'): raise ValueError('plan identity required')
    unique(annotations['tests'],'test_id'); tests=[]
    for row in annotations['tests']:
        spans=row.get('source_spans')
        if spans is None:
            spans=[{'locator':row.get('locator'),'quote':row.get('quote',''),'sequence':1}]
        if not isinstance(spans,list) or not spans: raise ValueError('source_spans must be a non-empty list')
        ordered=sorted(spans,key=lambda s:s.get('sequence',0))
        if [s.get('sequence') for s in ordered] != list(range(1,len(ordered)+1)):
            raise ValueError('source_spans sequence must be unique and contiguous from 1')
        verified=[]
        for span in ordered:
            pages=[p for p in document['pages'] if p['locator']==span.get('locator')]
            if len(pages)!=1: raise ValueError('unknown plan span locator')
            if not isinstance(span.get('quote'),str) or not span['quote'] or span['quote'] not in pages[0]['text']:
                raise ValueError('plan span quote not found')
            real=source_for(document,pages[0]); claim=span.get('source')
            if claim is not None and (not isinstance(claim,dict) or any(claim.get(k)!=real.get(k) for k in ('file','sha256','pdf_page','page_kind','locator'))):
                raise ValueError('plan span provenance mismatch')
            verified.append({'sequence':span['sequence'],'locator':span['locator'],'quote':span['quote'],
                'source':real})
        quote='\n'.join(s['quote'] for s in ordered)
        if row.get('quote') and row['quote'] != quote: raise ValueError('plan quote must exactly join source_spans')
        fields=verify_plan_field_spans(quote_fields(row,quote),verified,document)
        first=next(p for p in document['pages'] if p['locator']==ordered[0]['locator'])
        tests.append({**row,**{k:v['quote'] for k,v in fields.items()},'fields':fields,
            'quote':quote,'source_spans':verified,'source':source_for(document,first)})
    return {'schema_version':'2.0','plan_id':annotations['plan_id'],
        'plan_version':annotations['plan_version'],'tests':tests,
        'coverage':annotations.get('coverage',{})},document

def normalize(text):
    return re.sub(r'\s+',' ',text).strip()

def compare_literal(a,b):
    if normalize(a)==normalize(b): return 'matched'
    # Conflict only when the entire wording/unit/operator skeleton is unchanged.
    pattern=r'(?<![\w.])[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?'
    if re.findall(pattern,a)!=re.findall(pattern,b) and normalize(re.sub(pattern,'#',a))==normalize(re.sub(pattern,'#',b)):
        return 'conflict'
    return 'unknown'

def evaluate_candidate(req, tests):
    checks=[]
    for dim in DIMENSIONS:
        field=req['fields'].get(dim); standard=field['quote'] if field else None
        evidence=[t['fields'][dim]['quote'] for t in tests if dim in t.get('fields',{})]
        if field:
            states=[compare_literal(standard,x) for x in evidence]
            state='conflict' if 'conflict' in states else ('matched' if 'matched' in states else ('unknown' if states else 'missing'))
        else: state='not_required' if req['source_verified'] and dim in req.get('not_required',[]) else 'unknown'
        checks.append({'dimension':dim,'status':state,'standard_basis':standard,'plan_basis':' | '.join(evidence) or None})
    if any(c['status']=='conflict' for c in checks): status='conflict'
    elif any(c['status']=='missing' for c in checks): status='partial'
    elif any(c['status']=='unknown' for c in checks) or not any(c['status']=='matched' for c in checks): status='not_assessable'
    else: status='aligned'
    return status,checks

def audit(requirements,plan):
    req_ids={r['requirement_id'] for r in requirements['requirements']}
    for test in plan['tests']:
        if not isinstance(test.get('requirement_ids',[]),list) or set(test.get('requirement_ids',[]))-req_ids:
            raise ValueError('unknown plan requirement mapping')
    rows=[]; reverse=[]; cov=global_coverage({},requirements)
    verified_refs={(r['file'],r['sha256']) for r in cov['verified_references']}
    for req in requirements['requirements']:
        rid=req['requirement_id']; mapped=[t for t in plan['tests'] if rid in t.get('requirement_ids',[])]
        units=[[t] for t in mapped]; groups={}
        for test in mapped:
            key=tuple(test.get(k) for k in ('protocol_id','phase','sample_group','combination_group'))
            if all(isinstance(v,str) and v.strip() for v in key): groups.setdefault(key,[]).append(test)
        for group in groups.values():
            if len(group)>1 and all(review_ok(t.get('combination_evidence')) for t in group): units.append(group)
        candidates=[]
        for unit in units:
            state,checks=evaluate_candidate(req,unit)
            candidates.append({'test_ids':[t['test_id'] for t in unit],'status':state,'checkpoints':checks,
                'plan_evidence':' | '.join(t.get('quote','') for t in unit) or None})
        selected=next((x for x in candidates if x['status']=='aligned'),None)
        if selected is None:
            selected=next((x for x in candidates if x['status']=='conflict'),None) or next((x for x in candidates if x['status']=='partial'),None) or (candidates[0] if candidates else {'test_ids':[],'status':'missing','checkpoints':[],'plan_evidence':None})
        status=selected['status']; checks=selected['checkpoints']; reasons=[]
        obligation=req.get('audit_obligation') or requirement_obligation(req,req.get('source_verified') is True)
        chain=req.get('reference_chain',[])
        chain_closed=isinstance(chain,list) and all(isinstance(x,dict) and isinstance(x.get('file'),str) and (str(Path(x['file']).resolve()),x.get('sha256')) in verified_refs for x in chain)
        if obligation=='informative': status='not_assessable'; reasons.append('已核验的资料性内容不形成试验义务')
        elif obligation=='unknown': status='not_assessable'; reasons.append('规范义务属性未核实')
        elif req['applicability']=='not_applicable' and review_ok(req.get('applicability_review')): status='not_applicable'; reasons.append('有人工不适用依据')
        elif not req['source_verified'] or req['applicability'] in ('unknown','conditional','not_applicable') or not chain_closed:
            status='not_assessable'; reasons.append('来源、适用条件或规范性引用链未闭环')
        elif len(mapped)>1 and selected['status']!='aligned' and evaluate_candidate(req,mapped)[0]=='aligned' and not any(len(c['test_ids'])>1 for c in candidates):
            status='not_assessable'; reasons.append('只有跨无关联测试合并字段才可对齐，保留未评估状态')
        elif not mapped: status='missing'; reasons.append('未映射方案项目')
        elif status=='conflict': reasons.append('单一候选中的相同文字/单位结构数值冲突')
        elif status=='partial': reasons.append('该单一测试或经审签组合组缺少已引证字段')
        elif status=='not_assessable': reasons.append('单一候选措辞或维度需工程判断')
        else: reasons.append('单一测试或经审签组合组的已建模字段文本一致；仍需人工工程复核')
        source=req['source']; basis=f"{source['standard_id']} {source['edition']} / {req['clause_id']} / {source['file']} / {source.get('pdf_page') or source['locator']} / SHA256 {source['sha256']}"
        gaps=[c['dimension'] for c in checks if c['status'] not in ('matched','not_required')]
        risks=req.get('risk_factors',{}); risk_review=req.get('risk_review'); risk_keys=('safety','regulatory','failure_likelihood','detectability')
        risk_ok=review_ok(risk_review) and isinstance(risks,dict) and all(k in risks and risks[k] in ('low','medium','high','unknown') for k in risk_keys)
        if not risk_ok: severity='unknown'; risk_text='风险因子或审签记录缺失，严重度未知'
        elif 'unknown' in [risks[k] for k in risk_keys]: severity='unknown'; risk_text='风险因子含 unknown；严重度未知'
        else:
            vals=[risks[k] for k in risk_keys]; severity='critical' if any(v=='high' for v in vals[:2]) else ('major' if 'high' in vals or vals.count('medium')>=2 else 'minor')
            risk_text='审签风险因子='+json.dumps(risks,ensure_ascii=False)
        rows.append({'audit_id':f'AUD-{len(rows)+1:04}','requirement_id':rid,'audit_obligation':obligation,
            'test_ids':[t['test_id'] for t in mapped],'evaluated_test_ids':selected['test_ids'],'candidate_results':candidates,
            'status':status,'severity':severity,'risk_rationale':risk_text,'standard_source':basis,
            'plan_evidence':selected['plan_evidence'],'rationale':'; '.join(reasons+[risk_text]),
            'recommendation':'依据原文复核并补充 '+', '.join(gaps) if gaps else '人工确认解释、适用性及执行证据',
            'review_status':'draft','checkpoints':checks})
    for test in plan['tests']:
        reverse.append({'test_id':test['test_id'],'requirement_ids':test.get('requirement_ids',[]),
            'status':'mapped' if test.get('requirement_ids') else 'unmapped','source':test['source']})
    return {'schema_version':'2.0','plan_id':plan['plan_id'],'items':rows,'reverse_coverage':reverse,
        'coverage':cov,'reference_closure':requirements.get('reference_closure',{})}

def csv_out(path,rows,headers):
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=headers);writer.writeheader()
        for row in rows:
            safe={k:json.dumps(row.get(k),ensure_ascii=False) if isinstance(row.get(k),(list,dict)) else row.get(k,'') for k in headers}
            # CSVs are reviewed in spreadsheets; never interpret source text as formulas.
            writer.writerow({k:("'"+v if isinstance(v,str) and v.startswith(('=','+','-','@')) else v) for k,v in safe.items()})

def export_study(requirements,out):
    out=Path(out)
    if out.exists(): raise ValueError('study output exists; choose a new directory')
    approved=[r for r in requirements['requirements'] if r['review_status']=='approved' and r['source_verified'] and review_ok(r.get('review_record'))]
    for requirement in approved:
        src=requirement['source']
        if src.get('standard_id')!=requirements.get('standard_id') or src.get('edition')!=requirements.get('edition'):
            raise ValueError('study standard/version mismatch')
        verify_clauses({'standard_id':requirements['standard_id'],'edition':requirements['edition'],
            'source':src,'blocks':[{'block_id':requirement['requirement_id'],'clause_id':requirement['clause_id'],
                'source':{k:v for k,v in src.items() if k not in ('standard_id','edition')},
                'original_text':'\n'.join(s['quote'] for s in requirement['source_spans']),
                'spans':requirement['source_spans']}]})
    out.mkdir(parents=True); source=out/'source';source.mkdir()
    for index,r in enumerate(approved,1):
        name=f'knowledge-{index:04}.md'
        meta=json.dumps(r['source'],ensure_ascii=False)
        (source/name).write_text(f"# {r['requirement_id']} — {r['clause_id']}\n\n审核后的标准知识（不是产品符合性结论）。\n\n{r['summary']}\n\n原文引用：\n\n{r['quote']}\n\n来源：{meta}\n\n审核：{json.dumps(r['review_record'],ensure_ascii=False)}\n",encoding='utf-8')
    write(out/'handoff.json',{'mode':'Document Mode','source':str(source.resolve()),
        'output':str((out/'StudyVault').resolve()),'approved_count':len(approved),
        'excluded_ids':[r['requirement_id'] for r in requirements['requirements'] if r not in approved],
        'instruction':'读取本机 tutor-setup/SKILL.md；显式选择 Document Mode 与 source；中间文件放输出 .tutor-work/；未调用 tutor-setup。'})
    return len(approved)

def run(clauses_path,annotations_path,plan_path,plan_annotations_path,out,translations_path=None,design_path=None):
    out=Path(out)
    if out.exists(): raise ValueError('output already exists; choose a new job directory')
    clauses=read(clauses_path); doc=verify_clauses(clauses)
    requirements=build_requirements(clauses,read(annotations_path),doc)
    requirements['source_complete']=requirements['source_complete'] and doc['complete'] and not doc.get('warnings') and requirements['source_page_coverage'].get('complete') is True
    plan,plan_doc=build_plan(plan_path,read(plan_annotations_path)); result=audit(requirements,plan)
    translations=None; translation_issues=[]
    if translations_path:
        from validate_translation import check
        translations=read(translations_path); blocks={b['block_id']:b for b in clauses['blocks']}
        unique(translations['segments'],'block_id')
        if {s['block_id'] for s in translations['segments']}!=set(blocks): raise ValueError('translation coverage missing/extra blocks')
        for seg in translations['segments']:
            b=blocks[seg['block_id']]
            if any(seg.get(k)!=b.get(k) for k in ('clause_id','original_text','source_lang')) or seg.get('source')!=b['source'] or seg.get('pdf_page')!=b['source']['pdf_page']:
                raise ValueError('translation provenance mismatch')
            if not set(b.get('protected_tokens',[])).issubset(seg.get('protected_tokens',[])): raise ValueError('translation protection removed')
        translation_issues=check(translations,strict=True)
        bad={s['block_id'] for s in translations['segments'] if not s.get('human_reviewed') or check({'schema_version':'2.0','segments':[s]},strict=True)}
        for row in result['items']:
            req=next(r for r in requirements['requirements'] if r['requirement_id']==row['requirement_id'])
            if req['block_id'] in bad:
                row['status']='not_assessable';row['rationale']='翻译质量门禁未闭环；'+row['rationale']
    from validate_experiment_audit import check as check_audit
    errors=check_audit(requirements,plan,result)
    if errors: raise ValueError('generated audit invalid: '+str(errors))
    designs=read(design_path).get('items',[]) if design_path else []
    unique(designs,'design_id')
    for d in designs:
        if d.get('requirement_id') not in {r['requirement_id'] for r in requirements['requirements']}: raise ValueError('unknown design requirement')
    out.mkdir(parents=True)
    inputs=[clauses_path,annotations_path,plan_path,plan_annotations_path]+([translations_path] if translations_path else [])+([design_path] if design_path else [])
    manifest={'schema_version':'2.0','skill_version':'2.4','created_at':datetime.now(timezone.utc).isoformat(),
        'network_used':False,'sources':[{'file':doc['file'],'sha256':doc['sha256'],'parser':doc['parser'],'complete':doc['complete']},
            {'file':plan_doc['file'],'sha256':plan_doc['sha256'],'parser':plan_doc['parser'],'complete':plan_doc['complete']}],
        'inputs':[{'file':str(Path(p).resolve()),'sha256':digest(p)} for p in inputs],
        'standard_id':clauses['standard_id'],'edition':clauses['edition'],'source_complete':requirements['source_complete'],
            'modeled_source_complete':requirements['source_page_coverage'].get('complete') is True,
            'coverage':global_coverage(clauses,requirements),
            'warnings':doc['warnings']+plan_doc['warnings']+translation_issues,'disclaimer':DISCLAIMER}
    for name,data in [('manifest',manifest),('clauses',clauses),('requirements',requirements),('test_plan',plan),('experiment_audit',result)]:write(out/(name+'.json'),data)
    if translations:write(out/'translations'/'segments.json',translations)
    csv_out(out/'requirements-matrix.csv',requirements['requirements'],['requirement_id','clause_id','summary','requirement_level','applicability','source','fields','source_verified','review_status'])
    csv_out(out/'experiment_audit.csv',result['items'],['audit_id','requirement_id','test_ids','status','severity','standard_source','plan_evidence','rationale','recommendation','review_status','checkpoints'])
    csv_out(out/'reverse_coverage.csv',result['reverse_coverage'],['test_id','requirement_ids','status','source'])
    queue=[{'id':r['requirement_id'],'status':r['status'],'issue':r['rationale'],'action':r['recommendation']} for r in result['items']]
    queue += [{'id':t['test_id'],'status':'unmapped','issue':'方案项目没有标准要求映射','action':'确认自选试验或补充条款依据'} for t in result['reverse_coverage'] if t['status']=='unmapped']
    queue += [{'id':'translation','status':'needs_human_review','issue':i,'action':'原页/语义复核'} for i in translation_issues]
    csv_out(out/'review_queue.csv',queue,['id','status','issue','action'])
    text=['# 实验方案整改建议','',DISCLAIMER,'','以下为建议；原文要求见 requirements.json，负责人/期限均待指定。','']
    for row in result['items']:
        text += [f"## {row['requirement_id']} / {row['status']}", '',row['standard_source'],'',row['rationale'],'',row['recommendation'],'','负责人：待指定。复核：提供修订方案与人工审核记录。','']
    (out/'remediation_plan.md').write_text('\n'.join(text),encoding='utf-8')
    counts={s:sum(r['status']==s for r in result['items']) for s in sorted({r['status'] for r in result['items']})}
    (out/'report.md').write_text('# 可追溯方案审查报告\n\n'+DISCLAIMER+'\n\n'+
        f"标准：{clauses['standard_id']} / {clauses['edition']}。输入完整性人审：{requirements['source_complete']}。\n\n"+
        '当前条目状态：'+json.dumps(counts,ensure_ascii=False)+'\n\n'+
        '所有自动结论为草案。措辞不同、翻译未审、引用缺失和适用性不明均不得算覆盖通过。\n\n'+
        '已审查范围为 requirements.json 的显式建模条目，不推断全标准覆盖。解析警告与翻译疑点见 manifest.json；待办见 review_queue.csv。\n',encoding='utf-8')
    trace=[]
    for row in result['items']:
        links=[d for d in designs if d['requirement_id']==row['requirement_id']] or [{}]
        for d in links:trace.append({'requirement_id':row['requirement_id'],'standard_source':row['standard_source'],
            'design_id':d.get('design_id'),'design_input':d.get('design_input'),'test_ids':row['test_ids'],
            'evidence':d.get('evidence'),'evidence_status':'provided_unverified' if d.get('evidence') else 'not_provided'})
    csv_out(out/'traceability.csv',trace,['requirement_id','standard_source','design_id','design_input','test_ids','evidence','evidence_status'])
    return manifest

def full_analysis(clauses_path,annotations_path,out):
    out=Path(out)
    if out.exists():raise ValueError('output already exists; choose a new job directory')
    clauses=read(clauses_path);document=verify_clauses(clauses)
    requirements=build_requirements(clauses,read(annotations_path),document)
    requirements['source_complete']=requirements['source_complete'] and document['complete'] and not document.get('warnings') and requirements['source_page_coverage'].get('complete') is True
    out.mkdir(parents=True)
    write(out/'clauses.json',clauses);write(out/'requirements.json',requirements)
    write(out/'manifest.json',{'schema_version':'2.0','skill_version':'2.4','mode':'full-analysis',
        'standard_id':clauses['standard_id'],'edition':clauses['edition'],'network_used':False,
        'sources':[{'file':document['file'],'sha256':document['sha256'],'parser':document['parser']}],
        'inputs':[{'file':str(Path(p).resolve()),'sha256':digest(p)} for p in (clauses_path,annotations_path)],
        'source_complete':requirements['source_complete'],'modeled_source_complete':requirements['source_page_coverage'].get('complete') is True,'coverage':global_coverage(clauses,requirements),
        'warnings':document['warnings'],'disclaimer':DISCLAIMER})
    csv_out(out/'requirements-matrix.csv',requirements['requirements'],['requirement_id','clause_id','summary','requirement_level','applicability','source','source_spans','fields','source_verified','review_status'])
    csv_out(out/'review_queue.csv',[{'id':r['requirement_id'],'status':r['review_status'],
        'issue':'待人工确认来源、条款类型、参数和适用性','action':'原页/规范性引用/工程解释复核'}
        for r in requirements['requirements']],['id','status','issue','action'])
    (out/'report.md').write_text('# 标准要求建模报告\n\n'+DISCLAIMER+'\n\n'+
        f"标准：{clauses['standard_id']} / {clauses['edition']}。已建模 {len(requirements['requirements'])} 条。\n\n"+
        '仅处理已提供的引用型 annotations，不宣称全标准语义抽取完毕；没有实验方案，未执行方案审查。\n',encoding='utf-8')
    return requirements

def compare(old,new,out,mapping_path=None):
    old=read(old);new=read(new)
    if old['standard_id']!=new['standard_id']: raise ValueError('different standards need manual scope mapping')
    if Path(out).exists():raise ValueError('compare output exists')
    unique(old['requirements'],'requirement_id');unique(new['requirements'],'requirement_id')
    a={r['requirement_id']:r for r in old['requirements']}; b={r['requirement_id']:r for r in new['requirements']}
    mappings=read(mapping_path).get('mappings',[]) if mapping_path else []
    mapped_old=set();mapped_new=set(); explicit={}
    for m in mappings:
        if m.get('old_requirement_id') not in a or m.get('new_requirement_id') not in b: raise ValueError('version mapping references unknown requirement')
        if m['old_requirement_id'] in mapped_old or m['new_requirement_id'] in mapped_new: raise ValueError('version mapping must be one-to-one')
        if m.get('mapping_type') not in ('renumbering','amendment') or not review_ok(m.get('review_record')): raise ValueError('version mapping requires explicit type and review log')
        mapped_old.add(m['old_requirement_id']);mapped_new.add(m['new_requirement_id']);explicit[m['old_requirement_id']]=m
    rows=[]
    paired={}
    for rid,m in explicit.items():
        paired[rid]=m['new_requirement_id']
    emitted_new=set(paired.values())
    for rid in sorted((set(a)|set(b))-set(paired)-emitted_new):
        x=a.get(rid);y=b.get(rid)
        rows.append({'requirement_id':rid,'old_edition':old['edition'],'new_edition':new['edition'],
            'status':'added' if x is None else 'removed' if y is None else 'unchanged_text' if x.get('quote')==y.get('quote') and x.get('fields')==y.get('fields') and x.get('applicability')==y.get('applicability') and x.get('requirement_level')==y.get('requirement_level') else 'changed_needs_review',
            'old_source':x.get('source') if x else None,'new_source':y.get('source') if y else None})
    for old_id,new_id in paired.items():
        rows.append({'requirement_id':old_id,'old_edition':old['edition'],'new_edition':new['edition'],
            'status':'renumbered_needs_review' if explicit[old_id]['mapping_type']=='renumbering' else 'amendment_needs_review',
            'mapped_new_requirement_id':new_id,'mapping_type':explicit[old_id]['mapping_type'],
            'equivalence_claim':False,'mapping_review':explicit[old_id]['review_record'],
            'old_source':a[old_id].get('source'),'new_source':b[new_id].get('source')})
    Path(out).parent.mkdir(parents=True,exist_ok=True);csv_out(out,rows,['requirement_id','old_edition','new_edition','status','mapped_new_requirement_id','mapping_type','equivalence_claim','mapping_review','old_source','new_source'])

def corpus_query(paths,text,out):
    if Path(out).exists():raise ValueError('query output exists')
    matches=[];coverage=[]
    for path in paths:
        clauses=read(path);document=verify_clauses(clauses)
        coverage.append({'file':document['file'],'sha256':document['sha256'],
            'parsed_pages':len(document['pages']),'modeled_blocks':len(clauses['blocks']),
            'complete_extraction':document['complete']})
        matches.extend({'standard_id':clauses['standard_id'],'edition':clauses['edition'],**b}
            for b in clauses['blocks'] if text.casefold() in b['original_text'].casefold())
    write(out,{'query':text,'coverage':coverage,'matches':matches,
        'limitation':'仅在显式指定且已建模的块内做文本检索；无命中不代表标准没有要求。'})

def main():
    ap=argparse.ArgumentParser(description=DISCLAIMER); sub=ap.add_subparsers(dest='mode',required=True)
    p=sub.add_parser('prepare');p.add_argument('source');p.add_argument('--out',required=True)
    for name in ('standard-id','edition','language'):p.add_argument('--'+name,required=True)
    p=sub.add_parser('audit-test-plan')
    for name in ('clauses','annotations','plan','plan-annotations','out'):p.add_argument('--'+name,required=True)
    p.add_argument('--translations');p.add_argument('--design')
    p=sub.add_parser('full-analysis')
    for name in ('clauses','annotations','out'):p.add_argument('--'+name,required=True)
    p=sub.add_parser('study');p.add_argument('--requirements',required=True);p.add_argument('--out',required=True)
    p=sub.add_parser('compare');p.add_argument('--old',required=True);p.add_argument('--new',required=True);p.add_argument('--out',required=True);p.add_argument('--mapping')
    p=sub.add_parser('query');p.add_argument('--clauses',required=True);p.add_argument('--text',required=True)
    p=sub.add_parser('corpus-query');p.add_argument('--clauses',action='append',required=True);p.add_argument('--text',required=True);p.add_argument('--out',required=True)
    args=ap.parse_args()
    try:
        if args.mode=='prepare':
            if Path(args.out).exists():raise ValueError('prepare output exists')
            prepare(args.source,args.out,args.standard_id,args.edition,args.language)
        elif args.mode=='audit-test-plan':run(args.clauses,args.annotations,args.plan,args.plan_annotations,args.out,args.translations,args.design)
        elif args.mode=='full-analysis':full_analysis(args.clauses,args.annotations,args.out)
        elif args.mode=='study':print(json.dumps({'approved_count':export_study(read(args.requirements),args.out)}))
        elif args.mode=='compare':compare(args.old,args.new,args.out,args.mapping)
        elif args.mode=='corpus-query':corpus_query(args.clauses,args.text,args.out)
        elif args.mode=='query':
            clauses=read(args.clauses);verify_clauses(clauses)
            print(json.dumps([b for b in clauses['blocks'] if args.text.casefold() in b['original_text'].casefold()],ensure_ascii=False,indent=2))
        return 0
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as exc:
        print(json.dumps({'error':str(exc),'status':'blocked'},ensure_ascii=False),file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
