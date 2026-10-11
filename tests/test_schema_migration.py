import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import json_io
import migrate_schema_v2

class SchemaMigrationTests(unittest.TestCase):
    def test_duplicate_json_keys_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate JSON key'):
            json_io.loads('{"measurement":1,"measurement":2}')
    def test_migration_demotes_legacy_approval_and_logs(self):
        data={'schema_version':'2.0','requirements':[{'requirement_id':'R1','review_status':'approved','source_verified':True}]}
        migrated,log=migrate_schema_v2.migrate(data,'requirements')
        self.assertEqual(migrated['requirements'][0]['review_status'],'source_checked')
        self.assertFalse(log['approval_granted'])
        self.assertEqual(log['review_queue'][0]['requirement_id'],'R1')
    def test_migration_requires_explicit_v2_and_span_source(self):
        with self.assertRaisesRegex(ValueError,'schema_version 2.0'):
            migrate_schema_v2.migrate({'schema_version':'3.0','tests':[]},'test_plan')
        with self.assertRaisesRegex(ValueError,'lacks locator'):
            migrate_schema_v2.migrate({'schema_version':'2.0','tests':[{'test_id':'T'}]},'test_plan')

if __name__=='__main__':unittest.main()
