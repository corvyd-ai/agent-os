"""Parse JSONL log and cost files."""

from __future__ import annotations

import json
from pathlib import Path


def parse_jsonl_file(path: Path) -> list[dict]:
    """Parse all entries from a JSONL file. Missing files return empty list."""
    if not path.exists():
        return []
    entries = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries
