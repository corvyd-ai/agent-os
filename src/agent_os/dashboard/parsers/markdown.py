"""Parse structured markdown files (drives, journals, etc.)."""

import re


def parse_drives(text: str) -> list[dict]:
    """Parse the drives.md file into structured drive objects."""
    drives = []
    sections = re.split(r"^## ", text, flags=re.MULTILINE)

    for section in sections[1:]:  # Skip header
        lines = section.strip().split("\n")
        name = lines[0].strip()

        # Skip non-drive sections (like the quote block)
        if not name or name.startswith(">"):
            continue

        drive: dict = {"name": name, "tension": "unknown", "state": "", "last_updated": ""}

        body_lines = []
        for line in lines[1:]:
            line = line.strip()
            if line.startswith("**Tension**:"):
                drive["tension"] = line.split(":", 1)[1].strip().strip("*")
            elif line.startswith("**Current state**:"):
                drive["state"] = line.split(":", 1)[1].strip()
            elif line.startswith("**Last updated**:"):
                drive["last_updated"] = line.split(":", 1)[1].strip()
            elif line.startswith("**What would reduce tension**:"):
                drive["reduce"] = line.split(":", 1)[1].strip()
            else:
                body_lines.append(line)

        drive["body"] = "\n".join(body_lines).strip()
        drives.append(drive)

    return drives


def parse_journal(text: str, max_entries: int = 20) -> list[dict]:
    """Parse a journal.md file into structured entries."""
    entries = []
    sections = text.split("\n## ")

    for section in sections[1:]:  # Skip any file header
        lines = section.strip().split("\n", 1)
        header = lines[0].strip()
        body = lines[1].strip() if len(lines) > 1 else ""
        entries.append({"header": header, "body": body})

    # Return most recent entries
    return entries[-max_entries:]
