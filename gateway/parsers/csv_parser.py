"""CSV → unified JSON. Uses stdlib csv, no external deps."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from gateway.parsers.common import ParserError, summarize_rows


def parse_csv(path: Path, *, max_bytes: int = 10 * 1024 * 1024) -> dict[str, Any]:
    """Parse CSV into {'format': 'csv', 'rows': [...], 'summary': {...}}.

    `max_bytes` is a sanity guard against runaway files; the upload endpoint
    already caps total size, but this protects the parser path too.
    """
    if path.stat().st_size > max_bytes:
        raise ParserError(f"CSV file too large: {path.stat().st_size} bytes > {max_bytes}")
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
    except UnicodeDecodeError as e:
        raise ParserError(f"CSV is not valid UTF-8: {e}") from e
    except csv.Error as e:
        raise ParserError(f"CSV parse error: {e}") from e
    return {
        "format": "csv",
        "rows": rows,
        "summary": summarize_rows(rows),
    }


def parse_csv_text(content: str) -> dict[str, Any]:
    """Parse CSV from a string (handy for tests + small uploads)."""
    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(content.splitlines())
    for row in reader:
        rows.append({k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()})
    return {
        "format": "csv",
        "rows": rows,
        "summary": summarize_rows(rows),
    }


if __name__ == "__main__":  # pragma: no cover
    import sys
    p = Path(sys.argv[1])
    print(json.dumps(parse_csv(p), ensure_ascii=False, indent=2)[:2000])
