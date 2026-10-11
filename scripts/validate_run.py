#!/usr/bin/env python3
"""Validate exported JSON contracts; optional jsonschema is a validation dependency."""
import argparse
import json
import sys
from pathlib import Path
from json_io import load

FILES={'clauses.json':'clauses','requirements.json':'requirements','test_plan.json':'test_plan',
       'experiment_audit.json':'experiment_audit','translations/segments.json':'translation_segments'}

def validate_run(path):
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise RuntimeError('Optional local jsonschema dependency unavailable; no installation attempted') from exc
    root=Path(__file__).resolve().parents[1];path=Path(path);errors=[]
    for name,schema in FILES.items():
        target=path/name
        if not target.exists():
            if name.startswith('translations/') or name in ('test_plan.json','experiment_audit.json'):continue
            errors.append(name+': missing');continue
        data=load(target)
        spec=load(root/'schemas'/(schema+'.schema.json'))
        Draft202012Validator.check_schema(spec)
        for error in Draft202012Validator(spec).iter_errors(data):
            errors.append(name+' / '+'/'.join(map(str,error.path))+': '+error.message)
    return errors

def main():
    ap=argparse.ArgumentParser();ap.add_argument('run_directory');args=ap.parse_args()
    try:errors=validate_run(args.run_directory)
    except (OSError,RuntimeError,ValueError) as exc:errors=[str(exc)]
    print(json.dumps({'errors':errors,'ok':not errors,'limitation':'Schema structure only; does not approve translation or engineering decisions.'},ensure_ascii=False,indent=2))
    return 1 if errors else 0

if __name__=='__main__':sys.exit(main())
