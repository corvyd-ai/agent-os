"""Cost API routes."""

from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Query

from ..config import AGENT_ALIASES, COSTS_DIR, company_date
from ..parsers.jsonl import parse_jsonl_file

router = APIRouter(prefix="/api/costs", tags=["costs"])


def _normalize_agent(agent_id: str) -> str:
    return AGENT_ALIASES.get(agent_id, agent_id)


def _short_name(agent_id: str) -> str:
    parts = agent_id.split("-", 2)
    return parts[2].replace("-", " ").title() if len(parts) > 2 else agent_id


@router.get("/daily")
async def daily_costs(days: int = Query(7, description="Number of days to show")):
    """Get daily cost breakdown by agent for the last N days."""
    today = company_date()
    result = []

    for i in range(days):
        date = today - timedelta(days=i)
        date_str = str(date)
        entries = parse_jsonl_file(COSTS_DIR / f"{date_str}.jsonl")

        # Normalize agent IDs
        for e in entries:
            e["agent"] = _normalize_agent(e.get("agent", ""))

        # Aggregate by agent
        by_agent: dict[str, float] = defaultdict(float)
        total = 0.0
        invocations = 0
        for e in entries:
            cost = e.get("cost_usd", 0)
            by_agent[e["agent"]] += cost
            total += cost
            invocations += 1

        result.append({
            "date": date_str,
            "total": round(total, 4),
            "invocations": invocations,
            "by_agent": {k: round(v, 4) for k, v in sorted(by_agent.items())},
        })

    result.reverse()  # Chronological order
    return result


@router.get("/summary")
async def cost_summary(days: int = Query(7)):
    """Get aggregated cost summary."""
    today = company_date()
    by_agent: dict[str, float] = defaultdict(float)
    by_task_type: dict[str, float] = defaultdict(float)
    total = 0.0
    total_invocations = 0
    daily_totals = []

    for i in range(days):
        date = today - timedelta(days=i)
        entries = parse_jsonl_file(COSTS_DIR / f"{date}.jsonl")
        day_total = 0.0

        for e in entries:
            agent = _normalize_agent(e.get("agent", ""))
            cost = e.get("cost_usd", 0)
            task = e.get("task", "unknown")

            by_agent[agent] += cost
            by_task_type[task] += cost
            total += cost
            day_total += cost
            total_invocations += 1

        daily_totals.append({"date": str(date), "total": round(day_total, 4)})

    daily_totals.reverse()

    return {
        "total": round(total, 4),
        "days": days,
        "invocations": total_invocations,
        "avg_daily": round(total / max(days, 1), 4),
        "by_agent": {
            k: {"total": round(v, 4), "name": _short_name(k)}
            for k, v in sorted(by_agent.items())
        },
        "by_task_type": {k: round(v, 4) for k, v in sorted(by_task_type.items(), key=lambda x: -x[1])},
        "daily_totals": daily_totals,
    }
