import hashlib
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("local_parser",ROOT/"scripts"/"local_parser.py")
parser=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(parser)


def zip_sample(path, files):
    with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED) as z:
        for name,data in files.items(): z.writestr(name,data)


class TestLocalParser(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/"tests"); self.root=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()

    def test_text_formfeed_hash_and_nonphysical_page_label(self):
        path=self.root/"source.txt"; raw="Clause 1\nline 2\fClause 2".encode(); path.write_bytes(raw)
        got=parser.extract_document(path)
        self.assertEqual(got["sha256"],hashlib.sha256(raw).hexdigest())
        self.assertEqual([x["page_kind"] for x in got["pages"]],["text","text"])
        self.assertEqual(got["pages"][0]["text"],"Clause 1\nline 2")
        self.assertIn("not verified physical",got["warnings"][0]); self.assertFalse(got["complete"])

    def test_csv_keeps_rows(self):
        p=self.root/"a.csv"; p.write_text("clause,requirement\n1.1,Record 5 kPa\n",encoding="utf-8")
        out=parser.extract_document(p)
        self.assertEqual(len(out["pages"]),2); self.assertIn("5 kPa",out["pages"][1]["text"])

    def test_docx_paragraphs_and_table_rows(self):
        p=self.root/"sample.docx"
        w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        xml=f'''<w:document xmlns:w="{w}"><w:body><w:p><w:r><w:t>Clause 1.1</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Specimen</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>3 units</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'''
        zip_sample(p,{"word/document.xml":xml})
        got=parser.extract_document(p)
        self.assertEqual([x["locator"] for x in got["pages"]],["paragraph 1","table 1 row 1"])
        self.assertIn("3 units",got["pages"][1]["text"])

    def test_xlsx_shared_and_inline_cells(self):
        p=self.root/"sample.xlsx"; main="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        rel="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
        pkg="http://schemas.openxmlformats.org/package/2006/relationships"
        files={"xl/workbook.xml":f'<workbook xmlns="{main}" xmlns:r="{rel}"><sheets><sheet name="Plan" sheetId="1" r:id="rId1"/></sheets></workbook>',
          "xl/_rels/workbook.xml.rels":f'<Relationships xmlns="{pkg}"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
          "xl/sharedStrings.xml":f'<sst xmlns="{main}"><si><t>Clause 2.1</t></si></sst>',
          "xl/worksheets/sheet1.xml":f'<worksheet xmlns="{main}"><sheetData><row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="inlineStr"><is><t>10 cycles</t></is></c></row></sheetData></worksheet>'}
        zip_sample(p,files); got=parser.extract_document(p)
        self.assertEqual(got["pages"][0]["locator"],"worksheet Plan row 1")
        self.assertIn("Clause 2.1",got["pages"][0]["text"]); self.assertIn("10 cycles",got["pages"][0]["text"])

    def test_json_is_rejected_and_missing_pdf_parser_is_clear(self):
        p=self.root/"data.json"; p.write_text("{}")
        with self.assertRaisesRegex(ValueError,"not a source document"): parser.extract_document(p)
        pdf=self.root/"fake.pdf"; pdf.write_bytes(b"%PDF-demo")
        with self.assertRaisesRegex(parser.ParserUnavailableError,"No download was attempted"):
            parser._pdf(pdf,pypdf_module=False,pdftotext_path=None)


if __name__=="__main__": unittest.main()
