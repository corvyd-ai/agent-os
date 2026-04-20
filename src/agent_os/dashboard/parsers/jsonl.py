"""Shim — parsers moved to agent_os.parsers in phase 1 of the CLI-first rework."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from agent_os.parsers.jsonl import parse_jsonl_file

__all__ = ["parse_jsonl_file", "parse_jsonl_files"]


def parse_jsonl_files(directory: Path, days: int = 7) -> list[dict]:
    """Parse JSONL files from the last N days in a directory.

    Kept here for backward compatibility with dashboard routers; the new
    canonical location is agent_os.parsers.jsonl, which intentionally omits
    this helper since no external caller uses it.
    """
    from ..config import company_date

    if not directory.exists():
        return []
    entries: list[dict] = []
    today = company_date()
    for i in range(days):
        date = today - timedelta(days=i)
        path = directory / f"{date}.jsonl"
        entries.extend(parse_jsonl_file(path))
    return entries
