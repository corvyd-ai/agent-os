"""`agent-os health` — per-agent and system health scores.

Thin wrapper around agent_os.metrics that renders either a human-readable
summary (table of composite + sub-scores) or machine-readable JSON.
"""

from __future__ import annotations

import json

from .config import Config
from .formatting import _json_default
from .metrics import compute_all_health


def _filter_agents(report: dict, agent: str | None) -> dict:
    if agent is None:
        return report
    scoped = {k: v for k, v in report.get("agents", {}).items() if k == agent}
    return {**report, "agents": scoped}


def render_health(config: Config, *, days: int = 7, agent: str | None = None) -> str:
    """Human-readable health summary as a string.

    Uses a simple table-ish layout so the output is readable even when piped.
    """
    report = _filter_agents(compute_all_health(days=days, config=config), agent)

    lines: list[str] = [
        f"Health snapshot ({days}-day window)",
        f"System composite: {report['system_composite']}/100",
        "",
    ]
    agents = report.get("agents", {})
    if not agents:
        lines.append("No agents registered.")
        return "\n".join(lines) + "\n"

    # Fixed-width table so it stays aligned in any terminal width.
    lines.append(f"{'agent':<32} {'composite':>10} {'autonomy':>10} {'effect':>10} {'effic':>10} {'sysh':>10}")
    lines.append("-" * 86)
    for agent_id in sorted(agents):
        row = agents[agent_id]
        lines.append(
            f"{agent_id:<32} "
            f"{row['composite_score']:>10} "
            f"{row['autonomy']['score']:>10} "
            f"{row['effectiveness']['score']:>10} "
            f"{row['efficiency']['score']:>10} "
            f"{row['system_health']['score']:>10}"
        )
    return "\n".join(lines) + "\n"


def render_health_json(config: Config, *, days: int = 7, agent: str | None = None) -> str:
    report = _filter_agents(compute_all_health(days=days, config=config), agent)
    return json.dumps(report, indent=2, default=_json_default)
