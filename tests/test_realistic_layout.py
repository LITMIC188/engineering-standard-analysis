"""Synthetic layout regressions: provenance failures block, uncertain tables stay unknown."""
import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from layout_tables import detect_layout
from heading_registry import build_registry
from parser_adapters import import_structure
from reconstruct_source import reconstruct

class RealisticLayoutTests(unittest.TestCase):
 def test_cross_page_table_keeps_explicit_pages_and_unknown_structure(self):
  rows=[{'kind':'table','original_text':'Header','read_order':1,'region_id':'T1','source':{'pdf_page':8}}, {'kind':'table','original_text':'row 1','read_order':2,'region_id':'T1','source':{'pdf_page':9}}]
  result=detect_layout(rows); self.assertEqual(result[0]['region_pages'],[8,9]); self.assertEqual(result[1]['region_part'],2); self.assertEqual(result[0]['layout_status'],'unknown')
 def test_duplicate_headings_remain_distinct_and_ordered(self):
  r=build_registry([{'title':'Scope','clause_id':'1.1','kind':'heading','order':2},{'title':'Scope','clause_id':'1.2','kind':'heading','order':1}],'h')
  self.assertEqual([x['order'] for x in r['headings']],[1,2]); self.assertNotEqual(r['headings'][0]['heading_id'],r['headings'][1]['heading_id'])
 def test_heading_registry_rejects_title_not_present_on_bound_source_page(self):
  with self.assertRaisesRegex(ValueError,'not traceable'):
   build_registry([{'title':'Fabricated title','clause_id':'1','kind':'heading','source':{'locator':'p1','sha256':'h'}}],'h',[{'locator':'p1','text':'Actual title'}])
 def test_missing_page_provenance_is_blocked_not_assumed_page_one(self):
  import json, tempfile
  p=Path(__file__).with_name('adapter_fixture.tmp'); p.write_text(json.dumps({'blocks':[{'text':'table'}]}),encoding='utf-8')
  try:
   with self.assertRaisesRegex(ValueError,'refusing to assume page 1'): import_structure(p,'x.pdf','h')
  finally: p.unlink()
 def test_docling_provenance_list_and_mineru_export_are_imported(self):
  import json
  p=Path(__file__).with_name('backend_fixture.tmp')
  try:
   p.write_text(json.dumps({'texts':[{'label':'section_header','text':'4 Scope','prov':[{'page_no':1,'bbox':[1,2,3,4]}]}]}),encoding='utf-8')
   d=import_structure(p,'x.pdf','h'); self.assertEqual(d['imported_backend'],'docling-export'); self.assertEqual(d['blocks'][0]['source']['pdf_page'],1); self.assertEqual(d['blocks'][0]['bbox'],[1,2,3,4])
   p.write_text(json.dumps({'content_list':[{'type':'table','page_idx':1,'bbox':[0,0,4,4],'text':'grid'}]}),encoding='utf-8')
   m=import_structure(p,'x.pdf','h'); self.assertEqual(m['imported_backend'],'mineru-export'); self.assertEqual(m['blocks'][0]['source']['locator'],'PDF page 2'); self.assertTrue(m['blockers'])
  finally: p.unlink(missing_ok=True)
 def test_reconstruction_orders_by_page_and_bbox_and_marks_missing_figure(self):
  data={'file':'x.pdf','sha256':'h','complete':True,'pages':[],'blocks':[{'block_id':'B2','kind':'figure','text':'diagram','read_order':2,'bbox':[10,20,30,40],'source':{'pdf_page':2,'page_kind':'pdf','locator':'p2'}},{'block_id':'B1','kind':'paragraph','text':'first','read_order':1,'bbox':[0,0,2,2],'source':{'pdf_page':1,'page_kind':'pdf','locator':'p1'}}]}
  result=reconstruct(data); self.assertFalse(result['complete']); self.assertIn('UNKNOWN layout',result['article']); self.assertLess(result['article'].index('first'),result['article'].index('diagram'))
 def test_pages_only_reconstruct_cli_assigns_stable_ids_without_inventing_page_kind(self):
  import json, subprocess, tempfile
  root=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as td:
   d=Path(td); extraction=d/'extraction.json'; out=d/'out'
   extraction.write_text(json.dumps({'file':'scan.txt','sha256':'a'*64,'complete':True,'pages':[{'text':'First line','locator':'page label A','page_kind':'section'},{'text':'Second line','locator':'page label B','page_kind':'section'}]}),encoding='utf-8')
   proc=subprocess.run([sys.executable,str(root/'scripts'/'reconstruct_source.py'),str(extraction),'--out-dir',str(out)],cwd=root,capture_output=True,text=True)
   self.assertEqual(proc.returncode,0,proc.stderr)
   rebuilt=json.loads((out/'reconstruction.json').read_text(encoding='utf-8'))
   self.assertEqual([b['block_id'] for b in rebuilt['blocks']],['B0001','B0002'])
   self.assertEqual([b['source']['locator'] for b in rebuilt['blocks']],['page label A','page label B'])
   self.assertEqual([b['source']['page_kind'] for b in rebuilt['blocks']],['section','section'])
   self.assertTrue(all('pdf_page' not in b['source'] for b in rebuilt['blocks']))
   self.assertIn('First line',(out/'02_Original_Reconstructed.md').read_text(encoding='utf-8'))
  result=reconstruct({'file':'unknown.bin','sha256':'a'*64,'pages':[{'text':'Text'}]})
  self.assertEqual(result['blocks'][0]['source']['page_kind'],'unknown')
  self.assertFalse(result['complete'])

if __name__=='__main__': unittest.main()
