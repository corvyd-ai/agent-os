"""Agent API routes."""

from fastapi import APIRouter, Query

from ..config import (
    AGENT_ALIASES,
    AGENT_IDS,
    AGENTS_STATE_DIR,
    COSTS_DIR,
    LOGS_DIR,
    MESSAGES_DIR,
    REGISTRY_DIR,
    TASKS_IN_PROGRESS,
    company_today,
)
from ..parsers.frontmatter import parse_frontmatter, parse_frontmatter_file
from ..parsers.jsonl import parse_jsonl_file

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _short_name(agent_id: str) -> str:
    parts = agent_id.split("-", 2)
    return parts[2].replace("-", " ").title() if len(parts) > 2 else agent_id


def _agent_summary(agent_id: str) -> dict:
    """Build summary stats for an agent."""
    today = company_today()

    # Registry info
    reg_file = REGISTRY_DIR / f"{agent_id}.md"
    reg_meta = {}
    if reg_file.exists():
        reg_meta, _ = parse_frontmatter(reg_file)

    # Today's logs
    log_file = LOGS_DIR / agent_id / f"{today}.jsonl"
    logs = parse_jsonl_file(log_file)

    # Today's costs
    cost_entries = parse_jsonl_file(COSTS_DIR / f"{today}.jsonl")
    agent_costs = [e for e in cost_entries if _normalize_agent(e.get("agent", "")) == agent_id]
    cost_today = sum(e.get("cost_usd", 0) for e in agent_costs)
    cycles_today = len([e for e in agent_costs if e.get("cost_usd", 0) > 0])

    # Last active
    last_active = None
    if logs:
        last_active = logs[-1].get("timestamp")

    # Current task
    current_task = None
    for f in TASKS_IN_PROGRESS.glob("*.md"):
        meta, _ = parse_frontmatter(f)
        assigned = meta.get("assigned_to", "")
        if assigned == agent_id or agent_id.startswith(assigned + "-"):
            current_task = {"id": meta.get("id"), "title": meta.get("title")}
            break

    # Inbox count
    inbox_dir = MESSAGES_DIR / agent_id / "inbox"
    inbox_count = len(list(inbox_dir.glob("*.md"))) if inbox_dir.exists() else 0

    return {
        "id": agent_id,
        "name": reg_meta.get("name", _short_name(agent_id)),
        "role": reg_meta.get("role", ""),
        "status": reg_meta.get("status", "unknown"),
        "short_name": _short_name(agent_id),
        "last_active": last_active,
        "current_task": current_task,
        "cost_today": round(cost_today, 4),
        "cycles_today": cycles_today,
        "inbox_count": inbox_count,
    }


def _normalize_agent(agent_id: str) -> str:
    return AGENT_ALIASES.get(agent_id, agent_id)


@router.get("")
async def list_agents():
    """List all agents with summary stats."""
    return [_agent_summary(aid) for aid in AGENT_IDS]


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    """Get detailed agent info including soul and working memory."""
    summary = _agent_summary(agent_id)

    # Soul
    soul_file = AGENTS_STATE_DIR / agent_id / "soul.md"
    soul = soul_file.read_text() if soul_file.exists() else ""

    # Working memory
    wm_file = AGENTS_STATE_DIR / agent_id / "working-memory.md"
    working_memory = wm_file.read_text() if wm_file.exists() else ""

    # Registry (full)
    reg_file = REGISTRY_DIR / f"{agent_id}.md"
    registry = ""
    if reg_file.exists():
        _, registry = parse_frontmatter(reg_file)

    # Journal (last entries)
    journal_file = LOGS_DIR / agent_id / "journal.md"
    journal = journal_file.read_text() if journal_file.exists() else ""

    return {
        **summary,
        "soul": soul,
        "working_memory": working_memory,
        "registry": registry,
        "journal": journal,
    }


@router.get("/{agent_id}/logs")
async def get_agent_logs(
    agent_id: str,
    date: str | None = Query(None, description="Date in YYYY-MM-DD format"),
    hide_idle: bool = Query(True),
):
    """Get agent JSONL logs for a specific date (defaults to today)."""
    if not date:
        date = company_today()
    log_file = LOGS_DIR / agent_id / f"{date}.jsonl"
    entries = parse_jsonl_file(log_file)
    if hide_idle:
        entries = [e for e in entries if e.get("action") != "cycle_idle"]
    return entries


@router.get("/{agent_id}/messages")
async def get_agent_messages(agent_id: str):
    """Get agent inbox and outbox messages."""
    inbox_dir = MESSAGES_DIR / agent_id / "inbox"
    outbox_dir = MESSAGES_DIR / agent_id / "outbox"

    inbox = []
    if inbox_dir.exists():
        for f in sorted(inbox_dir.glob("*.md")):
            inbox.append(parse_frontmatter_file(f))

    outbox = []
    if outbox_dir.exists():
        for f in sorted(outbox_dir.glob("*.md"), reverse=True):
            outbox.append(parse_frontmatter_file(f))

    return {"inbox": inbox, "outbox": outbox[:20]}
