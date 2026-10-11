"""Conservative OCR spacing suggestions. Raw OCR is always retained verbatim."""
import argparse, difflib, json, re
from pathlib import Path
def _pairs(pairs):
    d={}
    for k,v in pairs:
        if k in d: raise ValueError(json.dumps({'error':'duplicate_json_key','key':k}))
        d[k]=v
    return d

def suggest(text):
    """Return candidate text and a character diff; never approves/applies it."""
    candidate = text
    # Conservative common-token segmentation, deliberately surfaced for review.
    words=('the','value','is','shall','must','not','be','of','and','or','for','record','test','sample','pressure','temperature','this','document')
    def split_run(m):
        run=m.group(0); low=run.lower(); memo={}
        def segment(pos):
            if pos==len(low): return []
            if pos in memo: return memo[pos]
            for word in words:
                if low.startswith(word,pos):
                    tail=segment(pos+len(word))
                    if tail is not None:
                        memo[pos]=[run[pos:pos+len(word)]]+tail; return memo[pos]
            memo[pos]=None; return None
        parts=segment(0)
        return ' '.join(parts) if parts and len(parts)>1 else run
    # Only split a complete alphabetic token sequence using the small explicit dictionary.
    candidate=re.sub(r'(?<![A-Za-z])[A-Za-z]{7,}(?=\d|[^A-Za-z]|$)',split_run,candidate)
    candidate=re.sub(r'\b(the|value|is|shall|must|not|be|of|and|or|for|record|test|sample|pressure|temperature|this|document)(?=\d)',r'\1 ',candidate,flags=re.I)
    return {"raw": text, "candidate": candidate,
            "diff": list(difflib.ndiff(text, candidate)), "approved": False}

def restore(records):
    out=[]
    for row in records:
        r=dict(row); raw=r.get('raw_text', r.get('text',''))
        r['raw_text']=raw; r['restoration']=suggest(raw); out.append(r)
    return out

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('input'); p.add_argument('--out',required=True); a=p.parse_args(argv)
    data=json.loads(Path(a.input).read_text(encoding='utf-8-sig'),object_pairs_hook=_pairs); rows=data if isinstance(data,list) else data.get('blocks',data.get('items',[]))
    out=Path(a.out)
    if out.exists(): raise SystemExit(json.dumps({'error':'output_exists','path':str(out)},ensure_ascii=False))
    out.write_text(json.dumps(restore(rows),ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); return 0
if __name__=='__main__': raise SystemExit(main())
