#!/usr/bin/env python3
"""Explicit, review-logged migration for legacy schema v2 JSON; never grants approval."""
import argparse
import json
import sys
from pathlib import Path

from json_io import load


def migrate(data, kind):
    if not isinstance(data, dict) or data.get('schema_version') != '2.0':
        raise ValueError('input must explicitly declare schema_version 2.0')
    result=json.loads(json.dumps(data))
    changes=[]; review_queue=[]
    if kind=='test_plan':
        for row in result.get('tests',[]):
            if not isinstance(row,dict): raise ValueError('test entries must be objects')
            if 'source_spans' not in row:
                src=row.get('source',{})
                locator=row.get('locator') or row.get('source',{}).get('locator')
                quote=row.get('quote') or row.get('source',{}).get('quote')
                if not locator or not quote:
                    raise ValueError('legacy plan row lacks locator/quote; cannot synthesize source span')
                row['source_spans']=[{'sequence':1,'locator':locator,'quote':quote}]
                changes.append(f"{row.get('test_id')}: source_spans[1]")
    elif kind=='requirements':
        for row in result.get('requirements',[]):
            if row.get('review_status')=='approved':
                row['review_status']='source_checked' if row.get('source_verified') else 'draft'
                review_queue.append({'requirement_id':row.get('requirement_id'),'reason':'legacy approval requires fresh explicit review'})
                changes.append(f"{row.get('requirement_id')}: approval demoted")
            row.setdefault('audit_obligation',row.get('requirement_level') if row.get('requirement_level') in ('mandatory','recommended','permitted') else ('informative' if row.get('requirement_level')=='informative' and row.get('source_verified') is True else 'unknown'))
    else:
        raise ValueError('kind must be test_plan or requirements')
    return result, {'schema_version':'2.0','migration':'explicit-v2-contract-adapter','kind':kind,
        'changes':changes,'review_queue':review_queue,'approval_granted':False}


def main():
    p=argparse.ArgumentParser();p.add_argument('kind',choices=['test_plan','requirements']);p.add_argument('input');p.add_argument('output');p.add_argument('--log',required=True)
    a=p.parse_args()
    try:
        data=load(a.input); migrated,log=migrate(data,a.kind)
        out=Path(a.output); logpath=Path(a.log)
        if out.exists() or logpath.exists(): raise ValueError('migration output/log already exists')
        out.parent.mkdir(parents=True,exist_ok=True);logpath.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(migrated,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        logpath.write_text(json.dumps(log,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'ok':True,'approval_granted':False,'changes':len(log['changes'])},ensure_ascii=False));return 0
    except (OSError,ValueError,TypeError,KeyError) as e:
        print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False),file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
