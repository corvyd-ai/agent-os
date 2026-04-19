"""`agent-os agent` — list and show registered agents."""

from __future__ import annotations

import json
from datetime import datetime

from .config import Config
from .formatting import _json_default
from .parsers.jsonl import parse_jsonl_file
from .registry import list_agents, load_agent


def agent_exists(config: Config, agent_id: str) -> bool:
    """True if `agent_id` has a registry file."""
    registry = config.registry_dir
    if not registry.exists():
        return False
    return (registry / f"{agent_id}.md").exists()


def _today(cfg: Config) -> str:
    return datetime.now(cfg.tz).date().isoformat()


def _today_cost(cfg: Config, agent_id: str) -> float:
    entries = parse_jsonl_file(cfg.costs_dir / f"{_today(cfg)}.jsonl")
    return round(sum(e.get("cost_usd", 0.0) for e in entries if e.get("agent") == agent_id), 4)


def _recent_log_lines(cfg: Config, agent_id: str, *, limit: int = 5) -> list[str]:
    entries = parse_jsonl_file(cfg.logs_dir / agent_id / f"{_today(cfg)}.jsonl")
    entries = [e for e in entries if e.get("action") not in {"cycle_idle", "cycle_skipped"}]
    entries = entries[-limit:]
    out: list[str] = []
    for e in entries:
        action = e.get("action", "?")
        ref = e.get("task") or e.get("msg") or ""
        suffix = f" ({ref})" if ref else ""
        out.append(f"{e.get('timestamp', '')[:19]} — {action}{suffix}")
    return out


def render_agent_list(config: Config) -> str:
    agents = list_agents(config=config)
    if not agents:
        return "No agents registered.\n"
    lines = [f"{'agent id':<32} {'role':<32} {'today spend':>12}", "-" * 78]
    for ac in agents:
        lines.append(f"{ac.agent_id:<32} {ac.role:<32} ${_today_cost(config, ac.agent_id):>11.2f}")
    return "\n".join(lines) + "\n"


def render_agent_list_json(config: Config) -> str:
    agents = list_agents(config=config)
    payload = [
        {
            "agent_id": ac.agent_id,
            "name": ac.name,
            "role": ac.role,
            "model": ac.model,
            "today_cost_usd": _today_cost(config, ac.agent_id),
        }
        for ac in agents
    ]
    return json.dumps(payload, indent=2, default=_json_default)


def render_agent_show(config: Config, agent_id: str) -> str:
    try:
        ac = load_agent(agent_id, config=config)
    except FileNotFoundError:
        return f"Agent '{agent_id}' not found. Run `agent-os agent list` to see registered agents.\n"

    lines = [
        f"# {ac.agent_id}",
        "",
        f"- **name:** {ac.name}",
        f"- **role:** {ac.role}",
        f"- **model:** {ac.model}",
        f"- **today spend:** ${_today_cost(config, ac.agent_id):.2f}",
        "",
    ]

    recent = _recent_log_lines(config, ac.agent_id)
    if recent:
        lines.append("## Recent activity (today)")
        for line in recent:
            lines.append(f"- {line}")
        lines.append("")

    if ac.system_body.strip():
        lines.append("## Identity")
        lines.append(ac.system_body.strip())
        lines.append("")

    return "\n".join(lines) + "\n"
