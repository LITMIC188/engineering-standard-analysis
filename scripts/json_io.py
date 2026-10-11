"""Strict JSON loading helpers; duplicate object keys are ambiguous and rejected."""
import json
import sys
from pathlib import Path


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def loads(text):
    return json.loads(text, object_pairs_hook=_unique_object)


def load(path):
    return loads(Path(path).read_text(encoding="utf-8-sig"))


def configure_utf8_output():
    """Emit JSON in UTF-8 even under a Windows legacy console code page."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
