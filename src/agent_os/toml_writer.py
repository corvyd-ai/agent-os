"""agent-os TOML writer — round-trip editing of agent-os.toml.

Uses tomlkit for round-trip editing that preserves comments, formatting,
and document structure. Falls back to read-modify-write with tomllib/tomli_w
if tomlkit is not available.

Usage:
    from agent_os.toml_writer import update_toml

    update_toml(Path("agent-os.toml"), "budget", {"daily_cap": 50.0})
"""

from __future__ import annotations

from pathlib import Path


def update_toml(path: Path, section: str, updates: dict) -> None:
    """Update a section of agent-os.toml preserving structure/comments.

    Args:
        path: Path to the TOML file.
        section: Dotted section name, e.g. "budget" or "autonomy.agents".
        updates: Key-value pairs to update within the section.
    """
    try:
        import tomlkit

        content = path.read_text()
        doc = tomlkit.parse(content)

        # Navigate to the section (supports dotted paths like "budget.agent_daily_caps")
        parts = section.split(".")
        target = doc
        for part in parts:
            if part not in target:
                target[part] = tomlkit.table()
            target = target[part]

        # Apply updates
        for key, value in updates.items():
            target[key] = value

        path.write_text(tomlkit.dumps(doc))

    except ImportError:
        # Fallback: read with tomllib, write with basic serialization
        import tomllib

        with open(path, "rb") as f:
            data = tomllib.load(f)

        parts = section.split(".")
        target = data
        for part in parts:
            if part not in target:
                target[part] = {}
            target = target[part]

        for key, value in updates.items():
            target[key] = value

        # Write back (loses comments but preserves data)
        _write_toml_fallback(path, data)


def remove_toml_key(path: Path, section: str, key: str) -> bool:
    """Remove a key from a section of agent-os.toml.

    Returns True if the key was present and removed, False if it wasn't found
    (missing section or missing key). Preserves comments/formatting via tomlkit.
    """
    try:
        import tomlkit

        content = path.read_text()
        doc = tomlkit.parse(content)

        parts = section.split(".")
        target = doc
        for part in parts:
            if part not in target:
                return False
            target = target[part]

        if key not in target:
            return False
        del target[key]
        path.write_text(tomlkit.dumps(doc))
        return True

    except ImportError:
        import tomllib

        with open(path, "rb") as f:
            data = tomllib.load(f)

        parts = section.split(".")
        target = data
        for part in parts:
            if part not in target:
                return False
            target = target[part]

        if key not in target:
            return False
        del target[key]
        _write_toml_fallback(path, data)
        return True


def _write_toml_fallback(path: Path, data: dict) -> None:
    """Write TOML data without tomlkit (loses comments)."""
    lines = []
    _write_section(lines, data, [])
    path.write_text("\n".join(lines) + "\n")


def _write_section(lines: list[str], data: dict, prefix: list[str]) -> None:
    """Recursively write TOML sections."""
    # Write simple key-value pairs first
    for key, value in data.items():
        if isinstance(value, dict):
            continue
        full_key = f'"{key}"' if " " in key or any(c in key for c in "-") else key
        lines.append(f"{full_key} = {_format_value(value)}")

    # Then write sub-tables
    for key, value in data.items():
        if not isinstance(value, dict):
            continue
        section_path = [*prefix, key]
        lines.append("")
        lines.append(f"[{'.'.join(section_path)}]")
        _write_section(lines, value, section_path)


def _format_value(value) -> str:
    """Format a Python value as TOML."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, list):
        items = ", ".join(_format_value(v) for v in value)
        return f"[{items}]"
    return str(value)
