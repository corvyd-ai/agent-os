"""agent-os budget — daily/weekly/monthly cost governance with circuit breaker.

Reads existing cost JSONL files (finance/costs/YYYY-MM-DD.jsonl) to compute
aggregate spend. No new state store — the cost log IS the budget ledger.

Usage:
    from agent_os.budget import check_budget, check_agent_budget, get_period_costs

    status = check_budget(config=cfg)
    if status.circuit_breaker_tripped:
        print(f"Daily cap reached: ${status.daily_spent:.2f}")
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import Config, get_config


@dataclass(frozen=True)
class BudgetStatus:
    """Snapshot of budget state."""

    daily_spent: float
    daily_cap: float
    daily_remaining: float
    daily_pct: float
    weekly_spent: float
    weekly_cap: float
    monthly_spent: float
    monthly_cap: float
    circuit_breaker_tripped: bool


def _read_daily_costs(date_str: str, *, config: Config | None = None) -> list[dict]:
    """Read all cost entries for a given date."""
    cfg = config or get_config()
    cost_file = cfg.costs_dir / f"{date_str}.jsonl"
    if not cost_file.exists():
        return []
    entries = []
    for line in cost_file.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _sum_costs(entries: list[dict]) -> float:
    """Sum cost_usd from a list of cost entries."""
    return sum(e.get("cost_usd", 0.0) for e in entries)


def _sum_agent_costs(entries: list[dict], agent_id: str) -> float:
    """Sum cost_usd for a specific agent from a list of cost entries."""
    return sum(e.get("cost_usd", 0.0) for e in entries if e.get("agent") == agent_id)


def get_daily_costs(date_str: str | None = None, *, config: Config | None = None) -> float:
    """Get total spend for a single day."""
    cfg = config or get_config()
    if date_str is None:
        date_str = datetime.now(cfg.tz).strftime("%Y-%m-%d")
    entries = _read_daily_costs(date_str, config=cfg)
    return _sum_costs(entries)


def get_period_costs(days: int, *, config: Config | None = None) -> float:
    """Sum costs over the last N days from JSONL files."""
    cfg = config or get_config()
    total = 0.0
    today = datetime.now(cfg.tz).date()
    for i in range(days):
        date = today - timedelta(days=i)
        total += get_daily_costs(date.isoformat(), config=config)
    return total


def check_budget(*, config: Config | None = None) -> BudgetStatus:
    """Read today's cost JSONL, sum it, compare to daily cap.

    Returns a BudgetStatus with spent, cap, remaining, pct, and whether
    the circuit breaker has tripped.
    """
    cfg = config or get_config()

    daily_spent = get_daily_costs(config=cfg)
    daily_cap = cfg.daily_budget_cap_usd
    daily_remaining = max(0.0, daily_cap - daily_spent)
    daily_pct = (daily_spent / daily_cap * 100) if daily_cap > 0 else 0.0

    weekly_spent = get_period_costs(7, config=cfg)
    weekly_cap = cfg.weekly_budget_cap_usd

    monthly_spent = get_period_costs(30, config=cfg)
    monthly_cap = cfg.monthly_budget_cap_usd

    tripped = daily_spent >= daily_cap or weekly_spent >= weekly_cap or monthly_spent >= monthly_cap

    return BudgetStatus(
        daily_spent=daily_spent,
        daily_cap=daily_cap,
        daily_remaining=daily_remaining,
        daily_pct=daily_pct,
        weekly_spent=weekly_spent,
        weekly_cap=weekly_cap,
        monthly_spent=monthly_spent,
        monthly_cap=monthly_cap,
        circuit_breaker_tripped=tripped,
    )


def check_agent_budget(agent_id: str, *, config: Config | None = None) -> tuple[bool, float]:
    """Check if a specific agent is within its daily cap.

    Returns (within_budget, spent_today).
    If no per-agent cap is configured, always returns within budget.
    """
    cfg = config or get_config()
    cap = cfg.agent_daily_caps.get(agent_id)
    if cap is None:
        return True, 0.0

    today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
    entries = _read_daily_costs(today, config=cfg)
    spent = _sum_agent_costs(entries, agent_id)
    return spent < cap, spent


def format_budget_report(*, config: Config | None = None) -> str:
    """Format a human-readable budget report for CLI output."""
    status = check_budget(config=config)
    cfg = config or get_config()

    lines = []
    lines.append("Budget Status")
    lines.append("=" * 50)

    # Daily
    bar_width = 30
    filled = int(min(status.daily_pct / 100, 1.0) * bar_width)
    bar = "#" * filled + "-" * (bar_width - filled)
    marker = "!! TRIPPED" if status.daily_spent >= status.daily_cap else ""
    lines.append(
        f"Daily:   [{bar}] ${status.daily_spent:.2f} / ${status.daily_cap:.2f} ({status.daily_pct:.0f}%) {marker}"
    )

    # Weekly
    weekly_pct = (status.weekly_spent / status.weekly_cap * 100) if status.weekly_cap > 0 else 0.0
    filled = int(min(weekly_pct / 100, 1.0) * bar_width)
    bar = "#" * filled + "-" * (bar_width - filled)
    marker = "!! TRIPPED" if status.weekly_spent >= status.weekly_cap else ""
    lines.append(f"Weekly:  [{bar}] ${status.weekly_spent:.2f} / ${status.weekly_cap:.2f} ({weekly_pct:.0f}%) {marker}")

    # Monthly
    monthly_pct = (status.monthly_spent / status.monthly_cap * 100) if status.monthly_cap > 0 else 0.0
    filled = int(min(monthly_pct / 100, 1.0) * bar_width)
    bar = "#" * filled + "-" * (bar_width - filled)
    marker = "!! TRIPPED" if status.monthly_spent >= status.monthly_cap else ""
    lines.append(
        f"Monthly: [{bar}] ${status.monthly_spent:.2f} / ${status.monthly_cap:.2f} ({monthly_pct:.0f}%) {marker}"
    )

    # Circuit breaker
    lines.append("")
    if status.circuit_breaker_tripped:
        lines.append("CIRCUIT BREAKER: TRIPPED - agent invocations will be blocked")
    else:
        lines.append(f"Circuit breaker: OK (${status.daily_remaining:.2f} remaining today)")

    # Per-agent caps
    if cfg.agent_daily_caps:
        lines.append("")
        lines.append("Per-Agent Daily Caps")
        lines.append("-" * 50)
        for agent_id, cap in sorted(cfg.agent_daily_caps.items()):
            within, spent = check_agent_budget(agent_id, config=cfg)
            status_str = "OK" if within else "OVER"
            lines.append(f"  {agent_id}: ${spent:.2f} / ${cap:.2f} [{status_str}]")

    return "\n".join(lines)
