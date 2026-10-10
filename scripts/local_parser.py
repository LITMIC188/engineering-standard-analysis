"""Offline-first document extraction helpers for engineering-standard-analysis.

No network clients or remote OCR are used. PDF extraction uses an installed
pypdf package or the local pdftotext executable.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


class ParserUnavailableError(RuntimeError):
    """Raised when no local parser is available for a supported format."""


def _entry(page, page_kind, locator, text):
    return {"page": page, "page_kind": page_kind, "locator": locator, "text": text}


def _xml(root, name):
    return root.find(".//{%s}%s" % ("http://schemas.openxmlformats.org/wordprocessingml/2006/main", name))


def _docx(path):
    pages = []
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    body = root.find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}body")
    p_no = t_no = 0
    if body is not None:
        for child in body:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                p_no += 1
                txt = "".join((n.text or "") for n in child.iter() if n.tag.rsplit("}", 1)[-1] == "t")
                if txt.strip(): pages.append(_entry(None, "section", f"paragraph {p_no}", txt))
            elif tag == "tbl":
                t_no += 1
                for r_no, row in enumerate(child.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tr"), 1):
                    cells=[]
                    for cell in row.findall("./{http://schemas.openxmlformats.org/wordprocessingml/2006/main}tc"):
                        cells.append("\n".join("".join((n.text or "") for n in p.iter() if n.tag.rsplit("}",1)[-1] == "t") for p in cell.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p")))
                    pages.append(_entry(None, "section", f"table {t_no} row {r_no}", "\t".join(cells)))
    return pages


def _xlsx(path):
    ns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    relns="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pkg="http://schemas.openxmlformats.org/package/2006/relationships"
    pages=[]
    with zipfile.ZipFile(path) as zf:
        names=set(zf.namelist())
        shared=[]
        if "xl/sharedStrings.xml" in names:
            sr=ET.fromstring(zf.read("xl/sharedStrings.xml"))
            shared=["".join(t.text or "" for t in si.iter("{%s}t"%ns)) for si in sr.findall("{%s}si"%ns)]
        wb=ET.fromstring(zf.read("xl/workbook.xml"))
        rel=ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        targets={x.attrib["Id"]:x.attrib["Target"] for x in rel.findall("{%s}Relationship"%pkg)}
        for sheet in wb.findall(".//{%s}sheet"%ns):
            title=sheet.attrib.get("name","sheet")
            target=targets.get(sheet.attrib.get("{%s}id"%relns))
            if not target: continue
            member=target.lstrip("/") if target.startswith("/") else "xl/"+target
            parts=[]
            for row in ET.fromstring(zf.read(member)).findall(".//{%s}sheetData/{%s}row"%(ns,ns)):
                vals=[]
                for cell in row.findall("{%s}c"%ns):
                    v=cell.find("{%s}v"%ns); value="" if v is None else (v.text or "")
                    if cell.attrib.get("t")=="s" and value: value=shared[int(value)]
                    elif cell.attrib.get("t")=="inlineStr": value="".join(t.text or "" for t in cell.iter("{%s}t"%ns))
                    formula=cell.find("{%s}f"%ns)
                    if formula is not None:
                        value=f"FORMULA[{formula.text or ''}] CACHED[{value}]"
                    vals.append(f"{cell.attrib.get('r','?')}={value}")
                pages.append(_entry(None,"section",f"worksheet {title} row {row.attrib.get('r','?')}","\t".join(vals)))
    return pages


def _pdf(path, pypdf_module=None, pdftotext_path="AUTO"):
    warnings=[]; pages=[]
    if pypdf_module is False:
        pypdf_module=None
    elif pypdf_module is None:
        try:
            import pypdf as pypdf_module
        except ImportError:
            pypdf_module=None
    if pypdf_module is not None:
        reader=pypdf_module.PdfReader(str(path))
        for i,p in enumerate(reader.pages,1): pages.append(_entry(i,"pdf",f"PDF page {i}",p.extract_text() or ""))
    else:
        exe=shutil.which("pdftotext") if pdftotext_path=="AUTO" else pdftotext_path
        if not exe: raise ParserUnavailableError("PDF parsing requires local 'pypdf' or 'pdftotext'; install one locally and retry. No download was attempted.")
        proc=subprocess.run([exe,"-layout",str(path),"-"],capture_output=True,text=True,encoding="utf-8",errors="replace",check=False)
        if proc.returncode: raise RuntimeError(f"local pdftotext failed (exit {proc.returncode}): {proc.stderr.strip()}")
        for i,txt in enumerate(proc.stdout.split("\f"),1):
            if i==len(proc.stdout.split("\f")) and not txt.strip(): break
            pages.append(_entry(i,"pdf",f"PDF page {i}",txt))
    if not pages: warnings.append("PDF contains no extractable pages; it may be scanned or empty.")
    for p in pages:
        if not p["text"].strip(): warnings.append(f"PDF page {p['page']} has no extractable text; it may be scanned or blank.")
    return pages,warnings


def extract_document(path):
    """Extract a supported local document; return source hash and located text blocks."""
    p=Path(path).expanduser().resolve(strict=True)
    if not p.is_file(): raise ValueError(f"Not a file: {p}")
    ext=p.suffix.lower()
    formats={".md":"markdown",".markdown":"markdown",".txt":"text",".csv":"csv",".docx":"docx",".xlsx":"xlsx",".pdf":"pdf"}
    if ext==".json": raise ValueError("JSON is structured data, not a source document; it is intentionally not accepted by extract_document.")
    if ext not in formats: raise ValueError(f"Unsupported document format: {ext or '(no extension)'}")
    raw=p.read_bytes(); warnings=[]
    if ext in (".md",".markdown",".txt"):
        source=raw.decode("utf-8-sig")
        chunks=source.split("\f")
        pages=[_entry(i if len(chunks)>1 else None,"text",f"text_page {i}" if len(chunks)>1 else "text document",t) for i,t in enumerate(chunks,1) if t or len(chunks)==1]
        if len(chunks)>1: warnings.append("Form-feed boundaries are text_page locators, not verified physical PDF pages.")
    elif ext==".csv":
        text=raw.decode("utf-8-sig"); pages=[]
        for n,row in enumerate(csv.reader(text.splitlines()),1): pages.append(_entry(None,"section",f"CSV row {n}","\t".join(row)))
    elif ext==".docx":
        pages=_docx(p)
        with zipfile.ZipFile(p) as archive:
            xml=archive.read('word/document.xml')
            root=ET.fromstring(xml)
            tags={n.tag.rsplit('}',1)[-1] for n in root.iter()}
            if tags & {'del','ins','delText','drawing','pict','oMath','oMathPara','vMerge','gridSpan','fldSimple','instrText'}:
                warnings.append('DOCX revisions, fields, figures, formulas or merged cells require local visual review; deleted text is excluded.')
            if any(re.search(r'word/(footnotes|endnotes|header|footer)',name) for name in archive.namelist()):
                warnings.append('DOCX footnotes/endnotes/headers/footers are not included by this text extractor.')
    elif ext==".xlsx":
        pages=_xlsx(p)
        with zipfile.ZipFile(p) as archive:
            for member in archive.namelist():
                if member.startswith('xl/worksheets/') and member.endswith('.xml'):
                    tags={n.tag.rsplit('}',1)[-1] for n in ET.fromstring(archive.read(member)).iter()}
                    if tags & {'f','mergeCell','drawing'}:
                        warnings.append(f'XLSX {member}: formulas/cached values, merged cells or drawings require review; formulas are not recalculated.')
    else:
        try:pages,warnings=_pdf(p)
        except ParserUnavailableError:raise
        except Exception as exc:raise RuntimeError(f'Local PDF extraction failed: {type(exc).__name__}: {exc}') from exc
    if not pages: warnings.append("No extractable content was found.")
    return {"file":str(p),"sha256":hashlib.sha256(raw).hexdigest(),"format":formats[ext],"parser":{".pdf":"pypdf or pdftotext"}.get(ext,"stdlib"),"pages":pages,"warnings":warnings,"complete":not warnings}


def main(argv=None):
    ap=argparse.ArgumentParser(description="Extract local document text without network access.")
    ap.add_argument("input"); ap.add_argument("--out",required=True,help="Output JSON path")
    args=ap.parse_args(argv)
    try: result=extract_document(args.input)
    except Exception as exc:
        print(f"local_parser: {exc}",file=sys.stderr); return 2
    Path(args.out).expanduser().resolve().write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return 0

if __name__=="__main__": raise SystemExit(main())
