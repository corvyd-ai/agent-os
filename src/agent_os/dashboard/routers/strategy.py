"""Strategy API routes — drives, decisions, proposals."""

from fastapi import APIRouter

from ..config import DECISIONS_DIR, DRIVES_FILE, PROPOSALS_ACTIVE, PROPOSALS_DECIDED
from ..parsers.frontmatter import parse_frontmatter_file
from ..parsers.markdown import parse_drives

router = APIRouter(prefix="/api", tags=["strategy"])


@router.get("/drives")
async def get_drives():
    """Get parsed company drives with tension levels."""
    if not DRIVES_FILE.exists():
        return []
    return parse_drives(DRIVES_FILE.read_text())


@router.get("/decisions")
async def list_decisions(limit: int = 20):
    """List recent decisions."""
    if not DECISIONS_DIR.exists():
        return []
    files = sorted(DECISIONS_DIR.glob("*.md"), reverse=True)[:limit]
    return [parse_frontmatter_file(f) for f in files]


@router.get("/proposals")
async def list_proposals():
    """List active and recent decided proposals."""
    result = {"active": [], "decided": []}

    if PROPOSALS_ACTIVE.exists():
        for f in sorted(PROPOSALS_ACTIVE.glob("*.md")):
            result["active"].append(parse_frontmatter_file(f))

    if PROPOSALS_DECIDED.exists():
        for f in sorted(PROPOSALS_DECIDED.glob("*.md"), reverse=True)[:10]:
            result["decided"].append(parse_frontmatter_file(f))

    return result
