"""Parse YAML frontmatter + markdown body from agent-os files."""

from __future__ import annotations

from pathlib import Path

import yaml


def parse_frontmatter(path: Path) -> tuple[dict, str]:
    """Parse YAML frontmatter + markdown body from a file.

    Returns (metadata_dict, body_string). If no frontmatter, metadata is empty.
    """
    text = path.read_text()
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return meta, body


def parse_frontmatter_file(path: Path) -> dict:
    """Parse a frontmatter file and return a combined dict with meta + body."""
    meta, body = parse_frontmatter(path)
    return {**meta, "body": body, "_file": path.name}
