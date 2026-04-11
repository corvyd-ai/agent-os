"""System Notes API routes (formerly Feedback).

Operational notes directed at agents. The exec chair writes notes,
agents read them during their cycles. Files live in the agent-os
filesystem as markdown with YAML frontmatter.

The underlying filesystem directory remains /agents/messages/feedback/
for backward compatibility — this module abstracts the path.
"""

import re
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import FEEDBACK_DIR
from ..parsers.frontmatter import parse_frontmatter_file

router = APIRouter(prefix="/api/notes", tags=["notes"])


def _next_id() -> str:
    """Generate next sequential feedback ID for today."""
    today = datetime.now(UTC).strftime("%Y-%m%d")
    prefix = f"feedback-{today}-"
    existing = sorted(FEEDBACK_DIR.glob(f"{prefix}*.md")) if FEEDBACK_DIR.exists() else []
    if existing:
        last_num = int(existing[-1].stem.split("-")[-1])
        return f"{prefix}{last_num + 1:03d}"
    return f"{prefix}001"


def _parse_responses(body: str) -> list[dict]:
    """Extract agent/human response sections from the markdown body."""
    responses = []
    # Match ## agent-id — ISO-datetime sections
    pattern = r"^## (.+?) — (\d{4}-\d{2}-\d{2}T[\d:.+Z-]+)\s*\n(.*?)(?=^## |\Z)"
    for m in re.finditer(pattern, body, re.MULTILINE | re.DOTALL):
        responses.append(
            {
                "author": m.group(1).strip(),
                "timestamp": m.group(2).strip(),
                "text": m.group(3).strip(),
            }
        )
    return responses


@router.get("")
async def list_notes():
    """List all system notes, newest first."""
    if not FEEDBACK_DIR.exists():
        return []

    results = []
    for f in sorted(FEEDBACK_DIR.glob("*.md"), reverse=True):
        item = parse_frontmatter_file(f)
        item["responses"] = _parse_responses(item.get("body", ""))
        results.append(item)

    return results


@router.get("/{note_id}")
async def get_note(note_id: str):
    """Get a single system note."""
    if not FEEDBACK_DIR.exists():
        raise HTTPException(status_code=404, detail="Note not found")

    matches = list(FEEDBACK_DIR.glob(f"{note_id}*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Note not found")

    item = parse_frontmatter_file(matches[0])
    item["responses"] = _parse_responses(item.get("body", ""))
    return item


class NoteCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)
    tags: list[str] = Field(default_factory=list)


@router.post("")
async def create_note(payload: NoteCreate):
    """Create a new system note."""
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)

    fb_id = _next_id()
    now = datetime.now(UTC).isoformat()
    tags_yaml = f"[{', '.join(payload.tags)}]" if payload.tags else "[]"

    content = f"""---
id: {fb_id}
author: human
created: {now}
status: open
tags: {tags_yaml}
---

{payload.text.strip()}
"""

    path = FEEDBACK_DIR / f"{fb_id}.md"
    path.write_text(content)
    return {"id": fb_id, "status": "created"}


class NoteRespond(BaseModel):
    author: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1, max_length=5000)


@router.post("/{note_id}/respond")
async def respond_to_note(note_id: str, payload: NoteRespond):
    """Append a response to a system note."""
    if not FEEDBACK_DIR.exists():
        raise HTTPException(status_code=404, detail="Note not found")

    matches = list(FEEDBACK_DIR.glob(f"{note_id}*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Note not found")

    path = matches[0]
    now = datetime.now(UTC).isoformat()
    response_section = f"\n\n## {payload.author} — {now}\n\n{payload.text.strip()}\n"
    path.write_text(path.read_text() + response_section)

    return {"status": "response_added"}


class NoteStatusUpdate(BaseModel):
    status: str = Field(..., pattern=r"^(open|acknowledged|addressed)$")


@router.patch("/{note_id}")
async def update_note_status(note_id: str, payload: NoteStatusUpdate):
    """Update the status of a system note."""
    if not FEEDBACK_DIR.exists():
        raise HTTPException(status_code=404, detail="Note not found")

    matches = list(FEEDBACK_DIR.glob(f"{note_id}*"))
    if not matches:
        raise HTTPException(status_code=404, detail="Note not found")

    path = matches[0]
    text = path.read_text()
    text = re.sub(r"^status:\s*\w+", f"status: {payload.status}", text, count=1, flags=re.MULTILINE)
    path.write_text(text)

    return {"status": payload.status}
