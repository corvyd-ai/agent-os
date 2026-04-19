"""`agent-os cost` — spend rollup across a configurable window.

Separates aggregation (pure data) from rendering so tests can assert
numbers deterministically and the render path can use plotext charts
for human consumption.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from .config import Config
from .formatting import _json_default, bar_chart, supports_color
from .parsers.jsonl import parse_jsonl_file


def _classify_task(task: str | None) -> str:
    """Bucket a cost entry's `task` field into one of:
    task, drive, standing-order, dream, other.
    """
    t = task or ""
    if t.startswith("task-"):
        return "task"
    if t.startswith("drive"):
        return "drive"
    if t.startswith("standing-order"):
        return "standing-order"
    if t.startswith("dream"):
        return "dream"
    return "other"


def aggregate_costs(config: Config, *, days: int = 7) -> dict:
    """Return {daily, by_agent, by_task_type, total_usd, period_days}."""
    today = datetime.now(config.tz).date()

    daily: dict[str, float] = {}
    by_agent: dict[str, float] = {}
    by_task_type: dict[str, float] = {}
    total = 0.0

    for i in range(days):
        date = today - timedelta(days=i)
        date_iso = date.isoformat()
        entries = parse_jsonl_file(config.costs_dir / f"{date_iso}.jsonl")
        if not entries:
            continue
        day_sum = 0.0
        for entry in entries:
            cost = float(entry.get("cost_usd", 0.0))
            agent = str(entry.get("agent") or "unknown")
            kind = _classify_task(entry.get("task"))

            day_sum += cost
            by_agent[agent] = by_agent.get(agent, 0.0) + cost
            by_task_type[kind] = by_task_type.get(kind, 0.0) + cost
            total += cost

        if day_sum > 0:
            daily[date_iso] = round(day_sum, 4)

    return {
        "period_days": days,
        "total_usd": round(total, 4),
        "daily": daily,
        "by_agent": {k: round(v, 4) for k, v in by_agent.items()},
        "by_task_type": {k: round(v, 4) for k, v in by_task_type.items()},
    }


def render_cost(config: Config, *, days: int = 7, by: str = "agent") -> str:
    report = aggregate_costs(config, days=days)
    lines: list[str] = [
        f"Spend over the last {days} day(s): ${report['total_usd']:.2f}",
        "",
    ]

    if report["daily"]:
        lines.append("Daily:")
        for date in sorted(report["daily"]):
            lines.append(f"  {date}  ${report['daily'][date]:.2f}")
        lines.append("")

    dim = report["by_agent"] if by == "agent" else report["by_task_type"]
    if dim:
        header = "Agent" if by == "agent" else "Task type"
        lines.append(f"{header:<32} {'spend':>10}")
        lines.append("-" * 44)
        for key in sorted(dim, key=lambda k: dim[k], reverse=True):
            lines.append(f"{key:<32} {'$' + format(dim[key], '.2f'):>10}")
        lines.append("")

    rendered = "\n".join(lines) + "\n"

    # Draw the chart if the terminal can render it. Skip in piped/NO_COLOR mode.
    if report["daily"] and supports_color():
        try:
            labels = sorted(report["daily"])
            values = [report["daily"][d] for d in labels]
            bar_chart(labels, values, title=f"Daily spend (last {days}d)")
        except Exception:
            pass

    return rendered


def render_cost_json(config: Config, *, days: int = 7) -> str:
    return json.dumps(aggregate_costs(config, days=days), indent=2, default=_json_default)
