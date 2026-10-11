"""Strict JSON loading helpers; duplicate object keys are ambiguous and rejected."""
import json
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
