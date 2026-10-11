"""Full offline workflow on clearly fictional source; fixture reviews are not approvals."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import esa
from heading_registry import build_registry
from local_parser import extract_document
from verify_source import canonical_source_article

class WorkflowSmoke(unittest.TestCase):
    def invoke(self,*args,expected=0):
        result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts'/args[0]),*map(str,args[1:])],
            capture_output=True,text=True,encoding='utf-8',cwd=ROOT)
        self.assertEqual(result.returncode,expected,result.stdout+result.stderr)
        return result

    def test_source_to_bilingual_to_obsidian_dry_run(self):
        with tempfile.TemporaryDirectory() as td:
            run=Path(td);source=run/'fictional-standard.md'
            texts=['# 1 Scope\nFictional scope.', '# 2 Method\nFictional method at 5 kPa.', '# 3 Records\nFictional record 1 sample.']
            source.write_bytes(('\n\n'.join(texts)+'\n').encode('utf-8'))
            extraction=extract_document(source)
            location=esa.source_for(extraction,extraction['pages'][0])
            clauses={'schema_version':'2.0','standard_id':'SYNTHETIC-NOT-A-STANDARD','edition':'TEST-ONLY',
                'source':{'file':str(source),'sha256':extraction['sha256']},'blocks':[
                    {'block_id':f'B{i}','clause_id':str(i),'kind':'heading','source_lang':'en','title':text.splitlines()[0][2:],
                     'original_text':text,'source':location,'protected_tokens':[]}
                    for i,text in enumerate(texts,1)]}
            registry=build_registry(clauses['blocks'],extraction['sha256'],extraction['pages'])
            inventory={'pages':[location['locator']],'chapters':['1','2','3'],'normative_annexes':[],
                       'tables':[],'figures':[],'references':[]}
            checklist=[{'id':f'{kind}:{value}','inventory_kind':kind,'inventory_id':value,'status':'reviewed'}
                       for kind,values in inventory.items() for value in values]
            review={'reviewer':'SYNTHETIC TEST FIXTURE','reviewed_at':'2099-01-01',
                    'approval_evidence':'SYNTHETIC ONLY - not a human approval'}
            segments={'schema_version':'2.0','segments':[
                {'block_id':b['block_id'],'clause_id':b['clause_id'],'source_lang':'en','target_lang':'zh-CN',
                 'source':b['source'],'pdf_page':None,'original_text':b['original_text'],
                 'translated_text':f'合成段落 {b["block_id"]}；{b["original_text"]}', 'human_reviewed':False,
                 'protected_tokens':[],'source_quote':b['original_text']}
                for b in reversed(clauses['blocks'])]}
            for name,data in [('clauses.json',clauses),('extraction.json',extraction),('registry.json',registry),
                              ('inventory.json',inventory),('checklist.json',checklist),('review.json',review),('segments.json',segments)]:
                esa.write(run/name,data)
            self.invoke('reconstruct_source.py',run/'extraction.json','--clauses',run/'clauses.json','--out-dir',run/'reconstruction')
            article=run/'reconstruction/02_Original_Reconstructed.md'
            self.assertEqual(article.read_bytes(),canonical_source_article(clauses))
            self.invoke('verify_source.py',run/'clauses.json',run/'extraction.json',run/'checklist.json',
                '--review-record',run/'review.json','--article',article,'--inventory',run/'inventory.json',
                '--heading-registry',run/'registry.json','--out',run/'verified_source.json')
            frozen=esa.read(run/'verified_source.json')
            self.assertEqual(frozen['review_status'],'source_checked')
            self.invoke('translate_dispatch.py',run/'clauses.json',run/'verified_source.json','--out',run/'dispatch.json')
            self.assertTrue(esa.read(run/'dispatch.json')['parallel'])
            self.invoke('render_full_articles.py',run/'clauses.json','--translations',run/'segments.json',
                '--verified-source',run/'verified_source.json','--out-dir',run/'articles')
            translated=(run/'articles/04_Translation_Complete.md').read_text(encoding='utf-8')
            self.assertLess(translated.index('合成段落 B1'),translated.index('合成段落 B3'))
            self.assertIn('DRAFT',translated)
            self.assertEqual(hashlib.sha256(Path(frozen['article_path']).read_bytes()).hexdigest(),frozen['article_sha256'])
            b=clauses['blocks'][1]
            reqs={'schema_version':'2.0','standard_id':clauses['standard_id'],'edition':clauses['edition'],
                  'source_complete':True,'requirements':[{'requirement_id':'REQ-SYNTH-1','block_id':b['block_id'],
                    'clause_id':b['clause_id'],'quote':'Fictional method at 5 kPa.','summary':'合成要求，非真实标准',
                    'source':{**b['source'],'standard_id':clauses['standard_id'],'edition':clauses['edition']},
                    'source_review':review,'source_verified':True,'review_status':'draft','requirement_level':'mandatory',
                    'applicability':'applicable','fields':{'method':{'quote':'Fictional method at 5 kPa.'}}}]}
            esa.write(run/'requirements.json',reqs)
            vault=run/'disposable-vault';vault.mkdir()
            request={'interface_id':'B-接口-02','interface_name':'render_obsidian_markdown','job_id':'SYNTH-1',
                     'schema_version':'1.0','vault_root':str(vault),'target_scope':'Synthetic/Version1',
                     'source_sha256':extraction['sha256'],'dry_run':True,'payload':{
                         'requirements_path':str(run/'requirements.json'),'clauses_path':str(run/'clauses.json'),
                         'verified_source_path':str(run/'verified_source.json'),'titles_registry_path':str(run/'registry.json'),
                         'article_path':frozen['article_path'],'staging_dir':str(run/'publish/staging')}}
            esa.write(run/'render-request.json',request)
            result=self.invoke('obsidian_render.py',run/'render-request.json')
            self.assertTrue(json.loads(result.stdout)['result']['ok'])
            note=run/'publish/staging/Synthetic/Version1/04_要求/REQ-SYNTH-1.md'
            self.assertIn('Fictional method at 5 kPa.',note.read_text(encoding='utf-8'))
            self.assertFalse(any(vault.iterdir()))
            self.invoke('verify_source.py',run/'clauses.json',run/'extraction.json',run/'checklist.json',
                '--review-record',run/'review.json','--article',article,'--inventory',run/'inventory.json',
                '--heading-registry',run/'registry.json','--out',run/'verified_source.json',expected=2)
            try:
                import yaml
            except ImportError:
                yaml=None
            if yaml:
                front=note.read_text(encoding='utf-8').split('---',2)[1]
                self.assertEqual(yaml.safe_load(front)['esa_review_status'],'draft')
                base=yaml.safe_load((run/'publish/staging/Synthetic/Version1/标准要求总览.base').read_text(encoding='utf-8'))
                self.assertTrue(any(v['name']=='已批准要求' for v in base['views']))

if __name__=='__main__':unittest.main()
