import json, subprocess, sys, tempfile, zipfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import esa, local_parser, migrate_schema_v2, validate_translation, validate_run, json_io

REVIEW = {'reviewer':'SYNTHETIC FIXTURE ONLY','reviewed_at':'2099-01-01','approval_evidence':'synthetic marker; no human review occurred'}

class IndependentAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.standard = self.d/'standard.md'
        self.standard.write_text('''# Synthetic Standard Z\n## 4 Test procedure\nEach specimen shall be tested at 20 °C. Use Method Q.\n## Appendix A (normative)\nRecord insulation resistance at 500 V.\n## Appendix B (informative)\nExample only.\n## References\n[R1] Synthetic procedure X, unresolved.\n''', encoding='utf-8')
        self.clauses = esa.prepare(self.standard, self.d/'prepared', 'SYN-Z','1','en')
        self.block = self.clauses['blocks'][0]
    def tearDown(self): self.tmp.cleanup()
    def requirements(self, level='mandatory', extra=None):
        self.block['clause_id']='4'
        self.block.pop('needs_clause_review',None)
        quote='Each specimen shall be tested at 20 °C. Use Method Q.'
        row={'requirement_id':'R-4','block_id':self.block['block_id'],'quote':quote,
             'fields':{'method':{'quote':'Use Method Q.'},'conditions':{'quote':'20 °C'}},
             'requirement_level':level,'applicability':'applicable',
             'not_required':[x for x in esa.DIMENSIONS if x not in ('method','conditions')],
             'source_review':REVIEW}
        if extra: row.update(extra)
        document=esa.verify_clauses(self.clauses)
        inventory_review={**REVIEW,'status':'source_checked','source_sha256':document['sha256']}
        return esa.build_requirements(self.clauses, {'standard_id':'SYN-Z','edition':'1','requirements':[row],
          'source_inventory_review':inventory_review},document)
    def test_distinct_phase_or_sample_records_do_not_supply_joint_fields(self):
        req=self.requirements(); tests=[]
        for tid,phase,sample,field,quote in [('T1','initial','A','method','Use Method Q.'),('T2','final','B','conditions','20 °C')]:
            tests.append({'test_id':tid,'phase':phase,'sample_group':sample,'protocol_id':tid,'combination_group':tid,
              'requirement_ids':['R-4'],'quote':quote,'fields':{field:{'quote':quote}},'source':{}})
        result=esa.audit(req,{'plan_id':'P','tests':tests})['items'][0]
        self.assertEqual(result['status'],'not_assessable')
        self.assertEqual(result['test_ids'],['T1','T2'])
        self.assertEqual(result['evaluated_test_ids'],['T1'])
    def test_informative_requirement_is_not_reported_missing(self):
        result=esa.audit(self.requirements('informative'), {'plan_id':'P','tests':[]})['items'][0]
        self.assertEqual(result['status'],'not_assessable'); self.assertEqual(result['audit_obligation'],'informative')
    def test_unresolved_reference_chain_blocks_alignment(self):
        req=self.requirements(extra={'reference_chain':['R1: unresolved']})
        plan={'plan_id':'P','tests':[{'test_id':'T','requirement_ids':['R-4'],'quote':'Each specimen shall be tested at 20 °C. Use Method Q.',
          'fields':{'method':{'quote':'Use Method Q.'},'conditions':{'quote':'20 °C'}},'source':{}}]}
        self.assertEqual(esa.audit(req,plan)['items'][0]['status'],'not_assessable')
    def test_omitted_appendix_makes_global_coverage_incomplete(self):
        req=self.requirements(); req.update(source_complete=True,coverage={'required_sections':['4','A','B'],'modeled_sections':['4','B'],'chapter_review':REVIEW,
          'tables':{'complete':True,'review':REVIEW},'figures':{'complete':True,'review':REVIEW}},
          reference_closure={'references':[],'review':REVIEW})
        self.assertFalse(esa.global_coverage({},req)['complete'])
        self.assertEqual(esa.global_coverage({},req)['missing_sections'],['A'])
    def test_inventory_cannot_omit_real_appendix_and_report_complete(self):
        # The actual synthetic source above contains normative Appendix A. The inventory omits it.
        req=self.requirements(); req.update(source_complete=True,coverage={
          'required_sections':['4'],'modeled_sections':['4'],'chapter_review':REVIEW,
          'normative_annexes':[],'modeled_annexes':[],'annex_review':REVIEW,
          'tables':{'expected_ids':[],'modeled_ids':[],'review':REVIEW},
          'figures':{'expected_ids':[],'modeled_ids':[],'review':REVIEW}},
          reference_closure={'references':[],'review':REVIEW})
        result=esa.global_coverage({},req)
        self.assertFalse(result['complete'])
        self.assertEqual(result['missing_normative_annexes'],['A'])
    def test_source_appendix_omitted_from_clauses_is_detected_from_all_source_pages(self):
        # Keep source identity/hash intact while simulating a clause model that omitted Appendix A.
        original=self.block['original_text']
        self.block['original_text']=original.split('## Appendix A')[0].rstrip()
        document=esa.verify_clauses(self.clauses)
        annotations={'standard_id':'SYN-Z','edition':'1','source_complete':True,
          'coverage_review':REVIEW,'source_inventory_review':{**REVIEW,'status':'source_checked','source_sha256':document['sha256']},
          'requirements':[],'coverage':{'required_sections':['4'],'modeled_sections':['4'],'chapter_review':REVIEW,
            'normative_annexes':['A'],'modeled_annexes':[],'annex_review':REVIEW,
            'tables':{'expected_ids':[],'modeled_ids':[],'review':REVIEW},
            'figures':{'expected_ids':[],'modeled_ids':[],'review':REVIEW}},
          'reference_closure':{'references':[],'review':REVIEW}}
        req=esa.build_requirements(self.clauses,annotations,document)
        req['source_complete']=False
        result=esa.global_coverage(self.clauses,req)
        self.assertIn('A',req['source_inventory']['normative_annex_ids'])
        self.assertNotIn('A',req['modeled_inventory']['normative_annex_ids'])
        self.assertFalse(req['source_page_coverage']['complete'])
        self.assertFalse(result['complete'])
    def test_forged_source_span_locator_is_rejected(self):
        row={'requirement_id':'R','block_id':self.block['block_id'],'quote':'Each specimen shall be tested at 20 °C.',
          'fields':{'method':{'quote':'Each specimen shall be tested at 20 °C.'}},'requirement_level':'mandatory','applicability':'applicable',
          'not_required':[x for x in esa.DIMENSIONS if x!='method'],'source_spans':[{'sequence':1,'locator':'forged paragraph 999','quote':'Each specimen shall be tested at 20 °C.'}]}
        with self.assertRaisesRegex(ValueError,'untraceable source span'):
            esa.build_requirements(self.clauses,{'standard_id':'SYN-Z','edition':'1','requirements':[row]})
    def test_multisection_docx_plan_extraction(self):
        planfile=self.d/'plan.docx'
        xml='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>1. Prepare specimen.</w:t></w:r></w:p><w:p><w:r><w:t>2. Apply Method Q at 20 °C.</w:t></w:r></w:p><w:p><w:r><w:t>3. Repeat on second specimen.</w:t></w:r></w:p><w:sectPr/></w:body></w:document>'''
        with zipfile.ZipFile(planfile,'w') as zf: zf.writestr('word/document.xml',xml)
        doc=local_parser.extract_document(planfile)
        self.assertEqual(len(doc['pages']),3)
        spans=[{'sequence':1,'locator':doc['pages'][1]['locator'],'quote':'2. Apply Method Q at 20 °C.'},
               {'sequence':2,'locator':doc['pages'][2]['locator'],'quote':'3. Repeat on second specimen.'}]
        built,_=esa.build_plan(planfile,{'source_sha256':doc['sha256'],'plan_id':'P','plan_version':'1','tests':[
          {'test_id':'T','title':'multi paragraph','source_spans':spans,'quote':'2. Apply Method Q at 20 °C.\n3. Repeat on second specimen.',
           'requirement_ids':['R-4'],'fields':{'method':{'quote':'2. Apply Method Q at 20 °C.'}}}]})
        self.assertEqual(len(built['tests'][0]['source_spans']),2)
    def test_translation_guards_negation_japanese_and_si_case_but_semantics_warn(self):
        def seg(i,a,b): return {'block_id':str(i),'clause_id':'4','source_lang':'en','target_lang':'ja','original_text':a,'translated_text':b,
          'source':{'page_kind':'text','locator':'text document'},'pdf_page':None,'protected_tokens':[],'human_reviewed':True,'review_record':REVIEW,'source_quote':a}
        bundle={'schema_version':'2.0','segments':[
          seg(1,'The valve shall not open at 20 kPa.','弁は20 kPaで開かなければならない。'),
          seg(2,'Pressure is 5 MPa.','圧力は5 mPa。'),
          seg(3,'Example prose: A is a variable.','例文：Aは変数です。'),
          seg(4,'流体を使用してはならない。','流体を使用してもよい。')]}
        out=validate_translation.validate_bundle(bundle)
        self.assertTrue(any('normative-force/negation cue' in w for w in out['warnings']))
        self.assertTrue(any('unit tokens mismatch' in e for e in out['errors']))
        self.assertTrue(any('numeric tokens mismatch' not in e for e in out['errors']))
        # Structural validation deliberately cannot detect the Japanese modal reversal.
        self.assertFalse(any('segment[4]' in e for e in out['errors']))
    def test_duplicate_json_keys_and_legacy_approval_migration(self):
        with self.assertRaisesRegex(ValueError,'duplicate JSON key'):
            json_io.loads('{"requirement_id":"R1","requirement_id":"R2"}')
        duplicate=self.d/'duplicate.json'; duplicate.write_text('{"schema_version":"2.0","segments":[],"segments":[]}',encoding='utf-8')
        proc=subprocess.run([sys.executable,str(ROOT/'scripts'/'validate_translation.py'),str(duplicate),'--strict'],capture_output=True,text=True)
        self.assertEqual(proc.returncode,2); self.assertIn('duplicate JSON key',proc.stdout)
        migrated,log=migrate_schema_v2.migrate({'schema_version':'2.0','requirements':[{'requirement_id':'R','review_status':'approved','source_verified':True}]},'requirements')
        self.assertEqual(migrated['requirements'][0]['review_status'],'source_checked')
        self.assertFalse(log['approval_granted']); self.assertEqual(log['review_queue'][0]['requirement_id'],'R')
    def test_explicit_renumber_mapping_never_claims_equivalence(self):
        old=self.d/'old.json'; new=self.d/'new.json'; mapping=self.d/'map.json'; out=self.d/'compare.csv'
        esa.write(old,{'standard_id':'S','edition':'1','requirements':[{'requirement_id':'4.1','quote':'old'}]})
        esa.write(new,{'standard_id':'S','edition':'2','requirements':[{'requirement_id':'5.1','quote':'new'}]})
        esa.write(mapping,{'mappings':[{'old_requirement_id':'4.1','new_requirement_id':'5.1','mapping_type':'renumbering','review_record':REVIEW}]})
        esa.compare(old,new,out,mapping)
        text=out.read_text(encoding='utf-8-sig'); self.assertIn('renumbered_needs_review',text); self.assertIn('False',text)
        unmapped=self.d/'compare-unmapped.csv'; esa.compare(old,new,unmapped)
        text=unmapped.read_text(encoding='utf-8-sig'); self.assertIn('removed',text); self.assertIn('added',text)

if __name__=='__main__': unittest.main(verbosity=2)
