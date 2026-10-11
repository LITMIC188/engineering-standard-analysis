import hashlib, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'scripts'
sys.path.insert(0,str(SCRIPTS))
import local_parser, verify_source, reconstruct_source, render_full_articles, validate_translation
import obsidian_render, obsidian_verify, obsidian_publish

SYNTHETIC_REVIEW={'reviewer':'SYNTHETIC FIXTURE ONLY','reviewed_at':'2099-01-01','approval_evidence':'synthetic marker; no human review occurred'}
KINDS=('pages','chapters','normative_annexes','tables','figures','references')

def canon_obj(o): return json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')

def save(p,obj): p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

class IndependentPublishAudit(unittest.TestCase):
    def setUp(self):
        (ROOT/'run'/'forward-publish').mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'run'/'forward-publish')
        self.base=Path(self.tmp.name)
        self.vault=self.base/'vault'; self.vault.mkdir()
        self.stage=self.base/'staging'
        self.source=self.base/'synthetic.md'
        self.source.write_bytes(b'# 4.1 Thermal test\nSpecimen must use Method Q at 10 kPa.\n## Annex A (normative)\nAnnex A shall record the result.\n')
        self.ext=local_parser.extract_document(self.source)
        self.h=self.ext['sha256']; loc=self.ext['pages'][0]['locator']; source_ref={'file':str(self.source),'sha256':self.h,'pdf_page':None,'page_kind':'text','locator':loc}
        self.clauses={'schema_version':'2.0','standard_id':'SYN-9','edition':'1','source':{'file':str(self.source),'sha256':self.h},'blocks':[
          {'block_id':'B1','clause_id':'4.1','kind':'clause','source_lang':'en','original_text':'# 4.1 Thermal test\nSpecimen must use Method Q at 10 kPa.','source':dict(source_ref)},
          {'block_id':'B2','clause_id':'A','kind':'annex','source_lang':'en','original_text':'## Annex A (normative)\nAnnex A shall record the result.','source':dict(source_ref)}]}
        self.article=self.base/'article.md'; self.article.write_bytes(verify_source.canonical_source_article(self.clauses))
        self.inventory={'pages':[loc],'chapters':['4.1'],'normative_annexes':['Annex A'],'tables':[],'figures':[],'references':[]}
        self.checklist=[{'inventory_kind':k,'inventory_id':item,'status':'complete'} for k,items in self.inventory.items() for item in items]
        self.registry={'schema_version':'1.0','source_sha256':self.h,'headings':[{'heading_id':'H1','block_id':'B1','clause_id':'4.1','title':'# 4.1 Thermal test','level':1,'order':1,'source':dict(source_ref)}]}
        self.verified=verify_source.verify_source(self.clauses,self.ext,self.checklist,SYNTHETIC_REVIEW,self.article,
          expected_inventory=self.inventory,heading_registry=self.registry)
        self.assertTrue(self.verified['source_complete'],repr((self.ext['pages'],self.verified['blockers'])))
        self.clauses_path=self.base/'clauses.json'; save(self.clauses_path,self.clauses)
        self.registry_path=self.base/'registry.json'; save(self.registry_path,self.registry)
        self.verified.update({'heading_registry_path':str(self.registry_path),'heading_registry_sha256':hashlib.sha256(canon_obj(self.registry)).hexdigest()})
        self.verified_path=self.base/'verified.json'; save(self.verified_path,self.verified)
        self.requirements={'schema_version':'2.0','standard_id':'SYN-9','edition':'1','source_complete':True,'requirements':[{
          'requirement_id':'R1','block_id':'B1','clause_id':'4.1','summary':'Method Q test','quote':'Specimen must use Method Q at 10 kPa.',
          'applicability':'applicable','requirement_level':'mandatory','source_verified':True,'source_review':SYNTHETIC_REVIEW,
          'review_status':'draft','source':{**source_ref,'standard_id':'SYN-9','edition':'1'}}]}
        self.req_path=self.base/'requirements.json'; save(self.req_path,self.requirements)
        self.request={'interface_id':'B-接口-02','interface_name':'render_obsidian_markdown','job_id':'SYN-JOB','schema_version':'1.0',
          'vault_root':str(self.vault),'target_scope':'SYN-9/draft/SYN-JOB','source_sha256':self.h,'dry_run':True,
          'payload':{'verified_source_path':str(self.verified_path),'clauses_path':str(self.clauses_path),'requirements_path':str(self.req_path),
            'titles_registry_path':str(self.registry_path),'article_path':str(self.article),'staging_dir':str(self.stage)}}
    def tearDown(self): self.tmp.cleanup()
    def cli(self,script,args): return subprocess.run([sys.executable,str(SCRIPTS/script),*map(str,args)],capture_output=True,text=True,encoding='utf-8',errors='replace')
    def test_reconstruct_and_verify_source_cli_with_markdown(self):
        extraction_path=self.base/'extraction.json'; save(extraction_path,self.ext)
        out=self.base/'reconstructed'
        cp=self.cli('reconstruct_source.py',[extraction_path,'--clauses',self.clauses_path,'--out-dir',out]); self.assertEqual(cp.returncode,0,cp.stderr)
        article=out/'02_Original_Reconstructed.md'; self.assertTrue(article.exists())
        self.assertIn('Annex A (normative)',article.read_text(encoding='utf-8'))
        standalone=self.base/'reconstructed-without-clauses'
        cp=self.cli('reconstruct_source.py',[extraction_path,'--out-dir',standalone]); self.assertEqual(cp.returncode,0,cp.stderr)
        self.assertTrue((standalone/'02_Original_Reconstructed.md').is_file())
        save(self.base/'checklist.json',self.checklist); save(self.base/'review.json',SYNTHETIC_REVIEW); save(self.base/'inventory.json',self.inventory)
        cp=self.cli('verify_source.py',[self.clauses_path,extraction_path,self.base/'checklist.json','--review-record',self.base/'review.json','--article',self.article,'--inventory',self.base/'inventory.json','--heading-registry',self.registry_path,'--out',self.base/'verified-cli.json'])
        self.assertEqual(cp.returncode,0,cp.stdout+cp.stderr)
        self.assertEqual(json.loads((self.base/'verified-cli.json').read_text(encoding='utf-8'))['review_status'],'source_checked')
        article_out=self.base/'rendered-articles'
        cp=self.cli('render_full_articles.py',[self.clauses_path,'--verified-source',self.base/'verified-cli.json','--out-dir',article_out])
        self.assertEqual(cp.returncode,0,cp.stdout+cp.stderr)
        self.assertIn('DRAFT',(article_out/'04_Translation_Complete.md').read_text(encoding='utf-8'))
    def test_pdf_extraction_text_cannot_be_forged(self):
        from reportlab.pdfgen import canvas
        pdf=self.base/'source.pdf'; c=canvas.Canvas(str(pdf),pagesize=(400,400));c.drawString(40,350,'4.1 Method Q at 10 kPa');c.showPage();c.drawString(40,350,'Annex A (normative)');c.save()
        ext=local_parser.extract_document(pdf); h=ext['sha256']; ext['pages'][0]['text']='4.1 Method Q at 999 kPa';
        loc=ext['pages'][0]['locator']; clause={'schema_version':'2.0','standard_id':'PDF-X','edition':'1','source':{'file':str(pdf),'sha256':h},'blocks':[{'block_id':'B1','clause_id':'4.1','source_lang':'en','original_text':'4.1 Method Q at 999 kPa','source':{'file':str(pdf),'sha256':h,'pdf_page':1,'page_kind':'pdf','locator':loc}}]}
        article=self.base/'pdf-article.md'; article.write_bytes(verify_source.canonical_source_article(clause))
        with self.assertRaisesRegex(ValueError,'raw_ocr artifact'):
            verify_source.verify_source(clause,ext,[{'id':'p1','status':'complete'}],SYNTHETIC_REVIEW,article,
              expected_inventory={k:[] for k in KINDS},heading_registry={'source_sha256':h,'headings':[]})
    def test_empty_inventory_and_unregistered_annex_block_freeze(self):
        noinv={k:[] for k in KINDS}
        result=verify_source.verify_source(self.clauses,self.ext,self.checklist,SYNTHETIC_REVIEW,self.article,
          expected_inventory=noinv,heading_registry=self.registry)
        self.assertFalse(result['source_complete']); self.assertTrue(result['blockers'])
    def test_omitting_same_page_annex_block_blocks_freeze(self):
        omitted={**self.clauses,'blocks':self.clauses['blocks'][:1]}; article=self.base/'omitted.md';article.write_bytes(verify_source.canonical_source_article(omitted))
        result=verify_source.verify_source(omitted,self.ext,self.checklist,SYNTHETIC_REVIEW,article,
          expected_inventory=self.inventory,heading_registry={'source_sha256':self.h,'headings':[]})
        self.assertFalse(result['source_complete']); self.assertTrue(any('unrepresented' in x['reason'] for x in result['blockers']))
    def test_omitting_entire_extracted_page_blocks_freeze(self):
        from reportlab.pdfgen import canvas
        pdf=self.base/'two-pages.pdf';c=canvas.Canvas(str(pdf),pagesize=(400,400));c.drawString(30,350,'4.1 Method Q');c.showPage();c.drawString(30,350,'Annex A (normative)');c.save()
        ext=local_parser.extract_document(pdf);h=ext['sha256'];p=ext['pages'][0];ref={'file':str(pdf),'sha256':h,'pdf_page':1,'page_kind':'pdf','locator':p['locator']}
        clauses={'schema_version':'2.0','standard_id':'PDF-X','edition':'1','source':{'file':str(pdf),'sha256':h},'blocks':[{'block_id':'B1','clause_id':'4.1','kind':'clause','source_lang':'en','original_text':p['text'],'source':ref}]}
        article=self.base/'one-page.md';article.write_bytes(verify_source.canonical_source_article(clauses))
        inv={'pages':[x['locator'] for x in ext['pages']],'chapters':[],'normative_annexes':['Annex A'],'tables':[],'figures':[],'references':[]}
        checklist=[{'inventory_kind':k,'inventory_id':i,'status':'complete'} for k,v in inv.items() for i in v]
        r=verify_source.verify_source(clauses,ext,checklist,SYNTHETIC_REVIEW,article,expected_inventory=inv,heading_registry={'source_sha256':h,'headings':[]})
        self.assertFalse(r['source_complete']); self.assertTrue(any('PDF page 2' in str(x) or 'PDF page 2' in str(x.get('id')) for x in r['blockers']))
    def test_b02_dry_run_cli_stages_outside_vault_and_never_writes_vault(self):
        reqfile=self.base/'b02.json';save(reqfile,self.request)
        cp=self.cli('obsidian_render.py',[reqfile]);self.assertEqual(cp.returncode,0,cp.stdout+cp.stderr)
        result=json.loads(cp.stdout)['result'];self.assertTrue(result['ok']);self.assertTrue(result['details']['staging_written']);self.assertFalse(result['details']['vault_written'])
        self.assertTrue((self.stage/'.esa_staging_manifest.json').is_file());self.assertEqual(list(self.vault.iterdir()),[])
        self.assertEqual(list(self.vault.iterdir()),[])
        vr={"interface_id":"B-接口-04","interface_name":"verify_obsidian_publish","job_id":"SYN-JOB","schema_version":"1.0","vault_root":str(self.vault),"target_scope":self.request['target_scope'],"source_sha256":self.h,"dry_run":True,"payload":{"staging_dir":str(self.stage)}}
        checked=obsidian_verify.verify(vr);self.assertFalse(checked['result']['ok']);self.assertEqual(checked['result']['status'],'pending_cli_validation');self.assertTrue(checked['result']['details']['local_link_check'])
    def test_stage_tamper_production_scope_and_false_approved_reject(self):
        self.assertRaises(obsidian_render.AdapterError,obsidian_render.safe_relative,'../../outside')
        bad={**self.requirements,'requirements':[dict(self.requirements['requirements'][0],review_status='approved')]};save(self.req_path,bad)
        with self.assertRaises(obsidian_render.AdapterError):obsidian_render.render(self.request)
        save(self.req_path,self.requirements);obsidian_render.render(self.request)
        note=self.stage/'SYN-9/draft/SYN-JOB/04_要求/R1.md';note.write_text(note.read_text(encoding='utf-8')+'\nTampered\n',encoding='utf-8')
        prod={**self.request,'dry_run':False,'target_scope':'SYN-9/production','payload':{**self.request['payload'],'allow_write':True,'publish_policy':{'require_cli_validation':False}}}
        env={'OBSIDIAN_VAULT_ROOT':str(self.vault)}
        with patch.dict(os.environ,env):
            with self.assertRaises(obsidian_publish.AdapterError) as cm:obsidian_publish.publish(prod)
        self.assertEqual(cm.exception.code,'SOURCE_NOT_VERIFIED');self.assertEqual(list(self.vault.iterdir()),[])
    def test_unreviewed_numeric_and_missing_translations_stay_draft_or_fail(self):
        segs=[{'block_id':b['block_id'],'original_text':b['original_text'],'source':b['source'],'translated_text':'Translated 999 kPa'} for b in self.clauses['blocks']]
        full=render_full_articles.render(self.clauses,{'segments':segs},self.verified)
        self.assertEqual(full['translation_status'],'draft');self.assertIn('DRAFT',full['chinese'])
        bad={'schema_version':'2.0','segments':[{'block_id':'B1','clause_id':'4.1','source_lang':'en','target_lang':'zh','original_text':'10 kPa','translated_text':'999 kPa','source':{'page_kind':'text','locator':'text document'},'pdf_page':None,'protected_tokens':[],'human_reviewed':True,'review_record':SYNTHETIC_REVIEW,'source_quote':'10 kPa'}]}
        self.assertTrue(any('numeric tokens mismatch' in x for x in validate_translation.validate_bundle(bad)['errors']))
        with self.assertRaisesRegex(ValueError,'IDs missing'):
            render_full_articles.render(self.clauses,{'segments':segs[:1]},self.verified)
    def test_numeric_mismatch_with_human_approved_flag_stays_draft(self):
        segments=[]
        for b in self.clauses['blocks']:
            text='Specimen must use Method Q at 999 kPa.' if b['block_id']=='B1' else 'Annex A shall record the result.'
            segments.append({'block_id':b['block_id'],'clause_id':b['clause_id'],'source_lang':'en','target_lang':'zh',
              'original_text':b['original_text'],'translated_text':text,'source':b['source'],'pdf_page':None,
              'protected_tokens':[],'human_reviewed':True,'review_record':SYNTHETIC_REVIEW,'source_quote':b['original_text']})
        translations={'schema_version':'2.0','segments':segments}
        strict=validate_translation.validate_bundle(translations)
        self.assertTrue(any('numeric tokens mismatch' in e for e in strict['errors']))
        full=render_full_articles.render(self.clauses,translations,self.verified)
        self.assertEqual(full['translation_status'],'draft')
        self.assertTrue(any('numeric tokens mismatch' in error for row in full['translation_validation'].values() for error in row['errors']))
    def test_traversal_wikilink_and_markdown_image_fail_render(self):
        altered={**self.clauses,'blocks':[dict(x) for x in self.clauses['blocks']]};altered['blocks'][0]=dict(altered['blocks'][0],original_text=altered['blocks'][0]['original_text']+'\n[[../../escape]] ![bad](../../outside.png)')
        article=self.base/'badlinks.md';article.write_bytes(verify_source.canonical_source_article(altered));save(self.clauses_path,altered)
        verified=dict(self.verified);verified['clauses_sha256']=hashlib.sha256(canon_obj(altered)).hexdigest();verified['article_sha256']=hashlib.sha256(article.read_bytes()).hexdigest();verified['article_path']=str(article);save(self.verified_path,verified)
        with self.assertRaises(obsidian_render.AdapterError):obsidian_render.render(self.request)
    def test_same_basename_different_directories_uses_explicit_attachment_map(self):
        a=self.base/'a'/'plot.png';b=self.base/'b'/'plot.png';a.parent.mkdir();b.parent.mkdir();a.write_bytes(b'plot A');b.write_bytes(b'plot B')
        clauses={**self.clauses,'blocks':[dict(x) for x in self.clauses['blocks']]}
        clauses['blocks'][0]=dict(clauses['blocks'][0],original_text=clauses['blocks'][0]['original_text']+'\n![A]('+str(a)+')\n![B]('+str(b)+')')
        article=self.base/'images-article.md';article.write_bytes(verify_source.canonical_source_article(clauses));save(self.clauses_path,clauses)
        verified=dict(self.verified);verified['clauses_sha256']=hashlib.sha256(canon_obj(clauses)).hexdigest();verified['article_sha256']=hashlib.sha256(article.read_bytes()).hexdigest();verified['article_path']=str(article);save(self.verified_path,verified)
        self.request['payload']['article_path']=str(article);self.request['payload']['attachments']=[{'source_path':str(a),'target_path':'assets/a/plot.png','sha256':hashlib.sha256(a.read_bytes()).hexdigest()},{'source_path':str(b),'target_path':'assets/b/plot.png','sha256':hashlib.sha256(b.read_bytes()).hexdigest()}]
        result=obsidian_render.render(self.request);self.assertTrue(result['result']['ok'])
        md=(self.stage/'SYN-9/draft/SYN-JOB/01_原文.md').read_text(encoding='utf-8');self.assertIn('![[assets/a/plot.png]]',md);self.assertIn('![[assets/b/plot.png]]',md)
        self.assertEqual((self.stage/'SYN-9/draft/SYN-JOB/assets/a/plot.png').read_bytes(),b'plot A');self.assertEqual((self.stage/'SYN-9/draft/SYN-JOB/assets/b/plot.png').read_bytes(),b'plot B')
    def test_missing_cli_is_pending_and_never_writes_vault(self):
        approved={**self.requirements,'requirements':[dict(self.requirements['requirements'][0],review_status='approved',review_record=SYNTHETIC_REVIEW)]};save(self.req_path,approved);obsidian_render.render(self.request)
        req={**self.request,'dry_run':False,'payload':{**self.request['payload'],'allow_write':True,'obsidian_executable':'esa-nonexistent-obsidian-cli','vault_name':'Synthetic','publish_policy':{'require_cli_validation':True}}}
        with patch.dict(os.environ,{'OBSIDIAN_VAULT_ROOT':str(self.vault)}):
            with self.assertRaises(obsidian_publish.AdapterError) as cm:obsidian_publish.publish(req)
        self.assertEqual(cm.exception.status,'pending_cli_validation');self.assertEqual(list(self.vault.iterdir()),[])
    def test_rollback_does_not_overwrite_external_concurrent_edit(self):
        approved={**self.requirements,'requirements':[dict(self.requirements['requirements'][0],review_status='approved',review_record=SYNTHETIC_REVIEW)]};save(self.req_path,approved);obsidian_render.render(self.request)
        env={'OBSIDIAN_VAULT_ROOT':str(self.vault)};req={**self.request,'dry_run':False,'payload':{**self.request['payload'],'allow_write':True,'publish_policy':{'require_cli_validation':True},'obsidian_executable':'fake','vault_name':'Synthetic','runtime_dir':str(self.base/'runtime')}}
        external=self.vault/'SYN-9/draft/SYN-JOB/01_原文.md'
        def fake_run(args,**kwargs):
            if args[-1]=='help':return type('R',(),{'returncode':0,'stdout':'read vault info','stderr':''})()
            if args[-1]=='info':return type('R',(),{'returncode':0,'stdout':str(self.vault),'stderr':''})()
            external.write_text('external concurrent edit',encoding='utf-8');return type('R',(),{'returncode':0,'stdout':b'bad readback','stderr':b''})()
        with patch.dict(os.environ,env),patch.object(obsidian_publish.subprocess,'run',side_effect=fake_run):
            with self.assertRaises(obsidian_publish.AdapterError):obsidian_publish.publish(req)
        self.assertEqual(external.read_text(encoding='utf-8'),'external concurrent edit')
    def test_midfile_fsync_failure_rolls_back_created_file(self):
        approved={**self.requirements,'requirements':[dict(self.requirements['requirements'][0],review_status='approved',review_record=SYNTHETIC_REVIEW)]};save(self.req_path,approved);obsidian_render.render(self.request)
        env={'OBSIDIAN_VAULT_ROOT':str(self.vault)};req={**self.request,'dry_run':False,'payload':{**self.request['payload'],'allow_write':True,'publish_policy':{'require_cli_validation':False},'runtime_dir':str(self.base/'runtime')}}
        with patch.dict(os.environ,env),patch.object(obsidian_publish.os,'fsync',side_effect=OSError('synthetic fsync failure')):
            with self.assertRaises(obsidian_publish.AdapterError):obsidian_publish.publish(req)
        partial=list(self.vault.rglob('*'))
        self.assertFalse(any(x.is_file() for x in partial))

if __name__=='__main__':unittest.main(verbosity=2)
