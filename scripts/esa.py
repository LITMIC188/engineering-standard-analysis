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
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def review_ok(record):
    return isinstance(record, dict) and all(isinstance(record.get(k),str) and record[k].strip()
        for k in ('reviewer','reviewed_at','approval_evidence'))

def unique(items, key):
    ids = [x.get(key) for x in items]
    if any(not isinstance(x,str) or not x.strip() for x in ids) or len(ids)!=len(set(ids)):
        raise ValueError('missing/duplicate '+key)

def source_for(document, page):
    return {'file':document['file'],'sha256':document['sha256'],
            'pdf_page':page['page'] if page['page_kind']=='pdf' else None,
            'page_kind':page['page_kind'],'locator':page['locator']}

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

def build_requirements(clauses, annotations):
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
        absent=row.get('not_required',[])
        if not isinstance(absent,list) or set(absent)-set(DIMENSIONS) or set(absent)&set(fields):
            raise ValueError('invalid/contradictory not_required dimensions')
        verified=review_ok(row.get('source_review')) and not b.get('needs_clause_review',False)
        req={**row,'clause_id':b['clause_id'],'summary':row.get('summary',quote),
             'source':{**b['source'],'standard_id':clauses['standard_id'],'edition':clauses['edition']},
             'source_verified':verified,'review_status':'source_checked' if verified else 'draft','fields':fields,
             'source_spans':b.get('spans') or [{'source':b['source'],'quote':b['original_text']}]}
        if req.get('applicability') not in ('applicable','conditional','not_applicable','unknown'):
            raise ValueError('invalid requirement applicability')
        if req.get('requirement_level') not in ('mandatory','recommended','permitted','informative','unknown'):
            raise ValueError('invalid normative strength')
        if row.get('review_status')=='approved':
            if not verified or not review_ok(row.get('review_record')): raise ValueError('approval lacks review evidence')
            req['review_status']='approved'
        requirements.append(req)
    return {'schema_version':'2.0','standard_id':clauses['standard_id'],'edition':clauses['edition'],
        'source_complete':bool(annotations.get('source_complete')) and review_ok(annotations.get('coverage_review')),
        'coverage_review':annotations.get('coverage_review'),'requirements':requirements}

def build_plan(path, annotations):
    from local_parser import extract_document
    document=extract_document(path)
    if annotations.get('source_sha256')!=document['sha256']: raise ValueError('plan annotation hash mismatch')
    if not annotations.get('plan_id') or not annotations.get('plan_version'): raise ValueError('plan identity required')
    unique(annotations['tests'],'test_id'); tests=[]
    for row in annotations['tests']:
        pages=[p for p in document['pages'] if p['locator']==row.get('locator')]
        if len(pages)!=1: raise ValueError('unknown plan locator')
        quote=row.get('quote','')
        if not quote or quote not in pages[0]['text']: raise ValueError('plan quote not found')
        fields=quote_fields(row,quote)
        tests.append({**row,**{k:v['quote'] for k,v in fields.items()},'fields':fields,
            'source':source_for(document,pages[0])})
    return {'schema_version':'2.0','plan_id':annotations['plan_id'],
        'plan_version':annotations['plan_version'],'tests':tests},document

def normalize(text):
    return re.sub(r'\s+',' ',text).strip()

def compare_literal(a,b):
    if normalize(a)==normalize(b): return 'matched'
    # Conflict only when the entire wording/unit/operator skeleton is unchanged.
    pattern=r'(?<![\w.])[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?'
    if re.findall(pattern,a)!=re.findall(pattern,b) and normalize(re.sub(pattern,'#',a))==normalize(re.sub(pattern,'#',b)):
        return 'conflict'
    return 'unknown'

def audit(requirements,plan):
    req_ids={r['requirement_id'] for r in requirements['requirements']}
    for test in plan['tests']:
        if not isinstance(test.get('requirement_ids',[]),list) or set(test.get('requirement_ids',[]))-req_ids:
            raise ValueError('unknown plan requirement mapping')
    rows=[]; reverse=[]
    for req in requirements['requirements']:
        rid=req['requirement_id']; tests=[t for t in plan['tests'] if rid in t.get('requirement_ids',[])]
        checks=[]
        for dim in DIMENSIONS:
            field=req['fields'].get(dim); standard=field['quote'] if field else None
            evidence=[t['fields'][dim]['quote'] for t in tests if dim in t['fields']]
            if field:
                statuses=[compare_literal(standard,x) for x in evidence]
                status='conflict' if 'conflict' in statuses else ('matched' if 'matched' in statuses else ('unknown' if statuses else 'missing'))
            else:
                status='not_required' if req['source_verified'] and dim in req.get('not_required',[]) else 'unknown'
            checks.append({'dimension':dim,'status':status,'standard_basis':standard,'plan_basis':' | '.join(evidence) or None})
        reasons=[]
        if req['applicability']=='not_applicable' and review_ok(req.get('applicability_review')):
            status='not_applicable'; reasons.append('有人工不适用依据')
        elif not req['source_verified'] or req['applicability'] in ('unknown','conditional','not_applicable') or req.get('reference_chain') or req['requirement_level']=='unknown':
            status='not_assessable'; reasons.append('来源、适用条件、规范强度或引用链待核实')
        elif not tests:
            status='missing'; reasons.append('未映射方案项目')
        elif any(c['status']=='conflict' for c in checks):
            status='conflict'; reasons.append('同一文字/单位结构中的数值存在冲突')
        elif any(c['status']=='missing' for c in checks):
            status='partial'; reasons.append('方案缺少已引证的字段')
        elif any(c['status']=='unknown' for c in checks) or not any(c['status']=='matched' for c in checks):
            status='not_assessable'; reasons.append('不同措辞或未界定维度需工程判断')
        else:
            status='aligned'; reasons.append('已建模字段文本一致；仍需人工工程复核')
        source=req['source']; basis=f"{source['standard_id']} {source['edition']} / {req['clause_id']} / {source['file']} / {source.get('pdf_page') or source['locator']} / SHA256 {source['sha256']}"
        gaps=[c['dimension'] for c in checks if c['status'] not in ('matched','not_required')]
        rows.append({'audit_id':f'AUD-{len(rows)+1:04}','requirement_id':rid,'test_ids':[t['test_id'] for t in tests],
            'status':status,'severity':'major' if status in ('missing','partial','conflict') else 'unknown',
            'standard_source':basis,'plan_evidence':' | '.join(t['quote'] for t in tests) or None,
            'rationale':'; '.join(reasons),'recommendation':'依据原文复核并补充 '+', '.join(gaps) if gaps else '人工确认解释、适用性及执行证据',
            'review_status':'draft','checkpoints':checks})
    for test in plan['tests']:
        reverse.append({'test_id':test['test_id'],'requirement_ids':test.get('requirement_ids',[]),
            'status':'mapped' if test.get('requirement_ids') else 'unmapped','source':test['source']})
    return {'schema_version':'2.0','plan_id':plan['plan_id'],'items':rows,'reverse_coverage':reverse}

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
    requirements=build_requirements(clauses,read(annotations_path))
    requirements['source_complete']=requirements['source_complete'] and doc['complete']
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
    manifest={'schema_version':'2.0','skill_version':'2.1','created_at':datetime.now(timezone.utc).isoformat(),
        'network_used':False,'sources':[{'file':doc['file'],'sha256':doc['sha256'],'parser':doc['parser'],'complete':doc['complete']},
            {'file':plan_doc['file'],'sha256':plan_doc['sha256'],'parser':plan_doc['parser'],'complete':plan_doc['complete']}],
        'inputs':[{'file':str(Path(p).resolve()),'sha256':digest(p)} for p in inputs],
        'standard_id':clauses['standard_id'],'edition':clauses['edition'],'source_complete':requirements['source_complete'],
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
    requirements=build_requirements(clauses,read(annotations_path))
    requirements['source_complete']=requirements['source_complete'] and document['complete']
    out.mkdir(parents=True)
    write(out/'clauses.json',clauses);write(out/'requirements.json',requirements)
    write(out/'manifest.json',{'schema_version':'2.0','skill_version':'2.1','mode':'full-analysis',
        'standard_id':clauses['standard_id'],'edition':clauses['edition'],'network_used':False,
        'sources':[{'file':document['file'],'sha256':document['sha256'],'parser':document['parser']}],
        'inputs':[{'file':str(Path(p).resolve()),'sha256':digest(p)} for p in (clauses_path,annotations_path)],
        'source_complete':requirements['source_complete'],'warnings':document['warnings'],'disclaimer':DISCLAIMER})
    csv_out(out/'requirements-matrix.csv',requirements['requirements'],['requirement_id','clause_id','summary','requirement_level','applicability','source','source_spans','fields','source_verified','review_status'])
    csv_out(out/'review_queue.csv',[{'id':r['requirement_id'],'status':r['review_status'],
        'issue':'待人工确认来源、条款类型、参数和适用性','action':'原页/规范性引用/工程解释复核'}
        for r in requirements['requirements']],['id','status','issue','action'])
    (out/'report.md').write_text('# 标准要求建模报告\n\n'+DISCLAIMER+'\n\n'+
        f"标准：{clauses['standard_id']} / {clauses['edition']}。已建模 {len(requirements['requirements'])} 条。\n\n"+
        '仅处理已提供的引用型 annotations，不宣称全标准语义抽取完毕；没有实验方案，未执行方案审查。\n',encoding='utf-8')
    return requirements

def compare(old,new,out):
    old=read(old);new=read(new)
    if old['standard_id']!=new['standard_id']: raise ValueError('different standards need manual scope mapping')
    if Path(out).exists():raise ValueError('compare output exists')
    unique(old['requirements'],'requirement_id');unique(new['requirements'],'requirement_id')
    a={r['requirement_id']:r for r in old['requirements']}; b={r['requirement_id']:r for r in new['requirements']}
    rows=[]
    for rid in sorted(set(a)|set(b)):
        x=a.get(rid);y=b.get(rid)
        rows.append({'requirement_id':rid,'old_edition':old['edition'],'new_edition':new['edition'],
            'status':'added' if x is None else 'removed' if y is None else 'unchanged_text' if x.get('quote')==y.get('quote') and x.get('fields')==y.get('fields') and x.get('applicability')==y.get('applicability') and x.get('requirement_level')==y.get('requirement_level') else 'changed_needs_review',
            'old_source':x.get('source') if x else None,'new_source':y.get('source') if y else None})
    Path(out).parent.mkdir(parents=True,exist_ok=True);csv_out(out,rows,['requirement_id','old_edition','new_edition','status','old_source','new_source'])

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
    p=sub.add_parser('compare');p.add_argument('--old',required=True);p.add_argument('--new',required=True);p.add_argument('--out',required=True)
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
        elif args.mode=='compare':compare(args.old,args.new,args.out)
        elif args.mode=='corpus-query':corpus_query(args.clauses,args.text,args.out)
        elif args.mode=='query':
            clauses=read(args.clauses);verify_clauses(clauses)
            print(json.dumps([b for b in clauses['blocks'] if args.text.casefold() in b['original_text'].casefold()],ensure_ascii=False,indent=2))
        return 0
    except (ValueError,KeyError,TypeError,OSError,RuntimeError) as exc:
        print(json.dumps({'error':str(exc),'status':'blocked'},ensure_ascii=False),file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
