"""Shim — parsers moved to agent_os.parsers in phase 1 of the CLI-first rework."""

from agent_os.parsers.frontmatter import parse_frontmatter, parse_frontmatter_file

__all__ = ["parse_frontmatter", "parse_frontmatter_file"]
