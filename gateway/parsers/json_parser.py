"""JSON → unified JSON. Accepts array-of-objects OR arbitrary JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gateway.parsers.common import ParserError, summarize_rows


def parse_json(path: Path) -> dict[str, Any]:
    """Parse JSON file.

    Heuristic:
    - If top-level is a list of dicts → emit as 'rows' (table format)
    - Otherwise → preserve as 'data' (raw structured, e.g. nested analysis result)
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ParserError(f"JSON is not valid UTF-8: {e}") from e
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ParserError(f"JSON parse error: {e}") from e

    if isinstance(obj, list):
        # list of dicts → table form
        rows = [r for r in obj if isinstance(r, dict)]
        if not rows and obj:
            raise ParserError("JSON list contains no objects; expected list of objects for table form")
        return {
            "format": "json",
            "rows": rows,
            "summary": summarize_rows(rows),
        }
    if isinstance(obj, dict):
        return {
            "format": "json",
            "data": obj,  # raw structured
            "summary": {"shape": "object", "top_level_keys": list(obj.keys())},
        }
    raise ParserError(f"JSON must be object or array, got {type(obj).__name__}")


def parse_json_text(content: str) -> dict[str, Any]:
    """Convenience: parse from string (for tests)."""
    obj = json.loads(content)
    if isinstance(obj, list):
        rows = [r for r in obj if isinstance(r, dict)]
        return {"format": "json", "rows": rows, "summary": summarize_rows(rows)}
    if isinstance(obj, dict):
        return {
            "format": "json",
            "data": obj,
            "summary": {"shape": "object", "top_level_keys": list(obj.keys())},
        }
    raise ParserError(f"JSON must be object or array, got {type(obj).__name__}")
