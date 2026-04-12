"""agent-os status — compact system overview for the CLI.

Aggregates data from the agent registry, task directories, budget JSONL,
agent logs, and the scheduler to produce a scannable status report.

Usage:
    from agent_os.status import format_status

    output, exit_code = format_status()
    print(output)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .budget import check_budget
from .config import Config, get_config
from .core import list_backlog, read_inbox
from .registry import list_agents
from .scheduler import is_within_operating_hours

# --- Color helpers ---


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


class _Colors:
    def __init__(self, enabled: bool):
        self.enabled = enabled

    def dim(self, text: str) -> str:
        return f"\033[2m{text}\033[0m" if self.enabled else text

    def green(self, text: str) -> str:
        return f"\033[32m{text}\033[0m" if self.enabled else text

    def yellow(self, text: str) -> str:
        return f"\033[33m{text}\033[0m" if self.enabled else text

    def red(self, text: str) -> str:
        return f"\033[31m{text}\033[0m" if self.enabled else text

    def cyan(self, text: str) -> str:
        return f"\033[36m{text}\033[0m" if self.enabled else text

    def bold(self, text: str) -> str:
        return f"\033[1m{text}\033[0m" if self.enabled else text


# --- Data gathering ---


def _relative_time(iso_timestamp: str, *, config: Config) -> str:
    """Convert an ISO timestamp to a human-readable relative time."""
    try:
        ts = datetime.fromisoformat(iso_timestamp)
        now = datetime.now(config.tz)
        delta = now - ts
        total_seconds = int(delta.total_seconds())

        if total_seconds < 0:
            return "just now"
        if total_seconds < 60:
            return "just now"
        if total_seconds < 3600:
            minutes = total_seconds // 60
            return f"{minutes} min ago"
        if total_seconds < 86400:
            hours = total_seconds // 3600
            return f"{hours} hr ago"
        days = total_seconds // 86400
        if days == 1:
            return "yesterday"
        return f"{days} days ago"
    except (ValueError, TypeError):
        return "unknown"


def _get_last_activity(agent_id: str, *, config: Config) -> str | None:
    """Read the last log entry timestamp for an agent from today's JSONL."""
    log_dir = config.logs_dir / agent_id
    if not log_dir.is_dir():
        return None

    today = datetime.now(config.tz).strftime("%Y-%m-%d")
    log_file = log_dir / f"{today}.jsonl"
    if not log_file.exists():
        return None

    last_line = ""
    try:
        for line in log_file.read_text().splitlines():
            if line.strip():
                last_line = line
        if last_line:
            entry = json.loads(last_line)
            return entry.get("timestamp")
    except (json.JSONDecodeError, KeyError, OSError):
        pass
    return None


def _get_in_progress_tasks(*, config: Config) -> dict[str, str]:
    """Map agent_id -> task_id for all in-progress tasks.

    Returns a dict where keys are agent IDs and values are task IDs.
    """
    import yaml

    result: dict[str, str] = {}
    if not config.tasks_in_progress.exists():
        return result

    for task_path in config.tasks_in_progress.glob("*.md"):
        try:
            text = task_path.read_text()
            if not text.startswith("---"):
                continue
            parts = text.split("---", 2)
            if len(parts) < 3:
                continue
            meta = yaml.safe_load(parts[1]) or {}
            assigned = meta.get("assigned_to", "")
            task_id = meta.get("id", task_path.stem)
            if assigned:
                result[assigned] = task_id
        except (yaml.YAMLError, OSError):
            continue
    return result


def _count_dir(directory: Path) -> int:
    """Count .md files in a directory."""
    if not directory.exists():
        return 0
    return sum(1 for f in directory.iterdir() if f.name.endswith(".md"))


def _get_schedule_label(*, config: Config) -> str:
    """Return 'active', 'paused', or 'disabled'."""
    if not config.schedule_enabled:
        return "disabled"
    if not is_within_operating_hours(config=config):
        return "paused"
    return "active"


def _budget_color(c: _Colors, pct: float, text: str) -> str:
    """Color budget text based on usage percentage."""
    if pct >= 80:
        return c.red(text)
    if pct >= 50:
        return c.yellow(text)
    return c.green(text)


# --- Main format function ---


def format_status(*, no_color: bool = False, config: Config | None = None) -> tuple[str, int]:
    """Build the compact status output and compute the exit code.

    Returns (formatted_output, exit_code) where exit_code is 0 if healthy
    and 1 if anything needs human attention.
    """
    cfg = config or get_config()
    use_color = not no_color and _supports_color()
    c = _Colors(use_color)

    lines: list[str] = []

    # --- Header ---
    agents = list_agents(config=cfg)
    schedule_label = _get_schedule_label(config=cfg)
    lines.append("")
    lines.append(f"  {c.bold(cfg.company_name)} ({len(agents)} agents, schedule: {schedule_label})")

    # --- Agent table ---
    if agents:
        in_progress = _get_in_progress_tasks(config=cfg)

        # Compute column widths
        name_width = max(len(a.name) for a in agents)
        name_width = max(name_width, len("Agents"))

        # Build rows first to compute last_cycle column width
        rows: list[tuple[str, str, str]] = []
        for agent in agents:
            last_ts = _get_last_activity(agent.agent_id, config=cfg)
            last_cycle = _relative_time(last_ts, config=cfg) if last_ts else "never"

            task_id = in_progress.get(agent.agent_id)
            if task_id:
                status = f"working on {task_id}"
            else:
                status = "idle"

            rows.append((agent.name, last_cycle, status))

        cycle_width = max(len(r[1]) for r in rows)
        cycle_width = max(cycle_width, len("Last cycle"))

        lines.append("")
        lines.append(f"  {'Agents':<{name_width}}  {'Last cycle':<{cycle_width}}  Status")

        for name, last_cycle, status in rows:
            if status == "idle":
                status_text = c.dim(status)
            else:
                status_text = c.cyan(status)

            lines.append(f"  {name:<{name_width}}  {last_cycle:<{cycle_width}}  {status_text}")

    # --- Task counts ---
    queued = _count_dir(cfg.tasks_queued)
    in_prog = _count_dir(cfg.tasks_in_progress)
    backlog = _count_dir(cfg.tasks_backlog)
    done = _count_dir(cfg.tasks_done)
    in_review = _count_dir(cfg.tasks_in_review)

    task_parts = [f"queued: {queued}", f"in-progress: {in_prog}"]
    if in_review:
        task_parts.append(f"in-review: {in_review}")
    if backlog:
        task_parts.append(f"backlog: {backlog}")
    task_parts.append(f"done: {done}")

    lines.append("")
    lines.append(f"  Tasks           {('  '.join(task_parts))}")

    # --- Budget ---
    budget = check_budget(config=cfg)
    daily_pct = budget.daily_pct
    weekly_pct = (budget.weekly_spent / budget.weekly_cap * 100) if budget.weekly_cap > 0 else 0.0

    daily_text = f"${budget.daily_spent:.2f} / ${budget.daily_cap:.2f} ({daily_pct:.0f}%)"
    weekly_text = f"${budget.weekly_spent:.2f} / ${budget.weekly_cap:.2f} ({weekly_pct:.0f}%)"

    lines.append(f"  Budget today    {_budget_color(c, daily_pct, daily_text)}")
    lines.append(f"  Budget weekly   {_budget_color(c, weekly_pct, weekly_text)}")

    # --- Needs attention ---
    attention: list[str] = []

    # Backlog items
    backlog_items = list_backlog(config=cfg)
    if backlog_items:
        n = len(backlog_items)
        attention.append(f"{n} backlog item{'s' if n != 1 else ''} awaiting promotion")

    # Human inbox
    human_messages = read_inbox("human", config=cfg)
    if human_messages:
        n = len(human_messages)
        attention.append(f"{n} message{'s' if n != 1 else ''} in human inbox")

    # In-review tasks
    if in_review:
        attention.append(f"{in_review} task{'s' if in_review != 1 else ''} awaiting review")

    # Budget warnings
    if budget.circuit_breaker_tripped:
        attention.append("Budget circuit breaker tripped")
    elif daily_pct >= 80:
        attention.append(f"Budget warning: {daily_pct:.0f}% of daily cap used")

    if attention:
        lines.append("")
        lines.append(f"  {c.yellow('Needs attention:')}")
        for item in attention:
            lines.append(f"    {item}")

    lines.append("")

    exit_code = 1 if attention else 0
    return "\n".join(lines), exit_code
