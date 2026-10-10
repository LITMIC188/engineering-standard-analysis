import copy
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import esa
import local_parser
import validate_translation

class RuntimeEdges(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def bundle(self):
        source=self.path/'source.md';source.write_text('4.1 Run at 5 kPa.\fTable continuation: 3 samples.',encoding='utf-8')
        clauses=esa.prepare(source,self.path/'prepare','DEMO','1','en')
        for i,b in enumerate(clauses['blocks']):b['clause_id']='4.'+str(i+1)
        annotations={'standard_id':'DEMO','edition':'1','source_complete':False,'requirements':[
            {'requirement_id':'R1','block_id':'B0001','quote':'Run at 5 kPa.','fields':{'method':{'quote':'Run at 5 kPa.'}},
            'applicability':'applicable','requirement_level':'mandatory','source_review':{}}]}
        return source,clauses,annotations
    def test_cross_page_spans_preserve_and_reject_changed_quote(self):
        source,clauses,_=self.bundle();blocks=clauses['blocks']
        spans=[{'source':b['source'],'quote':b['original_text']} for b in blocks]
        merged={**blocks[0],'kind':'table','spans':spans,'original_text':'\n'.join(s['quote'] for s in spans)}
        clauses['blocks']=[merged];esa.verify_clauses(clauses)
        clauses['blocks'][0]['spans'][1]['quote']='invented data'
        with self.assertRaisesRegex(ValueError,'untraceable'):esa.verify_clauses(clauses)
    def test_full_analysis_without_plan_and_source_complete_gate(self):
        _,clauses,ann=self.bundle();ann['source_complete']=True
        cp=self.path/'clauses.json';ap=self.path/'annotations.json';esa.write(cp,clauses);esa.write(ap,ann)
        out=self.path/'analysis';req=esa.full_analysis(cp,ap,out)
        self.assertFalse(req['source_complete']);self.assertTrue((out/'requirements-matrix.csv').is_file())
        self.assertFalse((out/'experiment_audit.json').exists())
    def test_local_corpus_records_checked_files_and_not_found_limit(self):
        _,clauses,_=self.bundle();cp=self.path/'clauses.json';esa.write(cp,clauses)
        out=self.path/'search.json';esa.corpus_query([cp],'not present',out)
        result=esa.read(out);self.assertEqual(result['matches'],[])
        self.assertEqual(len(result['coverage']),1);self.assertIn('不代表',result['limitation'])
    def test_compare_metadata_change_and_duplicate_ids_rejected(self):
        _,clauses,ann=self.bundle();old=esa.build_requirements(clauses,ann);new=copy.deepcopy(old)
        new['edition']='2';new['requirements'][0]['requirement_level']='recommended'
        a=self.path/'a.json';b=self.path/'b.json';esa.write(a,old);esa.write(b,new)
        output=self.path/'changes.csv';esa.compare(a,b,output)
        self.assertIn('changed_needs_review',output.read_text(encoding='utf-8-sig'))
        new['requirements'].append(new['requirements'][0]);esa.write(b,new)
        with self.assertRaisesRegex(ValueError,'duplicate'):esa.compare(a,b,self.path/'new.csv')
    def test_exclusion_without_review_never_counts_as_aligned(self):
        _,clauses,ann=self.bundle();r=ann['requirements'][0]
        r['applicability']='not_applicable';r['not_required']=[d for d in esa.DIMENSIONS if d!='method']
        r['source_review']={'reviewer':'UNIT TEST ONLY','reviewed_at':'2099-01-01','approval_evidence':'synthetic branch test'}
        req=esa.build_requirements(clauses,ann)
        plan={'plan_id':'P','tests':[{'test_id':'T','requirement_ids':['R1'],'quote':r['quote'],'fields':r['fields'],'source':{}}]}
        self.assertEqual(esa.audit(req,plan)['items'][0]['status'],'not_assessable')
    def test_docx_deleted_text_excluded_and_warning_prevents_completeness(self):
        source=self.path/'changes.docx'
        xml='<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Current 5 kPa</w:t></w:r><w:del><w:r><w:delText>Old 9 kPa</w:delText></w:r></w:del></w:p></w:body></w:document>'
        with zipfile.ZipFile(source,'w') as archive:archive.writestr('word/document.xml',xml)
        result=local_parser.extract_document(source)
        self.assertNotIn('9 kPa',result['pages'][0]['text']);self.assertFalse(result['complete'])
    def test_formula_change_flagged_and_spacing_equivalent(self):
        segment={'block_id':'B','clause_id':'1','source_lang':'en','target_lang':'zh-CN','pdf_page':1,
            'original_text':'F=m*a','translated_text':'F=m*b','human_reviewed':False,'protected_tokens':[]}
        bundle={'schema_version':'2.0','segments':[segment]}
        self.assertTrue(any('algebraic formula' in e for e in validate_translation.check(bundle,strict=True)))
        segment['translated_text']='F = m * a'
        self.assertFalse(any('algebraic formula' in e for e in validate_translation.check(bundle,strict=True)))

if __name__=='__main__':unittest.main()
