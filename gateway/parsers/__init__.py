"""Unified parser dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gateway.parsers.common import ParserError, detect_format
from gateway.parsers.csv_parser import parse_csv
from gateway.parsers.excel_parser import parse_excel
from gateway.parsers.json_parser import parse_json


def parse_file(path: Path) -> dict[str, Any]:
    """Parse a file by detected format. Raises ParserError on failure."""
    fmt = detect_format(path)
    if fmt == "csv":
        return parse_csv(path)
    if fmt == "excel":
        return parse_excel(path)
    if fmt == "json":
        return parse_json(path)
    raise ParserError(f"Unhandled format: {fmt}")


__all__ = [
    "ParserError",
    "parse_file",
    "parse_csv",
    "parse_excel",
    "parse_json",
    "detect_format",
]
