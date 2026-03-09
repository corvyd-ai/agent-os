"""Parse JSONL log and cost files."""

import json
from datetime import timedelta
from pathlib import Path

from ..config import company_date


def parse_jsonl_file(path: Path) -> list[dict]:
    """Parse all entries from a JSONL file."""
    if not path.exists():
        return []
    entries = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def parse_jsonl_files(directory: Path, days: int = 7) -> list[dict]:
    """Parse JSONL files from the last N days in a directory.

    Assumes files are named YYYY-MM-DD.jsonl.
    """
    if not directory.exists():
        return []
    entries = []
    today = company_date()
    for i in range(days):
        date = today - timedelta(days=i)
        path = directory / f"{date}.jsonl"
        entries.extend(parse_jsonl_file(path))
    return entries
