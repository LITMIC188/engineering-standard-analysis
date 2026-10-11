import hashlib, json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'scripts'))
from ocr_space_restore import restore
from heading_registry import build_registry
from reconstruct_source import reconstruct
from verify_source import verify_source
from translate_dispatch import dispatch
from render_full_articles import render
from verify_source import canonical_source_article

class SourcePipelineTests(unittest.TestCase):
 def test_100_line_ocr_synthetic_retains_raw_and_candidate_only(self):
  rows=[{'block_id':f'B{i:04}','text':f'Thevalueis{i}kPa.','bbox':[0,i,20,i+1],'read_order':i,'kind':'paragraph','source':{'locator':f'p{i}'}} for i in range(1,101)]
  out=restore(rows); self.assertEqual(len(out),100); self.assertEqual(out[0]['raw_text'],'Thevalueis1kPa.'); self.assertEqual(out[0]['restoration']['candidate'],'The value is 1kPa.'); self.assertFalse(out[0]['restoration']['approved'])
  self.assertEqual(restore([{'text':'temperature ISO1234-5 formula x=2'}])[0]['restoration']['candidate'],'temperature ISO1234-5 formula x=2')
  self.assertEqual(restore([{'text':'Thisdocument'}])[0]['restoration']['candidate'],'This document')
 def test_registry_never_substitutes_block_id_for_title(self):
  r=build_registry([{'block_id':'4.1','kind':'paragraph'}],'abc'); self.assertEqual(r['headings'],[])
  r=build_registry([{'block_id':'B1','title':'4.1 Scope','clause_id':'4.1','kind':'heading'}],'abc'); self.assertEqual(r['headings'][0]['title'],'4.1 Scope')
 def fixture(self):
  raw=b'PDF source'; h=hashlib.sha256(raw).hexdigest(); src={'file':'source.pdf','sha256':h}
  blocks=[{'block_id':f'B{i}','clause_id':str(i),'kind':'clause','source_lang':'en','original_text':f'Clause {i}. Test {i}.','source':{'file':'source.pdf','sha256':h,'pdf_page':i,'page_kind':'pdf','locator':f'PDF page {i}'}} for i in range(1,4)]
  clauses={'schema_version':'2.0','standard_id':'X','edition':'1','source':src,'blocks':blocks}
  ext={'file':'source.pdf','sha256':h,'complete':True,'pages':[{'page':i,'page_kind':'pdf','locator':f'PDF page {i}','text':blocks[i-1]['original_text']} for i in range(1,4)]}
  return clauses,ext
 def checked_payload(self,clauses,stem):
  article=ROOT/'tests'/f'{stem}.md'; article.write_bytes(canonical_source_article(clauses))
  registry={'schema_version':'1.0','source_sha256':clauses['source']['sha256'],'headings':[]}; regpath=ROOT/'tests'/f'{stem}_registry.json'; regpath.write_text(json.dumps(registry),encoding='utf-8')
  canon=lambda x:json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
  return {'source_sha256':clauses['source']['sha256'],'review_status':'source_checked','source_complete':True,'article_sha256':hashlib.sha256(article.read_bytes()).hexdigest(),'article_path':str(article),'clauses_sha256':hashlib.sha256(canon(clauses)).hexdigest(),'heading_registry_path':str(regpath),'heading_registry_sha256':hashlib.sha256(canon(registry)).hexdigest()},[article,regpath]
 def test_missing_appendix_and_critical_review_block_freeze(self):
  c,e=self.fixture(); checklist=[{'id':'Appendix A','kind':'appendix','status':'missing','critical':True}]
  ap=ROOT/'tests'/'article_pipeline_fixture.tmp'; ap.write_text('article',encoding='utf-8')
  r=verify_source(c,e,checklist,{'reviewer':'R','reviewed_at':'today','approval_evidence':'record'},ap)
  self.assertFalse(r['source_complete']); self.assertEqual(r['review_status'],'draft')
  r=verify_source(c,e,[{'id':'safety','status':'open','critical':True}],{'reviewer':'R','reviewed_at':'today','approval_evidence':'record'},ap)
  ap.unlink()
  self.assertFalse(r['source_complete'])
 def test_empty_checklist_inventory_unknown_appendix_and_article_tamper_block(self):
  c,e=self.fixture(); e['pages'][2]['text']='Annex A — normative annex\n'+e['pages'][2]['text']
  inventory={k:[] for k in ('pages','chapters','normative_annexes','tables','figures','references')}
  ap=ROOT/'tests'/'canonical_article.tmp'; ap.write_bytes(canonical_source_article(c))
  review={'reviewer':'R','reviewed_at':'now','approval_evidence':'manual signoff'}
  self.assertFalse(verify_source(c,e,[],review,ap,expected_inventory=inventory)['source_complete'])
  checklist=[{'inventory_kind':'pages','inventory_id':f'PDF page {i}','status':'complete'} for i in (1,2,3)]
  self.assertFalse(verify_source(c,e,checklist,review,ap,expected_inventory=inventory)['source_complete'])
  ap.write_text('arbitrary text')
  self.assertIn('canonical source renderer',str(verify_source(c,e,checklist,review,ap,expected_inventory=inventory)['blockers']))
  ap.unlink()
 def test_same_page_unrepresented_body_text_blocks_complete_source(self):
  c,e=self.fixture(); e['pages'][0]['text']+='\nUnmapped safety exception text.'
  ap=ROOT/'tests'/'partial_page_article.md'; ap.write_bytes(canonical_source_article(c))
  result=verify_source(c,e,[{'id':'page','status':'reviewed'}],None,ap,expected_inventory={k:[] for k in ('pages','chapters','normative_annexes','tables','figures','references')})
  self.assertFalse(result['source_complete']); self.assertTrue(any('unrepresented non-whitespace' in x['reason'] for x in result['blockers'])); ap.unlink()
 def test_source_checked_requires_real_hash_inventory_and_canonical_article(self):
  from local_parser import extract_document
  source_file=ROOT/'tests'/'pipeline_source.txt'; source_file.write_text('Clause 1. Test 1.\nClause 2. Test 2.\nClause 3. Test 3.',encoding='utf-8')
  try:
   e=extract_document(source_file); h=e['sha256']; c={'schema_version':'2.0','standard_id':'X','edition':'1','source':{'file':str(source_file),'sha256':h},'blocks':[]}
   for i in range(1,4): c['blocks'].append({'block_id':f'B{i}','clause_id':str(i),'kind':'clause','source_lang':'en','original_text':f'Clause {i}. Test {i}.','source':{'file':str(source_file),'sha256':h,'pdf_page':None,'page_kind':'text','locator':'text document'}})
   article=ROOT/'tests'/'pipeline_article.md'; article.write_bytes(canonical_source_article(c))
   inv={'pages':['text document'],'chapters':[],'normative_annexes':[],'tables':[],'figures':[],'references':[]}
   checklist=[{'inventory_kind':'pages','inventory_id':'text document','status':'complete'}]
   review={'reviewer':'Reviewer','reviewed_at':'2026-10-11','approval_evidence':'recorded source review'}
   registry={'schema_version':'1.0','source_sha256':h,'headings':[]}
   result=verify_source(c,e,checklist,review,article,expected_inventory=inv,heading_registry=registry)
   self.assertTrue(result['source_complete']); self.assertEqual(result['review_status'],'source_checked')
   article.unlink()
  finally: source_file.unlink(missing_ok=True)
 def test_span_page_kind_and_file_mismatch_block(self):
  c,e=self.fixture(); c['blocks'][0]['spans']=[{'source':dict(c['blocks'][0]['source'],page_kind='text'),'quote':c['blocks'][0]['original_text']}]
  ap=ROOT/'tests'/'span_article.tmp'; ap.write_bytes(canonical_source_article(c))
  result=verify_source(c,e,[{'id':'x','status':'complete'}],{'reviewer':'R','reviewed_at':'now','approval_evidence':'manual'},ap,expected_inventory={k:[] for k in ('pages','chapters','normative_annexes','tables','figures','references')})
  self.assertFalse(result['source_complete']); self.assertTrue(any('page_kind' in x['reason'] for x in result['blockers'])); ap.unlink()
 def test_three_translations_reordered_render_in_clause_order(self):
  c,e=self.fixture(); segs=[]
  for b in reversed(c['blocks']): segs.append({'block_id':b['block_id'],'original_text':b['original_text'],'source':b['source'],'translated_text':'中文'+b['block_id']})
  frozen,paths=self.checked_payload(c,'render_source'); result=render(c,{'segments':segs},frozen)
  self.assertLess(result['bilingual'].index('中文B1'),result['bilingual'].index('中文B2')); self.assertIn('source_checked',result['source_status']); self.assertIn('DRAFT',result['bilingual']); [p.unlink() for p in paths]
 def test_unreviewed_translation_never_emits_completed_status_and_chinese_skips_translation(self):
  c,e=self.fixture(); segs=[{'block_id':b['block_id'],'original_text':b['original_text'],'source':b['source'],'translated_text':'中文'} for b in c['blocks']]
  frozen,paths=self.checked_payload(c,'unreviewed_source'); r=render(c,{'segments':segs},frozen); [p.unlink() for p in paths]
  self.assertEqual(r['translation_status'],'draft'); self.assertNotIn('translation_approved',r['status'])
  c['blocks'][0]['source_lang']='zh-CN'; chinese=render(c)['chinese']; self.assertIn('DRAFT',chinese); self.assertIn(canonical_source_article(c).decode(),chinese)
 def test_reviewed_wrong_numeric_translation_fails_validation_gate(self):
  c,e=self.fixture(); c['blocks'][0]['original_text']='Pressure 5 kPa.'
  segments=[]
  for b in c['blocks']:
   original=b['original_text']; translated='Pressure 6 kPa.' if b['block_id']=='B1' else original
   segments.append({'block_id':b['block_id'],'clause_id':b['clause_id'],'source_lang':'en','target_lang':'zh-CN','source':b['source'],'pdf_page':b['source']['pdf_page'],'original_text':original,'source_quote':original,'translated_text':translated,'protected_tokens':[],'human_reviewed':True,'review_record':{'reviewer':'R','reviewed_at':'today','approval_evidence':'review'}})
  frozen,paths=self.checked_payload(c,'wrong_numeric_review'); result=render(c,{'schema_version':'2.0','segments':segments},frozen); [p.unlink() for p in paths]
  self.assertEqual(result['translation_status'],'draft'); self.assertTrue(any('numeric tokens mismatch' in e for e in result['translation_validation']['B1']['errors'])); self.assertIn('DRAFT',result['chinese'])
 def test_bad_cross_page_table_provenance_and_missing_translation_block(self):
  c,e=self.fixture(); c['blocks'][1]['source']['sha256']='bad'
  r=verify_source(c,e,[],None)
  self.assertFalse(r['source_complete']); self.assertTrue(r['blockers'])
  c,e=self.fixture()
  with self.assertRaises(ValueError): render(c,{'segments':[{'block_id':'B1','original_text':c['blocks'][0]['original_text'],'translated_text':'a','source':c['blocks'][0]['source']}]})
 def test_dispatch_freeze_gate_and_chinese_skip(self):
  c,e=self.fixture(); self.assertEqual(dispatch(c,{'source_sha256':c['source']['sha256'],'review_status':'draft'})['status'],'draft_blocked')
  c['blocks'][0]['source_lang']='zh-CN'; self.assertFalse(dispatch(c,{'source_sha256':c['source']['sha256']})['translation_required'])

if __name__=='__main__': unittest.main()
