import copy, importlib.util, json, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py'); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod
def fixture(name): return json.loads((ROOT/'tests'/'fixtures'/name).read_text(encoding='utf-8'))

class ExtendedValidation(unittest.TestCase):
    def test_number_exponent_comparison_and_unit_changes_detected(self):
        v=load('validate_translation'); d=fixture('translations.json'); s=d['segments'][0]
        s['original_text']='Apply 1.0e-3 MPa and keep x ≤ 5.'
        s['translated_text']='施加 1.0e-2 kPa，并保持 x ≥ 5。'
        issues=v.check(d)
        self.assertTrue(any('numeric tokens mismatch' in x for x in issues))
        strict=v.validate_bundle(d)
        self.assertTrue(any('comparison operators mismatch' in x for x in strict['errors']))
        self.assertTrue(any('unit tokens mismatch' in x for x in strict['errors']))

    def test_adjacent_numbers_and_case_sensitive_units(self):
        v=load('validate_translation'); d=fixture('translations.json'); s=d['segments'][0]
        s['original_text']='x=5kPa; r2=10 MPa'
        s['translated_text']='x=6kPa; r2=10 mPa'
        result=v.validate_bundle(d)
        self.assertTrue(any('numeric tokens mismatch' in x for x in result['errors']))
        self.assertTrue(any('unit tokens mismatch' in x for x in result['errors']))

    def test_unhashable_legacy_block_id_does_not_crash(self):
        v=load('validate_translation'); d=fixture('translations.json')
        d['segments'][0]['block_id']=['B1']
        self.assertIsInstance(v.check(d),list)

    def test_strict_translation_requires_review_and_quote(self):
        v=load('validate_translation'); d=fixture('translations.json')
        self.assertTrue(any('review_record' in x for x in v.check(d,strict=True)))
        d['segments'][0].update(review_record={'reviewer':'R','reviewed_at':'2026-01-01','approval_evidence':'checked'},source_quote='EXAMPLE shall record 5 kPa.')
        self.assertEqual(v.check(d,strict=True),[])
        self.assertTrue(any('normative-force' in x for x in v.validate_bundle(d)['warnings']))

    def test_non_pdf_page_requires_locator(self):
        v=load('validate_translation'); d=fixture('translations.json'); s=d['segments'][0]; s['pdf_page']=None
        self.assertTrue(any('page_kind and source.locator' in x for x in v.validate_bundle(d)['errors']))
        s['source']={'page_kind':'html','locator':'section #2'}
        self.assertFalse(any('pdf_page' in x for x in v.validate_bundle(d)['errors']))

    def test_audit_unknown_cannot_be_aligned_and_duplicate_dimension(self):
        v=load('validate_experiment_audit'); r=fixture('requirements.json'); p=fixture('test_plan.json'); a=fixture('experiment_audit.json')
        row=a['items'][0]; row['status']='aligned'; row['checkpoints'][1]['status']='matched'; row['checkpoints'].append(copy.deepcopy(row['checkpoints'][0]))
        issues=v.check(r,p,a)
        self.assertTrue(any('cannot be aligned' in x for x in issues))
        self.assertTrue(any('duplicate checkpoint dimensions' in x for x in issues))

    def test_approved_requires_review_record_and_strict_core_coverage(self):
        v=load('validate_experiment_audit'); r=fixture('requirements.json'); p=fixture('test_plan.json'); a=fixture('experiment_audit.json')
        a['items'][0]['review_status']='approved'
        self.assertTrue(any('approved requires human review_record' in x for x in v.check(r,p,a)))
        strict=v.check(r,p,a,strict=True)
        self.assertTrue(any('missing core checkpoints' in x for x in strict))
        self.assertTrue(any('sha256' in x for x in strict))

    def test_malformed_types_do_not_crash(self):
        self.assertTrue(load('validate_translation').check({'schema_version':'2.0','segments':[None,{'protected_tokens':None}]}))
        self.assertTrue(load('validate_experiment_audit').check({'requirements':[None]}, {'tests':[None]}, {'items':[None]}))

    def test_audit_nonobject_checkpoints_and_unhashable_ids_do_not_crash(self):
        v=load('validate_experiment_audit'); r=fixture('requirements.json'); p=fixture('test_plan.json'); a=fixture('experiment_audit.json')
        a['items'][0]['status']='aligned'; a['items'][0]['requirement_id']=['REQ-001']; a['items'][0]['checkpoints']=[None,{'dimension':[],'status':[]}]
        a['items'][1]['audit_id']=['id']
        self.assertTrue(v.check(r,p,a))

    def test_strict_accepts_root_quote_field(self):
        v=load('validate_experiment_audit'); r=fixture('requirements.json'); p=fixture('test_plan.json'); a=fixture('experiment_audit.json')
        for req in r['requirements']:
            req['source'].update(sha256='a'*64, edition='2026'); req['source_verified']=True; req['quote']=req['summary']
        issues=v.check(r,p,a,strict=True)
        self.assertFalse(any('strict validation requires source_quote' in x for x in issues))

if __name__=='__main__': unittest.main()
