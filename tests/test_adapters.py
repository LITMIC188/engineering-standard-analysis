import json
import shutil
import sys
import unittest
from uuid import uuid4
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from scripts.adapters import doctor, import_translations, prepare_translation


def demo():
    return {"schema_version": "2.0", "standard_id": "DEMO", "edition": "demo", "source": {"file": "demo.txt", "sha256": "abc"}, "blocks": [
        {"block_id": "B0001", "clause_id": "4.1", "source_lang": "en", "original_text": "The value shall be 5 kPa.", "source": {"file": "demo.txt", "sha256": "abc", "pdf_page": None, "locator": "paragraph 1", "page_kind": "section"}, "protected_tokens": ["5 kPa"], "kind": "clause"},
        {"block_id": "B0002", "clause_id": "Table 2", "source_lang": "en", "original_text": "|A|B|\n|--|--|\n|1|2|", "source": {"file": "demo.pdf", "sha256": "def", "pdf_page": 7, "locator": "Table 2", "page_kind": "pdf"}, "protected_tokens": ["1", "2"], "kind": "table"},
    ]}


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.work = Path(__file__).parents[2] / "development-evidence" / "test-work" / f"adapters-{uuid4().hex}"
        self.work.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.work)

    def test_prepare_preserves_ids_and_tables_and_flags_oversize(self):
        temp = self.work / "prep"
        result = prepare_translation(demo(), temp, max_chars=8)
        blocks = json.loads(Path(result["source_blocks"]).read_text(encoding="utf-8"))["blocks"]
        self.assertEqual([b["id"] for b in blocks], ["S0001", "S0002"])
        self.assertEqual(blocks[1]["text"], demo()["blocks"][1]["original_text"])
        self.assertTrue(all(b["oversized_review_required"] for b in blocks))
        self.assertEqual(result["id_map"], {"S0001": "B0001", "S0002": "B0002"})

    def test_import_maps_exact_ids_and_defaults_unreviewed(self):
        out = self.work / "job"
        prepare_translation(demo(), out)
        aligned = out / "translation_aligned.md"
        aligned.write_text("# Aligned\n\n## S0001\n\n数值应为 5 kPa。\n\n## S0002\n\n|A|B|\n|--|--|\n|1|2|\n", encoding="utf-8")
        imported = import_translations(demo(), aligned)
        self.assertEqual(imported["segments"][0]["block_id"], "B0001")
        self.assertIsNone(imported["segments"][0]["pdf_page"])
        self.assertEqual(imported["segments"][1]["pdf_page"], 7)
        self.assertFalse(imported["segments"][0]["human_reviewed"])
        self.assertEqual(imported["segments"][0]["source_quote"], imported["segments"][0]["original_text"])
        self.assertEqual(imported["segments"][0]["source"], demo()["blocks"][0]["source"])

    def test_id_map_handles_clause_reordering(self):
        out = self.work / "mapped"
        prepared = prepare_translation(demo(), out)
        aligned = out / "translation_aligned.md"
        aligned.write_text("## S0001\n\nFirst translation\n## S0002\n\nSecond translation\n", encoding="utf-8")
        reordered = dict(demo())
        reordered["blocks"] = list(reversed(demo()["blocks"]))
        imported = import_translations(reordered, aligned, id_map=prepared["id_map"])
        self.assertEqual(imported["segments"][0]["block_id"], "B0001")
        self.assertEqual(imported["segments"][0]["translated_text"], "First translation")
        with self.assertRaises(ValueError):
            import_translations(demo(), aligned, id_map={"S0001": "B0002", "S0002": "B0001"})
        changed = demo()
        changed["blocks"][0] = dict(changed["blocks"][0], original_text="changed source")
        with self.assertRaisesRegex(ValueError, "source text changed"):
            import_translations(changed, aligned, id_map=prepared["id_map"], block_hashes=prepared["block_hashes"])

    def test_import_rejects_missing_duplicate_and_pending_ids(self):
        cases = ["## S0001\n\nok\n", "## S0001\n\na\n## S0001\n\nb\n", "## S0001\n\n<translation pending>\n## S0002\n\nb\n"]
        path = self.work / "aligned.md"
        for text in cases:
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError):
                import_translations(demo(), path)

    def test_doctor_checks_only_explicit_root(self):
        root = self.work / "doctor"
        skill = root / "translation-quality-codex"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("name: translation-quality-codex", encoding="utf-8")
        result = doctor([root])
        self.assertEqual(result["tools"]["translation-quality-codex"]["status"], "local_available")
        self.assertEqual(result["roots_checked"], [str(root.resolve())])


if __name__ == "__main__":
    unittest.main()
