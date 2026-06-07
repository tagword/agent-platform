"""Common parser utilities and exceptions."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class ParserError(Exception):
    """Raised when a file cannot be parsed into structured data."""


SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".csv", ".xlsx", ".xls", ".json"})


def detect_format(path: Path) -> str:
    """Return one of: 'csv', 'excel', 'json'. Raises ParserError if unsupported."""
    ext = path.suffix.lower()
    if ext == ".csv":
        return "csv"
    if ext in (".xlsx", ".xls"):
        return "excel"
    if ext == ".json":
        return "json"
    raise ParserError(f"Unsupported file extension: {ext}")


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a small summary for a list of dict rows (CSV/Excel)."""
    if not rows:
        return {"row_count": 0, "columns": []}
    columns: list[str] = []
    seen: set[str] = set()
    for r in rows[:50]:  # only inspect first 50 rows for columns
        if not isinstance(r, dict):
            continue
        for k in r.keys():
            if k not in seen:
                seen.add(k)
                columns.append(str(k))
    return {
        "row_count": len(rows),
        "columns": columns,
    }
