import json, unittest, importlib.util
from pathlib import Path
R=Path(__file__).resolve().parents[1]

def load_script(name):
    spec=importlib.util.spec_from_file_location(name,R/'scripts'/f'{name}.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

class TestContract(unittest.TestCase):
    def read(self,n):return json.loads((R/'tests'/'fixtures'/n).read_text(encoding='utf-8'))
    def test_translation_clean(self):
        validator=load_script('validate_translation');self.assertEqual(validator.check(self.read('translations.json')),[])
    def test_translation_bad_number(self):
        validator=load_script('validate_translation');data=self.read('translations.json');data['segments'][0]['translated_text']='演示应记录 6 kPa。';self.assertTrue(any('numeric tokens mismatch' in x for x in validator.check(data)))
    def test_testplan_clean(self):
        validator=load_script('validate_experiment_audit');self.assertEqual(validator.check(self.read('requirements.json'),self.read('test_plan.json'),self.read('experiment_audit.json')),[])
    def test_testplan_unassessed_req(self):
        validator=load_script('validate_experiment_audit');data=self.read('experiment_audit.json');data['items'].pop();self.assertTrue(any('unassessed applicable requirement' in x for x in validator.check(self.read('requirements.json'),self.read('test_plan.json'),data)))
    def test_testplan_bad_aligned_with_missing_conditions(self):
        validator=load_script('validate_experiment_audit');data=self.read('experiment_audit.json');data['items'][0]['status']='aligned';self.assertTrue(any('aligned requires' in x for x in validator.check(self.read('requirements.json'),self.read('test_plan.json'),data)))
    def test_testplan_fake_pass_without_evidence(self):
        validator=load_script('validate_experiment_audit');data=self.read('experiment_audit.json');data['items'][0]['status']='aligned';data['items'][0]['plan_evidence']=None;self.assertTrue(any('requires plan_evidence' in x for x in validator.check(self.read('requirements.json'),self.read('test_plan.json'),data)))
if __name__=='__main__':unittest.main()
