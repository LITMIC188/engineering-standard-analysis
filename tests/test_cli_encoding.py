"""CLI JSON must remain UTF-8 under legacy Windows output encodings."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]

class CliEncoding(unittest.TestCase):
    def test_utf8_output_overrides_cp1252(self):
        env=dict(os.environ,PYTHONIOENCODING='cp1252')
        code="import sys;sys.path.insert(0,'scripts');from json_io import configure_utf8_output;configure_utf8_output();print(chr(0x539f)+chr(0x6587))"
        p=subprocess.run([sys.executable,'-c',code],cwd=ROOT,env=env,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(p.stdout.decode('utf-8').strip(),'原文')
