"""Message API routes — broadcasts, inboxes, threads."""

from fastapi import APIRouter

from ..config import AGENT_IDS, BROADCAST_DIR, HUMAN_INBOX, MESSAGES_DIR, THREADS_DIR
from ..parsers.frontmatter import parse_frontmatter_file

router = APIRouter(prefix="/api/messages", tags=["messages"])


@router.get("/broadcast")
async def list_broadcasts():
    """List active broadcast messages."""
    if not BROADCAST_DIR.exists():
        return []
    results = []
    for f in sorted(BROADCAST_DIR.glob("*.md"), reverse=True):
        results.append(parse_frontmatter_file(f))
    return results


@router.get("/threads")
async def list_threads():
    """List active conversation threads."""
    if not THREADS_DIR.exists():
        return []
    results = []
    for f in sorted(THREADS_DIR.glob("*.md"), reverse=True):
        if f.is_dir():
            continue
        results.append(parse_frontmatter_file(f))
    return results


@router.get("/human")
async def human_inbox():
    """List messages in the human inbox."""
    if not HUMAN_INBOX.exists():
        return []
    results = []
    for f in sorted(HUMAN_INBOX.glob("*.md"), reverse=True):
        results.append(parse_frontmatter_file(f))
    return results


@router.get("/inboxes")
async def inbox_summary():
    """Get unread message counts for all agent inboxes + human."""
    counts = {}
    for agent_id in AGENT_IDS:
        inbox = MESSAGES_DIR / agent_id / "inbox"
        counts[agent_id] = len(list(inbox.glob("*.md"))) if inbox.exists() else 0

    if HUMAN_INBOX.exists():
        counts["human"] = len(list(HUMAN_INBOX.glob("*.md")))
    else:
        counts["human"] = 0

    return counts
