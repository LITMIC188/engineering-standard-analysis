import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import esa
import local_parser


class AuditEdgeCases(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.source=self.root/'standard.txt'; self.source.write_text('## 4 Test procedure\nRun at 5 kPa.\n[R1] Referenced method.\n',encoding='utf-8')
        clauses=esa.prepare(self.source,self.root/'prepared','DEMO','1','en')
        clauses['blocks'][0]['clause_id']='4.1'
        self.clauses=clauses
        self.annotations={'standard_id':'DEMO','edition':'1','requirements':[{
            'requirement_id':'R1','block_id':'B0001','quote':'Run at 5 kPa.',
            'fields':{'method':{'quote':'Run at 5 kPa.'}},'requirement_level':'mandatory',
            'applicability':'applicable','not_required':[d for d in esa.DIMENSIONS if d!='method'],
            'source_review':{'reviewer':'reviewer','reviewed_at':'2026-01-01','approval_evidence':'source-check'}}]}
        self.req=esa.build_requirements(clauses,self.annotations)
    def tearDown(self): self.tmp.cleanup()
    def test_informative_content_never_becomes_missing_obligation(self):
        self.annotations['requirements'][0]['requirement_level']='informative'
        req=esa.build_requirements(self.clauses,self.annotations)
        audit=esa.audit(req,{'plan_id':'P','tests':[]})['items'][0]
        self.assertEqual(audit['audit_obligation'],'informative')
        self.assertNotEqual(audit['status'],'missing')
    def test_two_unrelated_tests_cannot_combine_fields(self):
        self.annotations['requirements'][0]['fields']['conditions']={'quote':'Run at 5 kPa.'}
        self.annotations['requirements'][0]['not_required'].remove('conditions')
        req=esa.build_requirements(self.clauses,self.annotations)
        plan={'plan_id':'P','tests':[
            {'test_id':'T1','protocol_id':'P1','phase':'initial','sample_group':'A','requirement_ids':['R1'],'quote':'method','fields':{'method':{'quote':'Run at 5 kPa.'}},'source':{}},
            {'test_id':'T2','protocol_id':'P2','phase':'final','sample_group':'B','requirement_ids':['R1'],'quote':'condition','fields':{'conditions':{'quote':'Run at 5 kPa.'}},'source':{}}]}
        result=esa.audit(req,plan)['items'][0]
        self.assertEqual(result['status'],'not_assessable')
        self.assertEqual(result['test_ids'],['T1','T2'])
        self.assertEqual(result['evaluated_test_ids'],['T1'])
    def test_separate_complete_tests_are_evaluated_individually(self):
        tests=[{'test_id':tid,'requirement_ids':['R1'],'quote':'Run at 5 kPa.','fields':{'method':{'quote':'Run at 5 kPa.'}},'source':{}}
            for tid in ('T1','T2')]
        result=esa.audit(self.req,{'plan_id':'P','tests':tests})['items'][0]
        self.assertEqual(result['status'],'aligned')
        self.assertEqual(result['test_ids'],['T1','T2'])
        self.assertEqual(result['evaluated_test_ids'],['T1'])
    def test_combination_requires_reviewed_real_group_evidence(self):
        self.annotations['requirements'][0]['fields']['conditions']={'quote':'Run at 5 kPa.'}
        self.annotations['requirements'][0]['not_required'].remove('conditions')
        req=esa.build_requirements(self.clauses,self.annotations)
        ev={'reviewer':'reviewer','reviewed_at':'2026-01-01','approval_evidence':'record-1'}
        tests=[{'test_id':'T1','protocol_id':'P','combination_group':'g','phase':'initial','sample_group':'S',
            'requirement_ids':['R1'],'quote':'Run at 5 kPa.','fields':{'method':{'quote':'Run at 5 kPa.'}},'source':{},'combination_evidence':ev},
            {'test_id':'T2','protocol_id':'P','combination_group':'g','phase':'initial','sample_group':'S',
            'requirement_ids':['R1'],'quote':'Run at 5 kPa.','fields':{'conditions':{'quote':'Run at 5 kPa.'}},'source':{},'combination_evidence':ev}]
        result=esa.audit(req,{'plan_id':'P','tests':tests})['items'][0]
        self.assertEqual(result['status'],'aligned')
    def test_multi_span_sequence_is_checked(self):
        planfile=self.root/'plan.txt';planfile.write_text('first span\fsecond span',encoding='utf-8')
        doc=local_parser.extract_document(planfile)
        spans=[{'sequence':1,'locator':doc['pages'][0]['locator'],'quote':'first span'},
               {'sequence':2,'locator':doc['pages'][1]['locator'],'quote':'second span'}]
        annotations={'source_sha256':doc['sha256'],'plan_id':'P','plan_version':'1','tests':[
            {'test_id':'T','title':'multi span','source_spans':spans,'quote':'first span\nsecond span',
             'requirement_ids':['R1'],'fields':{'method':{'quote':'first span\nsecond span','source_spans':spans}}}]}
        built,_=esa.build_plan(planfile,annotations)
        self.assertEqual([s['sequence'] for s in built['tests'][0]['source_spans']],[1,2])
        annotations['tests'][0]['source_spans'][1]['sequence']=3
        with self.assertRaisesRegex(ValueError,'contiguous'):
            esa.build_plan(planfile,annotations)
    def test_global_coverage_requires_chapter_object_and_reference_closure(self):
        doc=esa.verify_clauses(self.clauses)
        review={'reviewer':'reviewer','reviewed_at':'2026-01-01','approval_evidence':'coverage-check'}
        req=esa.build_requirements(self.clauses,{**self.annotations,'source_inventory_review':{
            **review,'status':'source_checked','source_sha256':doc['sha256']}},doc)
        req['source_complete']=True
        self.assertFalse(esa.global_coverage({},req)['complete'])
        req['coverage']={'required_sections':['4'],'modeled_sections':['4'],'chapter_review':review,'normative_annexes':[],'modeled_annexes':[],
            'annex_review':review,'tables':{'expected_ids':[],'modeled_ids':[],'review':review},
            'figures':{'expected_ids':[],'modeled_ids':[],'review':review}}
        reference=self.root/'reference.txt';reference.write_text('Reference body',encoding='utf-8')
        req['reference_closure']={'references':[{'reference_id':'R1','file':str(reference),'sha256':esa.digest(reference),
            'status':'resolved','resolution_review':review}],'review':review}
        self.assertTrue(esa.global_coverage({},req)['complete'])
        req['coverage']['normative_annexes']=['A']
        result=esa.global_coverage({},req)
        self.assertFalse(result['complete']);self.assertEqual(result['missing_normative_annexes'],['A'])
    def test_requirement_source_spans_are_canonical_and_claim_checked(self):
        row=self.annotations['requirements'][0]
        src=self.req['requirements'][0]['source_spans'][0]
        self.assertEqual(src['quote'],row['quote']);self.assertEqual(src['source']['sha256'],self.req['requirements'][0]['source']['sha256'])
        row['source_spans']=[{'sequence':1,'locator':src['locator'],'quote':src['quote'],
            'source':{**src['source'],'file':'forged.txt'}}]
        with self.assertRaisesRegex(ValueError,'provenance mismatch'):
            esa.build_requirements(self.clauses,self.annotations)
    def test_reference_closure_checks_real_file_hash(self):
        ref=self.root/'referenced.txt';ref.write_text('Referenced source',encoding='utf-8')
        review={'reviewer':'reviewer','reviewed_at':'2026-01-01','approval_evidence':'reference-check'}
        requirements={'requirements':[],'source_complete':False,'coverage':{},'source_inventory':{
            'validated':True,'reference_ids':['R1'],'sections':[],'normative_annex_ids':[],'table_ids':[],'figure_ids':[],'sha256':'test'},
            'source_inventory_review':{**review,'status':'source_checked','source_sha256':'test'},'reference_closure':{
            'references':[{'reference_id':'R1','file':str(ref),'sha256':esa.digest(ref),'status':'resolved','resolution_review':review}], 'review':review}}
        self.assertTrue(esa.global_coverage({},requirements)['references_complete'])
        ref.write_text('Changed source',encoding='utf-8')
        self.assertFalse(esa.global_coverage({},requirements)['references_complete'])
    def test_canonical_requirement_spans_remain_exportable(self):
        row=self.annotations['requirements'][0]
        row['review_status']='approved';row['review_record']={'reviewer':'reviewer','reviewed_at':'2026-01-01','approval_evidence':'approval'}
        req=esa.build_requirements(self.clauses,self.annotations)
        self.assertEqual(esa.export_study(req,self.root/'study'),1)
    def test_informative_marker_cannot_override_mandatory_or_unverified_source(self):
        self.annotations['requirements'][0]['normative_nature']='informative'
        self.annotations['requirements'][0]['requirement_level']='mandatory'
        req=esa.build_requirements(self.clauses,self.annotations)
        self.assertEqual(req['requirements'][0]['audit_obligation'],'mandatory')
        self.annotations['requirements'][0]['requirement_level']='informative'
        self.annotations['requirements'][0]['source_review']={}
        req=esa.build_requirements(esa.read(self.root/'prepared'/'clauses.json'),self.annotations)
        self.assertEqual(req['requirements'][0]['audit_obligation'],'unknown')
    def test_explicit_renumbering_stays_unverified(self):
        old={'standard_id':'S','edition':'1','requirements':[{'requirement_id':'4.1','quote':'old'}]}
        new={'standard_id':'S','edition':'2','requirements':[{'requirement_id':'5.1','quote':'new'}]}
        oldfile=self.root/'old.json';newfile=self.root/'new.json';mapfile=self.root/'map.json';out=self.root/'cmp.csv'
        esa.write(oldfile,old);esa.write(newfile,new);esa.write(mapfile,{'mappings':[{
            'old_requirement_id':'4.1','new_requirement_id':'5.1','mapping_type':'renumbering',
            'review_record':{'reviewer':'reviewer','reviewed_at':'2026-01-01','approval_evidence':'mapping-check'}}]})
        esa.compare(oldfile,newfile,out,mapfile)
        text=out.read_text(encoding='utf-8-sig')
        self.assertIn('renumbered_needs_review',text)
        self.assertIn('False',text)

if __name__=='__main__': unittest.main()
