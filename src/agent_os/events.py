"""agent-os events — structured observability events for cycle outcomes and dispatch.

Provides clean, typed events that separate "the process ran" from "the work
shipped." Used by the runner (cycle outcomes) and scheduler (dispatch skipped)
to emit structured JSON to agent JSONL logs.

These events are designed with clean interfaces for future hosted-tier
consumption — no deployment-specific assumptions are hardcoded.

Usage:
    from agent_os.events import CycleOutcomeEvent, emit_cycle_outcome

    event = CycleOutcomeEvent(
        task_id="task-2026-0419-001",
        agent="agent-001-maker",
        cycle_type="task",
        process_status="completed",
        artifact_status="failed",
        failure_reason="git commit failed: author identity unknown",
    )
    emit_cycle_outcome(event, config=cfg)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from .config import Config, get_config
from .logger import get_logger


@dataclass(frozen=True)
class CycleOutcomeEvent:
    """Emitted when a task cycle ends.

    Separates *process_status* (did the SDK session finish?) from
    *artifact_status* (did the deliverable land?).  For workspace SDLC
    tasks, workspace fields record git commit/push/PR outcomes.
    """

    task_id: str
    agent: str
    cycle_type: str  # "task"
    process_status: str  # "completed", "error"
    artifact_status: str  # "completed", "failed", "none"
    artifact_type: str = ""  # "github_pr", "git_commit", "task_completion"
    artifact_ref: str | None = None  # PR URL, commit SHA, etc.
    failure_reason: str = ""

    # Workspace SDLC fields (populated only for workspace-mode tasks)
    workspace_git_commit: str | None = None  # commit SHA or None
    workspace_git_push: bool | None = None  # push succeeded?
    workspace_pr_url: str | None = None  # PR URL if available

    def to_dict(self) -> dict:
        """Serialize to a dict, omitting empty optional fields."""
        d = {"event": "cycle_outcome"}
        for k, v in asdict(self).items():
            if v is not None and v != "":
                d[k] = v
        return d


@dataclass(frozen=True)
class DispatchSkippedEvent:
    """Emitted when the scheduler evaluates an agent and decides not to fire.

    Turns scheduler silence into data — the April dispatch bug was invisible
    because absence produced no signal.
    """

    agent: str
    cycle_type: str  # "cycle", "standing_orders", "drives", "dreams"
    reason: str  # "cooldown_active", "outside_operating_hours", "budget_tripped", "disabled"
    next_eligible: str | None = None  # ISO datetime, if computable

    def to_dict(self) -> dict:
        """Serialize to a dict, omitting empty optional fields."""
        d = {"event": "dispatch_skipped"}
        for k, v in asdict(self).items():
            if v is not None and v != "":
                d[k] = v
        return d


def emit_cycle_outcome(event: CycleOutcomeEvent, *, config: Config | None = None) -> None:
    """Log a cycle outcome event to the agent's JSONL log."""
    cfg = config or get_config()
    log = get_logger(event.agent, config=cfg)

    event_dict = event.to_dict()
    event_dict.setdefault("timestamp", datetime.now(cfg.tz).isoformat())

    is_success = event.process_status == "completed" and event.artifact_status in ("completed", "none")
    level = "info" if is_success else "warn"

    log._write(
        level,
        "cycle_outcome",
        f"Cycle outcome: process={event.process_status} artifact={event.artifact_status}",
        event_dict,
    )


def emit_dispatch_skipped(event: DispatchSkippedEvent, *, config: Config | None = None) -> None:
    """Log a dispatch_skipped event to the agent's JSONL log."""
    cfg = config or get_config()
    log = get_logger(event.agent, config=cfg)

    event_dict = event.to_dict()
    event_dict.setdefault("timestamp", datetime.now(cfg.tz).isoformat())

    log.info(
        "dispatch_skipped",
        f"Dispatch skipped: {event.cycle_type} — {event.reason}",
        event_dict,
    )


def get_dispatch_status(*, config: Config | None = None) -> list[dict]:
    """Compute per-agent, per-cycle-type dispatch status.

    Returns a list of dicts, each with:
    - agent: agent ID
    - cycle_type: schedule type name
    - cadence: expected interval description
    - last_dispatch: ISO timestamp of last dispatch (or "never")
    - next_eligible: ISO timestamp of next eligible dispatch (or "now")
    - enabled: whether this schedule type is enabled
    """
    from datetime import timedelta

    from .registry import list_agents

    cfg = config or get_config()
    now = datetime.now(cfg.tz)

    try:
        agents = list_agents(config=cfg)
    except Exception:
        agents = []

    agent_ids = [a.agent_id for a in agents]
    rows: list[dict] = []

    # Define the schedule types and their cadence configs
    schedule_types = [
        ("cycle", "scheduler-cycle", cfg.schedule_cycles_interval_minutes, cfg.schedule_cycles_enabled),
        (
            "standing_orders",
            "scheduler-standing-orders",
            cfg.schedule_standing_orders_interval_minutes,
            cfg.schedule_standing_orders_enabled,
        ),
    ]

    for agent_id in agent_ids:
        for stype, cadence_name, interval_min, enabled in schedule_types:
            cadence_file = cfg.logs_dir / agent_id / f".cadence-{cadence_name}"
            last_dispatch = "never"
            next_eligible = "now"

            if cadence_file.exists():
                try:
                    last_dt = datetime.fromisoformat(cadence_file.read_text().strip())
                    last_dispatch = last_dt.isoformat()
                    next_dt = last_dt + timedelta(minutes=interval_min)
                    if next_dt > now:
                        next_eligible = next_dt.isoformat()
                    else:
                        next_eligible = "now"
                except (ValueError, OSError):
                    pass

            rows.append(
                {
                    "agent": agent_id,
                    "cycle_type": stype,
                    "cadence": f"{interval_min}m",
                    "last_dispatch": last_dispatch,
                    "next_eligible": next_eligible,
                    "enabled": enabled,
                }
            )

        # Drives — time-based, not cadence-based
        rows.append(
            {
                "agent": agent_id,
                "cycle_type": "drives",
                "cadence": ", ".join(
                    cfg.schedule_drives_weekend_times if now.weekday() >= 5 else cfg.schedule_drives_weekday_times
                ),
                "last_dispatch": _read_last_dispatch(agent_id, "drives", config=cfg),
                "next_eligible": "per schedule",
                "enabled": cfg.schedule_drives_enabled,
            }
        )

        # Dreams — time-based
        rows.append(
            {
                "agent": agent_id,
                "cycle_type": "dreams",
                "cadence": cfg.schedule_dreams_time,
                "last_dispatch": _read_last_dispatch(agent_id, "dreams", config=cfg),
                "next_eligible": "per schedule",
                "enabled": cfg.schedule_dreams_enabled,
            }
        )

    return rows


def _read_last_dispatch(agent_id: str, dispatch_type: str, *, config: Config | None = None) -> str:
    """Read last dispatch time from agent log for a given dispatch type.

    Scans the agent's JSONL log for the most recent dispatch_outcome entry
    of the given type.
    """
    import json

    cfg = config or get_config()
    log_dir = cfg.logs_dir / agent_id
    if not log_dir.exists():
        return "never"

    # Check today's and yesterday's log files
    now = datetime.now(cfg.tz)
    last_ts = "never"

    for day_offset in range(2):
        from datetime import timedelta

        day = now - timedelta(days=day_offset)
        log_file = log_dir / f"{day.strftime('%Y-%m-%d')}.jsonl"
        if not log_file.exists():
            continue
        try:
            for line in log_file.read_text().splitlines():
                entry = json.loads(line)
                if entry.get("action") == "dispatch_outcome" and entry.get("refs", {}).get("type") == dispatch_type:
                    ts = entry.get("timestamp", "")
                    if ts > last_ts or last_ts == "never":
                        last_ts = ts
        except (json.JSONDecodeError, OSError):
            continue

    return last_ts


def format_dispatch_status(*, config: Config | None = None) -> str:
    """Format dispatch status as a human-readable table."""
    cfg = config or get_config()
    rows = get_dispatch_status(config=cfg)

    if not rows:
        return "No agents registered."

    # Header
    lines = [
        f"{'Agent':<28} {'Type':<18} {'Cadence':<12} {'Last Dispatch':<26} {'Next Eligible':<26} {'Enabled'}",
        "-" * 120,
    ]

    for row in rows:
        last = row["last_dispatch"]
        # Truncate ISO timestamps for readability
        if last != "never" and len(last) > 25:
            last = last[:25]
        next_e = row["next_eligible"]
        if next_e not in ("now", "per schedule") and len(next_e) > 25:
            next_e = next_e[:25]

        enabled_str = "yes" if row["enabled"] else "NO"
        lines.append(
            f"{row['agent']:<28} {row['cycle_type']:<18} {row['cadence']:<12} {last:<26} {next_e:<26} {enabled_str}"
        )

    return "\n".join(lines)
