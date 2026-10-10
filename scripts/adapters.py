"""Offline adapter for audited clause translations and optional local tools.

This module never launches a third-party command or performs network access.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import argparse
from pathlib import Path


def _need(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _block_digest(block):
    protected = {key: block.get(key) for key in ("block_id", "clause_id", "source_lang", "original_text", "source", "spans", "protected_tokens", "kind")}
    canonical = json.dumps(protected, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def prepare_translation(clauses, output_dir, max_chars=1800):
    """Write TQC-compatible source_blocks.json and an aligned translation scaffold.

    Clause blocks are never split, including tables. Oversize blocks are flagged
    for manual chunking at a verified clause/table boundary.
    """
    if clauses.get("schema_version") != "2.0" or not isinstance(clauses.get("blocks"), list):
        raise ValueError("clauses must use schema_version 2.0 and contain blocks[]")
    if not isinstance(max_chars, int) or max_chars < 1:
        raise ValueError("max_chars must be a positive integer")
    out = Path(output_dir).expanduser().resolve()
    if out.exists():
        raise FileExistsError(f"refusing to overwrite existing output directory: {out}")
    out.mkdir(parents=True, exist_ok=True)
    mapped, ids, lines = [], {}, ["# Aligned Translation", "", "Translate each source block while preserving identifiers, numbers, units, formulas, and normative force.", ""]
    seen = set()
    for i, block in enumerate(clauses["blocks"], 1):
        bid = _need(block.get("block_id"), "block_id")
        if bid in seen:
            raise ValueError(f"duplicate block_id: {bid}")
        seen.add(bid)
        source = block.get("source") or {}
        text = _need(block.get("original_text"), "original_text")
        sid = f"S{i:04d}"
        ids[sid] = bid
        kind = block.get("kind", "clause")
        oversized = len(text) > max_chars
        record = {"id": sid, "type": "table" if kind == "table" else "paragraph", "text": text,
                  "block_id": bid, "clause_id": block.get("clause_id", ""),
                  "source": {"file": source.get("file"), "sha256": source.get("sha256"),
                             "pdf_page": source.get("pdf_page"), "locator": source.get("locator"),
                             "page_kind": source.get("page_kind")},
                  "protected_tokens": list(block.get("protected_tokens", [])),
                  "oversized_review_required": oversized}
        mapped.append(record)
        lines.extend([f"## {sid}", "", "<translation pending>", ""])
    payload = {"source": clauses.get("source", {}), "source_language": clauses["blocks"][0].get("source_lang", "auto") if clauses["blocks"] else "auto",
               "target_language": "zh-CN", "block_count": len(mapped), "blocks": mapped,
               "adapter": {"contract": "engineering-standard-analysis/2.0", "id_map": ids}}
    (out / "source_blocks.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "translation_aligned.md").write_text("\n".join(lines), encoding="utf-8")
    manifest = {"contract": "TQC source_blocks.json + translation_aligned.md scaffold", "blocks": len(mapped),
                "id_map": ids,
                "block_hashes": {f"S{i:04d}": _block_digest(block) for i, block in enumerate(clauses["blocks"], 1)},
                "oversized_ids": [b["id"] for b in mapped if b["oversized_review_required"]]}
    (out / "adapter_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"source_blocks": str(out / "source_blocks.json"), "aligned": str(out / "translation_aligned.md"), "manifest": str(out / "adapter_manifest.json"), "id_map": ids, "block_hashes": manifest["block_hashes"]}


_HEADING = re.compile(r"^##\s+(S\d{4,})\s*$", re.MULTILINE)


def import_translations(clauses, aligned_file, id_map=None, block_hashes=None):
    """Import TQC translation_aligned.md with strict one-to-one S-ID coverage."""
    content = Path(aligned_file).expanduser().read_text(encoding="utf-8-sig")
    matches = list(_HEADING.finditer(content))
    blocks = clauses.get("blocks", [])
    manifest_path = Path(aligned_file).expanduser().resolve().parent / "adapter_manifest.json"
    if manifest_path.is_file():
        saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        if id_map is not None and saved.get("id_map") != id_map:
            raise ValueError("provided id_map differs from the prepared adapter manifest")
        if id_map is None:
            id_map = saved.get("id_map")
        if block_hashes is None:
            block_hashes = saved.get("block_hashes")
    expected = {}
    by_block = {b.get("block_id"): b for b in blocks}
    if id_map:
        if set(id_map.values()) != set(by_block):
            raise ValueError("id_map does not match the current clauses block IDs")
        expected = {sid: by_block[bid] for sid, bid in id_map.items()}
        if block_hashes:
            for sid, block in expected.items():
                digest = _block_digest(block)
                if block_hashes.get(sid) != digest:
                    raise ValueError(f"source text changed after preparation for {sid}")
    else:
        expected = {f"S{i:04d}": b for i, b in enumerate(blocks, 1)}
    found, by_id = [], {}
    for n, m in enumerate(matches):
        sid = m.group(1)
        if sid in by_id:
            raise ValueError(f"duplicate translation anchor: {sid}")
        end = matches[n + 1].start() if n + 1 < len(matches) else len(content)
        body = content[m.end():end]
        comment = re.match(r"\s*<!--\s*block_id:\s*(.*?)\s*-->\s*", body, flags=re.S)
        expected_block = expected.get(sid)
        if comment and expected_block and comment.group(1) != expected_block.get("block_id"):
            raise ValueError(f"block_id comment mismatch for {sid}: expected {expected_block.get('block_id')}, got {comment.group(1)}")
        if not id_map and expected_block and (not comment or comment.group(1) != expected_block.get("block_id")):
            raise ValueError(f"missing or mismatched block_id comment for {sid}; pass the prepared id_map")
        body = body[comment.end():] if comment else body
        body = body.strip()
        if not body or body == "<translation pending>":
            raise ValueError(f"translation missing for {sid}")
        by_id[sid] = body
        found.append(sid)
    missing, extra = set(expected) - set(found), set(found) - set(expected)
    if missing or extra:
        raise ValueError(f"translation anchors mismatch; missing={sorted(missing)}, extra={sorted(extra)}")
    segments = []
    for sid, block in expected.items():
        source = block.get("source") or {}
        segments.append({"block_id": block["block_id"], "clause_id": block.get("clause_id", ""),
                         "pdf_page": source.get("pdf_page"), "source": dict(source),
                         "source_lang": block.get("source_lang", "und"), "target_lang": "zh-CN",
                         "original_text": block["original_text"], "source_quote": block["original_text"], "translated_text": by_id[sid],
                         "source_spans": block.get("spans") or [{"source":dict(source),"quote":block["original_text"]}],
                         "protected_tokens": list(block.get("protected_tokens", [])), "human_reviewed": False})
    return {"schema_version": "2.0", "segments": segments}


TOOL_DIRS = {
    "docling": ("docling",), "mineru": ("mineru",), "doc-query": ("doc-query",),
    "doc-extract": ("doc-extract",), "doc-compare": ("doc-compare",),
    "traceability-matrix": ("traceability-matrix",), "iso-standards-readiness": ("iso-standards-readiness",),
    "mineru-document-explorer": ("mineru-document-explorer",),
    "translation-quality-codex": ("translation-quality-codex",),
    "document-translate-preserve-format": ("document-translate-preserve-format",),
    "academic-paper-translator": ("academic-paper-translator",), "translate-book": ("translate-book",),
    "tutor-setup": ("tutor-setup",),
}


def doctor(roots):
    """Inspect only explicitly supplied roots; report installed folders and runtimes."""
    normalized = [Path(r).expanduser().resolve() for r in roots]
    results = {}
    runtime = {name: shutil.which(name) for name in ("python", "python3", "docling", "mineru")}
    for tool, names in TOOL_DIRS.items():
        hits = [str(root / candidate) for root in normalized for candidate in names
                if (root / candidate / "SKILL.md").is_file()]
        results[tool] = {"status": "local_available" if hits else "contract_only", "paths": hits,
                         "execution_adapter": False, "file_adapter": tool in {"translation-quality-codex","tutor-setup"}}
    return {"tools": results, "runtime": runtime, "roots_checked": [str(p) for p in normalized]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline adapters for engineering standard analysis")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="create TQC-compatible source blocks and aligned scaffold")
    prep.add_argument("clauses_json"); prep.add_argument("output_dir"); prep.add_argument("--max-chars", type=int, default=1800)
    imp = sub.add_parser("import", help="strictly import TQC translation_aligned.md")
    imp.add_argument("clauses_json"); imp.add_argument("aligned_file"); imp.add_argument("output_json")
    imp.add_argument("--id-map", help="prepared adapter_manifest.json path (defaults beside aligned file)")
    doc = sub.add_parser("doctor", help="inspect only explicitly supplied roots")
    doc.add_argument("roots", nargs="+")
    args = parser.parse_args(argv)
    if args.command == "doctor":
        result = doctor(args.roots)
    else:
        clauses = json.loads(Path(args.clauses_json).read_text(encoding="utf-8"))
        if args.command == "prepare":
            result = prepare_translation(clauses, args.output_dir, args.max_chars)
        else:
            id_map = block_hashes = None
            if args.id_map:
                saved = json.loads(Path(args.id_map).read_text(encoding="utf-8"))
                id_map, block_hashes = saved.get("id_map"), saved.get("block_hashes")
            result = import_translations(clauses, args.aligned_file, id_map=id_map, block_hashes=block_hashes)
            Path(args.output_json).expanduser().resolve().write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(args.output_json)
            return 0
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
