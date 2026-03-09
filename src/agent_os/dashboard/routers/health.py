"""Health metrics and timeline API routes.

Provides:
- /api/timeline — merged activity log timeline
- /api/health — basic system health check (legacy)
- /api/health/metrics — full health metrics with 7/30 day trends
- /api/health/metrics/{agent_id} — per-agent health metrics
- /api/health/summary — lightweight summary for overview page card
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Query

from ..config import AGENT_IDS, LOGS_DIR, company_today
from ..metrics import compute_agent_health, compute_health_with_trends
from ..parsers.jsonl import parse_jsonl_file

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/timeline")
async def timeline(
    date: str | None = Query(None),
    agent: str | None = Query(None),
    limit: int = Query(100),
    hide_idle: bool = Query(True),
):
    """Get merged timeline of all agent activity."""
    if not date:
        date = company_today()

    agents_to_scan = [agent] if agent else AGENT_IDS
    entries = []

    for agent_id in agents_to_scan:
        log_file = LOGS_DIR / agent_id / f"{date}.jsonl"
        for entry in parse_jsonl_file(log_file):
            entry.setdefault("agent", agent_id)
            entries.append(entry)

    if hide_idle:
        entries = [e for e in entries if e.get("action") != "cycle_idle"]

    # Sort by timestamp descending (most recent first)
    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return entries[:limit]


@router.get("/health")
async def system_health():
    """Basic system health check (legacy — kept for backward compatibility)."""
    today = company_today()

    agent_status = {}
    for agent_id in AGENT_IDS:
        log_file = LOGS_DIR / agent_id / f"{today}.jsonl"
        logs = parse_jsonl_file(log_file)
        last_active = logs[-1].get("timestamp") if logs else None
        agent_status[agent_id] = {
            "active": bool(logs),
            "last_active": last_active,
            "entries_today": len(logs),
        }

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "agents": agent_status,
    }


@router.get("/health/metrics")
async def health_metrics():
    """Full health metrics with 7-day and 30-day trend data.

    Returns per-agent scores across five categories (autonomy, effectiveness,
    efficiency, governance, system health) plus system-wide composite scores
    and trend direction (improving/stable/declining).
    """
    return compute_health_with_trends()


@router.get("/health/metrics/{agent_id}")
async def agent_health_metrics(
    agent_id: str,
    days: int = Query(7, ge=1, le=90),
):
    """Health metrics for a single agent over a configurable period."""
    if agent_id not in AGENT_IDS:
        return {"error": f"Unknown agent: {agent_id}"}
    return compute_agent_health(agent_id, days)


@router.get("/health/summary")
async def health_summary():
    """Lightweight health summary for the overview page card.

    Returns just composite scores and trend direction — no detailed breakdowns.
    """
    data = compute_health_with_trends()

    agent_summaries = {}
    for agent_id in AGENT_IDS:
        trend = data["trends"]["agents"].get(agent_id, {})
        agent_summaries[agent_id] = {
            "score": trend.get("score_7d", 0),
            "direction": trend.get("direction", "stable"),
            "delta": trend.get("delta", 0),
        }

    return {
        "system_score": data["trends"]["system"]["score_7d"],
        "system_direction": data["trends"]["system"]["direction"],
        "system_delta": data["trends"]["system"]["delta"],
        "governance_score": data["current"]["governance"]["score"],
        "agents": agent_summaries,
        "computed_at": data["computed_at"],
    }
