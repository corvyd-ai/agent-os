"""Overview API — single endpoint for the home page."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter

from ..config import (
    AGENT_ALIASES,
    AGENT_IDS,
    AGENTS_STATE_DIR,
    COSTS_DIR,
    DRIVES_FILE,
    LOGS_DIR,
    TASK_STATUS_DIRS,
    TASKS_IN_PROGRESS,
    TASKS_QUEUED,
    company_date,
    company_today,
)
from ..parsers.frontmatter import parse_frontmatter
from ..parsers.jsonl import parse_jsonl_file
from ..parsers.markdown import parse_drives

# Executive summary — written by the Steward during health scans
EXECUTIVE_SUMMARY_FILE = AGENTS_STATE_DIR / "agent-000-steward" / "executive-summary.md"

router = APIRouter(prefix="/api", tags=["overview"])


def _short_name(agent_id: str) -> str:
    parts = agent_id.split("-", 2)
    return parts[2].replace("-", " ").title() if len(parts) > 2 else agent_id


def _normalize_agent(agent_id: str) -> str:
    return AGENT_ALIASES.get(agent_id, agent_id)


@router.get("/overview")
async def overview():
    """Aggregated overview data for the home page."""
    today = company_today()

    # --- Agent summaries ---
    agents = []
    for agent_id in AGENT_IDS:
        log_file = LOGS_DIR / agent_id / f"{today}.jsonl"
        logs = parse_jsonl_file(log_file)
        last_active = logs[-1].get("timestamp") if logs else None

        # Today's cost
        cost_entries = parse_jsonl_file(COSTS_DIR / f"{today}.jsonl")
        agent_costs = [e for e in cost_entries if _normalize_agent(e.get("agent", "")) == agent_id]
        cost_today = sum(e.get("cost_usd", 0) for e in agent_costs)
        cycles = len([e for e in agent_costs if e.get("cost_usd", 0) > 0])

        # Current task
        current_task = None
        for f in TASKS_IN_PROGRESS.glob("*.md"):
            meta, _ = parse_frontmatter(f)
            if meta.get("assigned_to", "") == agent_id:
                current_task = {"id": meta.get("id"), "title": meta.get("title")}
                break

        agents.append({
            "id": agent_id,
            "name": _short_name(agent_id),
            "last_active": last_active,
            "cost_today": round(cost_today, 4),
            "cycles_today": cycles,
            "current_task": current_task,
        })

    # --- Task queue summary ---
    task_counts = {}
    for status, directory in TASK_STATUS_DIRS.items():
        if directory.exists():
            task_counts[status] = len(list(directory.glob("*.md")))
        else:
            task_counts[status] = 0

    # --- 7-day cost sparkline ---
    cost_trend = []
    for i in range(7):
        date = company_date() - timedelta(days=i)
        entries = parse_jsonl_file(COSTS_DIR / f"{date}.jsonl")
        day_total = sum(e.get("cost_usd", 0) for e in entries)
        by_agent: dict[str, float] = defaultdict(float)
        for e in entries:
            by_agent[_normalize_agent(e.get("agent", ""))] += e.get("cost_usd", 0)
        cost_trend.append({
            "date": str(date),
            "total": round(day_total, 4),
            "by_agent": {k: round(v, 4) for k, v in by_agent.items()},
        })
    cost_trend.reverse()

    # --- Drives ---
    drives = []
    if DRIVES_FILE.exists():
        drives = parse_drives(DRIVES_FILE.read_text())

    # --- Human task queue ---
    human_tasks = []
    if TASKS_QUEUED.exists():
        for f in sorted(TASKS_QUEUED.glob("*.md")):
            meta, _body = parse_frontmatter(f)
            if meta.get("assigned_to") == "human":
                human_tasks.append({
                    "id": meta.get("id"),
                    "title": meta.get("title"),
                    "priority": meta.get("priority", "medium"),
                    "created_by": meta.get("created_by", ""),
                    "created": meta.get("created", ""),
                })

    # --- Recent activity (merged timeline, always hide idle) ---
    activity = []
    for agent_id in AGENT_IDS:
        log_file = LOGS_DIR / agent_id / f"{today}.jsonl"
        for entry in parse_jsonl_file(log_file):
            entry.setdefault("agent", agent_id)
            if entry.get("action") != "cycle_idle":
                activity.append(entry)
    activity.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    recent_activity = activity[:20]

    # --- Executive summary (written by the Steward) ---
    executive_summary = None
    if EXECUTIVE_SUMMARY_FILE.exists():
        content = EXECUTIVE_SUMMARY_FILE.read_text().strip()
        if content:
            stat = EXECUTIVE_SUMMARY_FILE.stat()
            last_modified = datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat()
            executive_summary = {
                "content": content,
                "last_updated": last_modified,
            }

    return {
        "executive_summary": executive_summary,
        "agents": agents,
        "task_counts": task_counts,
        "cost_trend": cost_trend,
        "drives": drives,
        "human_tasks": human_tasks,
        "recent_activity": recent_activity,
    }
