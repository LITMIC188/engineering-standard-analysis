#!/usr/bin/env python3
"""Structural and token checks for aligned translation segments.

check(data) preserves the v2 legacy interface. validate_bundle() adds strict
provenance/review checks and returns machine-readable errors and review warnings.
Neither interface judges translation meaning.
"""
import argparse, json, re, sys, unicodedata
from collections import Counter
from pathlib import Path

NUM_RE = re.compile(r"(?<!\d)(?:[+-]?\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?)(?!\d)")
UNIT_RE = re.compile(r"(?<![A-Za-z])(?:%|°[CF]|(?:m|k|M|G|c|milli)?(?:Pa|V|A|W|J|N|Hz|s|h|min|kg|g|mm|cm|m|L|K|mol|cd|rad|rpm|MPa|kPa|GPa|µm|μm))(?![A-Za-z])")
FORMULA_RE = re.compile(r"(?<!\w)(?:[A-Z][a-z]?\d+(?:\.\d+)?(?:[A-Z][a-z]?\d*(?:\.\d+)?)*)|(?:[A-Z][a-z]?\d*[₂₃₄₅₆₇₈₉₀]+)(?!\w)")
COMPARE_RE = re.compile(r"(?:<=|>=|≦|≧|≤|≥|!=|==|=|<|>)")
OPERAND = r'(?:[A-Za-zΑ-Ωα-ω](?:_[A-Za-z0-9]+)?|\d+(?:\.\d+)?)'
EQUATION_RE = re.compile(r'(?<!\w)[A-Za-zΑ-Ωα-ω](?:_[A-Za-z0-9]+)?\s*=\s*'+OPERAND+r'(?:\s*[-+*/^]\s*'+OPERAND+r')*(?!\w)')
MODAL_RE = re.compile(r"\b(shall|should|may|must|shall not|should not|may not|must not)\b|(?:しなければならない|するものとする|することが望ましい|してもよい|してはならない|ないこと)", re.I)

def _norm(s):
    return unicodedata.normalize('NFKC', s).replace('−','-').replace('–','-').replace('≦','<=').replace('≧','>=').replace('≤','<=').replace('≥','>=')

def digits(text):
    return Counter(NUM_RE.findall(_norm(text)))

def _counter(regex, text):
    # SI prefix case changes magnitude (mPa != MPa); preserve case for every
    # protected token. NFKC still folds compatibility glyphs consistently.
    return Counter(_norm(x) for x in regex.findall(_norm(text)))

def _segments(data):
    if not isinstance(data, dict): return []
    v=data.get('segments', [])
    return v if isinstance(v,list) else []

def validate_bundle(data):
    """Return {errors,warnings}; strict provenance rules for production bundles."""
    errors=[]; warnings=[]; seen=set()
    if not isinstance(data,dict): return {'errors':['bundle must be an object'],'warnings':[]}
    if data.get('schema_version') != '2.0': errors.append('schema_version must be 2.0')
    segments=data.get('segments')
    if not isinstance(segments,list) or not segments: errors.append('no segments supplied'); segments=[]
    for i,seg in enumerate(segments,1):
        p=f'segment[{i}]'
        if not isinstance(seg,dict): errors.append(f'{p}: must be object'); continue
        bid=seg.get('block_id','')
        if not isinstance(bid,str) or not bid.strip(): errors.append(f'{p}: missing block_id'); bid=''
        if str(bid) in seen: errors.append(f'{p}: duplicate block_id {bid}')
        seen.add(str(bid))
        for key in ('clause_id','source_lang','target_lang','original_text','translated_text'):
            if not isinstance(seg.get(key),str) or not seg[key].strip(): errors.append(f'{p}: missing {key}')
        page=seg.get('pdf_page'); source=seg.get('source')
        if page is not None and (isinstance(page,bool) or not isinstance(page,int) or page<1): errors.append(f'{p}: invalid pdf_page')
        if page is None:
            if not isinstance(source,dict) or not source.get('page_kind') or not source.get('locator'):
                errors.append(f'{p}: pdf_page null requires source.page_kind and source.locator')
            elif str(source.get('page_kind')).lower() == 'pdf': errors.append(f'{p}: PDF source requires pdf_page')
        a=seg.get('original_text') if isinstance(seg.get('original_text'),str) else ''
        b=seg.get('translated_text') if isinstance(seg.get('translated_text'),str) else ''
        for label,rx in [('numeric tokens',NUM_RE),('comparison operators',COMPARE_RE),('formula tokens',FORMULA_RE),('unit tokens',UNIT_RE)]:
            ca,cb=_counter(rx,a),_counter(rx,b)
            if ca != cb: errors.append(f'{p} ({bid}): {label} mismatch: {dict(ca)} != {dict(cb)}')
        equations=lambda text:Counter(re.sub(r'\s+','',_norm(m.group(0))) for m in EQUATION_RE.finditer(text))
        if equations(a)!=equations(b):errors.append(f'{p} ({bid}): algebraic formula tokens mismatch')
        pt=seg.get('protected_tokens',[])
        if not isinstance(pt,list): errors.append(f'{p}: protected_tokens must be list'); pt=[]
        for tok in pt:
            if not isinstance(tok,str): errors.append(f'{p}: protected token must be string')
            elif tok not in a or tok not in b: errors.append(f'{p} ({bid}): protected token missing/changed: {tok}')
        ma=[x.group(0).casefold() for x in MODAL_RE.finditer(a)]; mb=[x.group(0).casefold() for x in MODAL_RE.finditer(b)]
        if ma or mb:
            warnings.append(f'{p} ({bid}): normative-force/negation cue needs bilingual human review; source={ma}, target={mb}')
        if seg.get('human_reviewed') is not True: errors.append(f'{p} ({bid}): manual meaning review outstanding')
        else:
            review=seg.get('review_record') if isinstance(seg.get('review_record'),dict) else {}
            if not all(isinstance(review.get(k),str) and review[k].strip() for k in ('reviewer','reviewed_at','approval_evidence')):
                errors.append(f'{p} ({bid}): human_reviewed requires review_record reviewer/reviewed_at/approval_evidence')
        if not isinstance(seg.get('source_quote'),str) or not seg.get('source_quote').strip(): errors.append(f'{p}: strict validation requires source_quote')
        elif seg.get('source_quote') not in a: errors.append(f'{p}: source_quote not found in original_text')
    return {'errors':errors,'warnings':warnings}

def check(data, strict=False):
    """Legacy checks by default; strict=True opts into strict bundle contract."""
    if strict: return validate_bundle(data)['errors']
    issues=[]; seen=set()
    if not isinstance(data,dict): return ['bundle must be an object']
    if data.get('schema_version')!='2.0': issues.append('schema_version must be 2.0')
    segments=_segments(data)
    for i,seg in enumerate(segments,1):
        p=f'segment[{i}]'
        if not isinstance(seg,dict): issues.append(f'{p}: must be object'); continue
        bid=seg.get('block_id','')
        if not bid: issues.append(f'{p}: missing block_id')
        if str(bid) in seen: issues.append(f'{p}: duplicate block_id {bid}')
        seen.add(str(bid))
        for key in ('clause_id','source_lang','target_lang','original_text','translated_text'):
            if not isinstance(seg.get(key),str) or not seg[key].strip(): issues.append(f'{p}: missing {key}')
        page=seg.get('pdf_page')
        if page is not None and (isinstance(page,bool) or not isinstance(page,int) or page<1): issues.append(f'{p}: invalid pdf_page')
        a=seg.get('original_text') if isinstance(seg.get('original_text'),str) else ''; b=seg.get('translated_text') if isinstance(seg.get('translated_text'),str) else ''
        if digits(a)!=digits(b): issues.append(f'{p} ({bid}): numeric tokens mismatch: {dict(digits(a))} != {dict(digits(b))}')
        pt=seg.get('protected_tokens',[])
        if not isinstance(pt,list): issues.append(f'{p}: protected_tokens must be list'); pt=[]
        for tok in pt:
            if isinstance(tok,str) and (tok not in a or tok not in b): issues.append(f'{p} ({bid}): protected token missing/changed: {tok}')
        if not seg.get('human_reviewed',False): issues.append(f'{p} ({bid}): manual meaning review outstanding')
    if not segments: issues.append('no segments supplied')
    return issues

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('file'); ap.add_argument('--strict',action='store_true'); args=ap.parse_args()
    try: data=json.loads(Path(args.file).read_text(encoding='utf-8'))
    except (OSError,json.JSONDecodeError) as e: print(json.dumps({'ok':False,'issues':[str(e)]},ensure_ascii=False)); return 2
    result=validate_bundle(data) if args.strict else {'errors':check(data),'warnings':[]}
    print(json.dumps({'segments':len(_segments(data)),'issues':result['errors'],'warnings':result['warnings'],'ok':not result['errors']},ensure_ascii=False,indent=2))
    return 1 if result['errors'] else 0
if __name__=='__main__': sys.exit(main())
