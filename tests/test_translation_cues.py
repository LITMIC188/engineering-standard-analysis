"""Synthetic language cues; no technical standard or actual human approval."""
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('translation_cues',ROOT/'scripts/validate_translation.py')
v=importlib.util.module_from_spec(spec); spec.loader.exec_module(v)

class TranslationCues(unittest.TestCase):
    def test_negations_longest_match(self):
        self.assertEqual([m.group(0) for m in v.MODAL_RE.finditer('shall not; must not; should not; may not; shall')],
                         ['shall not','must not','should not','may not','shall'])
        self.assertEqual([m.group(0) for m in v.MODAL_RE.finditer('してはならない。してはいけない。')],
                         ['してはならない','してはいけない'])

    def test_ambiguous_prose_does_not_become_units(self):
        self.assertEqual(v.unit_tokens('A method, N samples and m as a variable.'),{})
        self.assertEqual(v.unit_tokens('5kPa; 2 MPa; 3 m; 4 mPa'),{'kPa':1,'MPa':1,'m':1,'mPa':1})
        self.assertNotEqual(v.unit_tokens('5 MPa'),v.unit_tokens('5 mPa'))

    def test_whitelist_cannot_remove_actual_measured_units(self):
        errors=[]
        v._lexical_exceptions({'lexical_exceptions':[{'token':'m','side':'source','reason':'synthetic',
            'review_record':{'reviewer':'test fixture','reviewed_at':'fixture','approval_evidence':'synthetic only'}}]},
            '3 m','3 m',errors,'fixture')
        self.assertTrue(any('cannot be whitelisted' in x for x in errors))

    def test_japanese_conditions_remain_review_cues(self):
        self.assertTrue(v.CONDITION_RE.search('ただし、指定した場合に限り、以下とする。'))

    def test_duplicate_keys_rejected(self):
        import json
        with self.assertRaisesRegex(ValueError,'duplicate JSON key'):
            json.loads('{"measurement":1,"measurement":2}',object_pairs_hook=v._no_duplicates)

if __name__=='__main__': unittest.main()
