#!/usr/bin/env python3
"""Deterministic traceability/coverage checks only; never decides engineering compliance."""
import argparse, csv, json, sys
from collections import Counter
from pathlib import Path
ALLOWED={'aligned','partial','missing','conflict','not_assessable','not_applicable'}
HEADERS=['audit_id','requirement_id','test_ids','status','severity','standard_source','plan_evidence','rationale','recommendation','review_status']

DIMENSIONS={'test_item','method','sequence','conditions','sample','equipment','calibration','preconditioning','environment','measurement','duration','acceptance_criteria','records','other'}

def _list(obj,key):
    v=obj.get(key,[]) if isinstance(obj,dict) else []
    return v if isinstance(v,list) else []

def check(reqs,plan,audit,strict=False):
    """Validate trace links. strict adds provenance and core-dimension completeness."""
    if not isinstance(reqs,dict) or not isinstance(plan,dict) or not isinstance(audit,dict): return ['requirements, plan, and audit must be objects']
    issues=[];aids=[]
    reqrows=_list(reqs,'requirements'); planrows=_list(plan,'tests'); auditrows=_list(audit,'items')
    rid_list=[x.get('requirement_id') for x in reqrows if isinstance(x,dict)];tid_list=[x.get('test_id') for x in planrows if isinstance(x,dict)]
    if len(rid_list)!=len(set(map(str,rid_list))):issues.append('duplicate requirement_id in requirements')
    if len(tid_list)!=len(set(map(str,tid_list))):issues.append('duplicate test_id in test_plan')
    if audit.get('plan_id')!=plan.get('plan_id'):issues.append('audit plan_id does not match plan')
    req_ids=set(map(str,rid_list));test_ids=set(map(str,tid_list));seen=[]
    if strict:
        for r in reqrows:
            if not isinstance(r,dict): issues.append('requirement entry must be object'); continue
            src=r.get('source') if isinstance(r.get('source'),dict) else {}
            if not isinstance(src.get('sha256'),str) or not __import__('re').fullmatch(r'[0-9a-fA-F]{64}',src.get('sha256','')): issues.append(f"{r.get('requirement_id')}: source sha256 must be 64 hexadecimal characters")
            if not isinstance(src.get('edition') or r.get('edition') or reqs.get('edition'),str) or not (src.get('edition') or r.get('edition') or reqs.get('edition')): issues.append(f"{r.get('requirement_id')}: missing standard edition")
            if r.get('source_verified') is not True: issues.append(f"{r.get('requirement_id')}: source not verified")
            quote=r.get('source_quote') or r.get('quote') or src.get('quote')
            if not isinstance(quote,str) or not quote.strip(): issues.append(f"{r.get('requirement_id')}: strict validation requires source_quote")
    for i,row in enumerate(auditrows,1):
        tag=f'item[{i}]'
        if not isinstance(row,dict): issues.append(f'{tag}: must be object'); continue
        aids.append(row.get('audit_id'))
        rid=row.get('requirement_id');seen.append(rid)
        if str(rid) not in req_ids:issues.append(f'{tag}: unknown requirement_id {rid}')
        tids=row.get('test_ids',[])
        if not isinstance(tids,list):issues.append(f'{tag}: test_ids must be list');tids=[]
        for tid in tids:
            if str(tid) not in test_ids:issues.append(f'{tag}: unknown test_id {tid}')
        status=row.get('status')
        if not isinstance(status,str) or status not in ALLOWED:
            issues.append(f'{tag}: invalid status {status}'); status='__invalid__'
        for field in ('rationale','standard_source'):
            if not str(row.get(field) or '').strip():issues.append(f'{tag}: missing {field}')
        if status in {'aligned','partial','conflict'} and not tids:issues.append(f'{tag}: {status} requires linked test_id')
        if status=='missing' and tids:issues.append(f'{tag}: missing should not have linked test_id')
        if status in {'aligned','conflict'} and not str(row.get('plan_evidence') or '').strip():issues.append(f'{tag}: {status} requires plan_evidence')
        if status in {'partial','missing','conflict'} and not str(row.get('recommendation') or '').strip():issues.append(f'{tag}: {status} requires recommendation')
        checks=row.get('checkpoints',[])
        if not isinstance(checks,list): issues.append(f'{tag}: checkpoints must be list'); checks=[]
        dims=[]
        for cp in checks:
            if not isinstance(cp,dict): continue
            dims.append(cp.get('dimension'))
        if len(dims)!=len(set(map(str,dims))): issues.append(f'{tag}: duplicate checkpoint dimensions')
        if status in {'aligned','partial','conflict'} and not checks:
            issues.append(f'{tag}: {status} requires per-dimension checkpoints')
        cp_statuses=[x.get('status') for x in checks if isinstance(x,dict)]
        if status == 'aligned' and (not any(x == 'matched' for x in cp_statuses) or any(not isinstance(x,str) or x not in {'matched','not_required'} for x in cp_statuses)):
            issues.append(f'{tag}: aligned requires at least one matched checkpoint and no missing/conflict/unknown checkpoints')
        if status == 'partial' and checks and not any(x in {'missing','unknown'} for x in cp_statuses if isinstance(x,str)):
            issues.append(f'{tag}: partial requires missing/unknown checkpoint')
        if status == 'conflict' and checks and not any(x == 'conflict' for x in cp_statuses):
            issues.append(f'{tag}: conflict requires conflicting checkpoint')
        for j,cp in enumerate(checks,1):
            if not isinstance(cp,dict): issues.append(f'{tag} checkpoint[{j}]: must be object'); continue
            if not isinstance(cp.get('dimension'),str) or cp.get('dimension') not in DIMENSIONS: issues.append(f'{tag} checkpoint[{j}]: invalid dimension')
            if not isinstance(cp.get('status'),str) or cp.get('status') not in {'matched','missing','conflict','unknown','not_required'}:
                issues.append(f'{tag} checkpoint[{j}]: invalid status')
            if cp.get('status') in ('matched','conflict') and (not cp.get('standard_basis') or not cp.get('plan_basis')):
                issues.append(f'{tag} checkpoint[{j}]: matched/conflict needs both evidences')
        if status == 'aligned':
            if str(rid) not in req_ids: issues.append(f'{tag}: unknown requirement cannot be aligned')
            elif reqs.get('requirements'):
                req=next((x for x in reqrows if isinstance(x,dict) and x.get('requirement_id')==rid),{})
                if req.get('source_verified') is not True or req.get('applicability') in (None,'unknown'): issues.append(f'{tag}: unverified/unknown requirement cannot be aligned')
            if any(isinstance(cp,dict) and cp.get('status')=='unknown' for cp in checks): issues.append(f'{tag}: unknown checkpoint cannot be aligned')
        if strict and status in {'aligned','partial','conflict','missing'}:
            # Eight core dimensions; sequence is a valid extra detail under method.
            core={'test_item','method','conditions','sample','equipment','measurement','acceptance_criteria','records'}
            present={x for x in dims if x in core}
            missing=core-present
            if missing: issues.append(f'{tag}: missing core checkpoints: {sorted(missing)}')
        if strict and status in {'not_assessable','not_applicable'} and not str(row.get('rationale') or '').strip(): issues.append(f'{tag}: {status} requires rationale')
        if row.get('review_status')=='approved':
            review=row.get('review_record') if isinstance(row.get('review_record'),dict) else {}
            if not all(isinstance(review.get(k),str) and review[k].strip() for k in ('reviewer','reviewed_at','approval_evidence')):
                issues.append(f'{tag}: approved requires human review_record with reviewer/reviewed_at/approval_evidence')
    if len(aids)!=len(set(map(str,aids))):issues.append('duplicate audit_id')
    for r in reqrows:
        if not isinstance(r,dict): continue
        if r.get('applicability') in ('applicable','conditional') and r.get('requirement_id') not in seen:
            issues.append(f"unassessed applicable requirement: {r.get('requirement_id')}")
    return issues

def main():
    ap=argparse.ArgumentParser();ap.add_argument('requirements');ap.add_argument('test_plan');ap.add_argument('audit');ap.add_argument('--csv',default=None);ap.add_argument('--strict',action='store_true');args=ap.parse_args()
    reqs=json.loads(Path(args.requirements).read_text(encoding='utf-8'));plan=json.loads(Path(args.test_plan).read_text(encoding='utf-8'));audit=json.loads(Path(args.audit).read_text(encoding='utf-8'))
    issues=check(reqs,plan,audit,strict=args.strict);summary=dict(Counter(x.get('status','unknown') for x in _list(audit,'items') if isinstance(x,dict)))
    if args.csv:
        out=Path(args.csv);out.parent.mkdir(parents=True,exist_ok=True)
        with out.open('w',encoding='utf-8-sig',newline='') as fh:
            w=csv.DictWriter(fh,fieldnames=HEADERS);w.writeheader()
            for row in _list(audit,'items'):
                if not isinstance(row,dict): continue
                obj={k:row.get(k,'') for k in HEADERS};obj['test_ids']='; '.join(row.get('test_ids',[]));w.writerow(obj)
    print(json.dumps({'coverage_status_counts':summary,'issues':issues,'ok':not issues,'disclaimer':'结构一致性检查不是试验方案的技术符合性认定'},ensure_ascii=False,indent=2))
    sys.exit(1 if issues else 0)
if __name__=='__main__':main()
