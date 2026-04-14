"""agent-os scheduler — platform-native tick dispatcher.

Replaces 20+ cron entries with a single ``agent-os tick``. Scheduling
intelligence is in the platform; execution model stays Unix (cron).

One cron entry:
    * * * * * agent-os tick --config /path/to/agent-os.toml

The tick command runs every minute, reads schedule config, checks what's
due, checks budget, and dispatches.

Usage:
    from agent_os.scheduler import tick, get_schedule_status
"""

from __future__ import annotations

import fcntl
import json
from dataclasses import dataclass, field
from datetime import datetime

from .budget import check_budget
from .config import Config, get_config
from .logger import get_logger
from .registry import list_agents

# Schedule types gated by operating_hours.
# These represent "agent on the clock" work that costs API budget.
# Everything else (dreams, archive, log_archive, manifest, watchdog)
# runs regardless of operating hours.
_OPERATING_HOURS_GATED: frozenset[str] = frozenset(
    {
        "cycle",
        "standing_orders",
        "drives",
    }
)


@dataclass
class DispatchRecord:
    """Record of a single dispatched item."""

    type: str  # cycle, standing_orders, drives, dreams, archive, manifest, watchdog
    agent: str
    at: str
    cost: float = 0.0
    result: str = "pending"


@dataclass
class TickResult:
    """Result of a tick invocation."""

    timestamp: str
    enabled: bool
    budget_tripped: bool
    outside_hours: bool
    dispatched: list[DispatchRecord] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _now(*, config: Config | None = None) -> datetime:
    cfg = config or get_config()
    return datetime.now(cfg.tz)


def _parse_time(time_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' to (hour, minute)."""
    parts = time_str.strip().split(":")
    return int(parts[0]), int(parts[1])


def is_within_operating_hours(*, config: Config | None = None) -> bool:
    """Check if current time (in configured timezone) is within operating hours."""
    cfg = config or get_config()
    hours_str = cfg.schedule_operating_hours
    if not hours_str:
        return True  # No restriction = 24/7

    try:
        start_str, end_str = hours_str.split("-")
        start_h, start_m = _parse_time(start_str)
        end_h, end_m = _parse_time(end_str)
    except (ValueError, IndexError):
        return True  # Malformed = allow

    now = _now(config=cfg)
    current_minutes = now.hour * 60 + now.minute
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m

    if start_minutes <= end_minutes:
        return start_minutes <= current_minutes < end_minutes
    else:
        # Wraps midnight (e.g. "22:00-06:00")
        return current_minutes >= start_minutes or current_minutes < end_minutes


def acquire_lock(agent_id: str, mode: str, *, config: Config | None = None) -> object | None:
    """Try to acquire a file lock for agent+mode. Returns lock fd or None.

    The caller must keep the returned object alive for the duration of the
    operation. When the fd is closed (or garbage collected), the lock releases.
    """
    cfg = config or get_config()
    lock_dir = cfg.operations_dir / "locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{agent_id}.{mode}.lock"

    try:
        fd = lock_path.open("w")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except OSError:
        return None


def _is_cadence_due(agent_id: str, cadence_name: str, interval_minutes: int, *, config: Config | None = None) -> bool:
    """Check if a scheduled cadence is due based on interval in minutes."""
    cfg = config or get_config()
    cadence_file = cfg.logs_dir / agent_id / f".cadence-{cadence_name}"
    if not cadence_file.exists():
        return True

    try:
        last_run = datetime.fromisoformat(cadence_file.read_text().strip())
        elapsed = (_now(config=cfg) - last_run).total_seconds() / 60
        # 2 minute tolerance for clock drift
        return elapsed >= (interval_minutes - 2)
    except (ValueError, OSError):
        return True


def _mark_scheduler_cadence(agent_id: str, cadence_name: str, *, config: Config | None = None) -> None:
    """Record that a scheduler cadence just ran."""
    cfg = config or get_config()
    cadence_file = cfg.logs_dir / agent_id / f".cadence-{cadence_name}"
    cadence_file.parent.mkdir(parents=True, exist_ok=True)
    cadence_file.write_text(_now(config=cfg).isoformat())


def _is_time_match(target_time: str, *, config: Config | None = None) -> bool:
    """Check if current HH:MM matches a target time string."""
    try:
        target_h, target_m = _parse_time(target_time)
        now = _now(config=config)
        return now.hour == target_h and now.minute == target_m
    except (ValueError, IndexError):
        return False


def _is_weekend(*, config: Config | None = None) -> bool:
    """Check if today is a weekend (Saturday=5, Sunday=6)."""
    return _now(config=config).weekday() >= 5


def write_scheduler_state(result: TickResult, *, config: Config | None = None) -> None:
    """Write scheduler state file for dashboard consumption."""
    cfg = config or get_config()
    cfg.operations_dir.mkdir(parents=True, exist_ok=True)

    state = {
        "last_tick": result.timestamp,
        "enabled": result.enabled,
        "budget": {},
        "dispatched": [],
        "skipped": result.skipped,
    }

    if not result.budget_tripped:
        budget = check_budget(config=cfg)
        state["budget"] = {
            "daily_spent": round(budget.daily_spent, 2),
            "daily_cap": budget.daily_cap,
            "circuit_breaker_tripped": budget.circuit_breaker_tripped,
        }

    for d in result.dispatched:
        state["dispatched"].append(
            {
                "type": d.type,
                "agent": d.agent,
                "at": d.at,
                "cost": d.cost,
                "result": d.result,
            }
        )

    cfg.scheduler_state_file.write_text(json.dumps(state, indent=2) + "\n")


async def tick(*, config: Config | None = None) -> TickResult:
    """Main entry point. Called every minute by a single cron entry.

    1. Check master enable switch
    2. Compute operating hours (applied selectively, not as a global gate)
    3. Check daily budget
    4. For each schedule type:
       - If type is in _OPERATING_HOURS_GATED and outside hours → skip
       - Otherwise check if due, acquire lock, dispatch
    5. Write scheduler state file for dashboard

    Operating hours only gate agent work (cycles, standing_orders, drives).
    Dreams, archive, manifest, and watchdog run regardless of hours.
    """
    cfg = config or get_config()
    now_iso = _now(config=cfg).isoformat()
    result = TickResult(timestamp=now_iso, enabled=True, budget_tripped=False, outside_hours=False)

    # 1. Master enable
    if not cfg.schedule_enabled:
        result.enabled = False
        result.skipped.append("scheduler disabled")
        write_scheduler_state(result, config=cfg)
        return result

    # 2. Operating hours — computed once, applied per dispatch type
    outside_hours = not is_within_operating_hours(config=cfg)
    if outside_hours:
        result.outside_hours = True

    # 3. Budget
    budget = check_budget(config=cfg)
    if budget.circuit_breaker_tripped:
        result.budget_tripped = True
        result.skipped.append(f"budget tripped: ${budget.daily_spent:.2f}/{budget.daily_cap:.2f}")
        write_scheduler_state(result, config=cfg)
        return result

    # Get all agents
    try:
        agents = list_agents(config=cfg)
    except Exception:
        agents = []

    agent_ids = [a.agent_id for a in agents]

    # Determine which agents to schedule for cycles
    cycle_agents = agent_ids
    if cfg.schedule_cycles_agents != ["all"]:
        cycle_agents = [a for a in agent_ids if a in cfg.schedule_cycles_agents]

    # 4. Dispatch each schedule type

    # Lazy import to avoid circular dependency
    from . import runner

    # --- Cycles ---
    if outside_hours and "cycle" in _OPERATING_HOURS_GATED:
        result.skipped.append("cycles: outside operating hours")
    elif cfg.schedule_cycles_enabled:
        for agent_id in cycle_agents:
            cadence_name = "scheduler-cycle"
            if _is_cadence_due(agent_id, cadence_name, cfg.schedule_cycles_interval_minutes, config=cfg):
                lock = acquire_lock(agent_id, "cycle", config=cfg)
                if lock is None:
                    result.skipped.append(f"cycle:{agent_id} locked")
                    continue

                record = DispatchRecord(type="cycle", agent=agent_id, at=now_iso)
                try:
                    get_logger("system").info(
                        "tick_dispatch", f"Dispatching cycle for {agent_id}", {"type": "cycle", "agent": agent_id}
                    )
                    await runner.run_cycle(agent_id, config=cfg)
                    record.result = "done"
                    _mark_scheduler_cadence(agent_id, cadence_name, config=cfg)
                except Exception as e:
                    record.result = f"error: {e}"
                    get_logger("system").error(
                        "tick_error", f"Error in cycle for {agent_id}: {e}", {"type": "cycle", "agent": agent_id}
                    )
                finally:
                    lock.close()
                result.dispatched.append(record)

    # --- Standing orders ---
    if outside_hours and "standing_orders" in _OPERATING_HOURS_GATED:
        result.skipped.append("standing_orders: outside operating hours")
    elif cfg.schedule_standing_orders_enabled:
        for agent_id in agent_ids:
            cadence_name = "scheduler-standing-orders"
            if _is_cadence_due(agent_id, cadence_name, cfg.schedule_standing_orders_interval_minutes, config=cfg):
                lock = acquire_lock(agent_id, "standing-orders", config=cfg)
                if lock is None:
                    result.skipped.append(f"standing_orders:{agent_id} locked")
                    continue

                record = DispatchRecord(type="standing_orders", agent=agent_id, at=now_iso)
                try:
                    get_logger("system").info(
                        "tick_dispatch",
                        f"Dispatching standing orders for {agent_id}",
                        {"type": "standing_orders", "agent": agent_id},
                    )
                    await runner.run_standing_orders(agent_id, config=cfg)
                    record.result = "done"
                    _mark_scheduler_cadence(agent_id, cadence_name, config=cfg)
                except Exception as e:
                    record.result = f"error: {e}"
                    get_logger("system").error(
                        "tick_error",
                        f"Error in standing orders for {agent_id}: {e}",
                        {"type": "standing_orders", "agent": agent_id},
                    )
                finally:
                    lock.close()
                result.dispatched.append(record)

    # --- Drive consultations ---
    if outside_hours and "drives" in _OPERATING_HOURS_GATED:
        result.skipped.append("drives: outside operating hours")
    elif cfg.schedule_drives_enabled:
        times = cfg.schedule_drives_weekend_times if _is_weekend(config=cfg) else cfg.schedule_drives_weekday_times
        if any(_is_time_match(t, config=cfg) for t in times):
            for agent_id in agent_ids:
                lock = acquire_lock(agent_id, "drives", config=cfg)
                if lock is None:
                    result.skipped.append(f"drives:{agent_id} locked")
                    continue

                record = DispatchRecord(type="drives", agent=agent_id, at=now_iso)
                try:
                    get_logger("system").info(
                        "tick_dispatch",
                        f"Dispatching drive consultation for {agent_id}",
                        {"type": "drives", "agent": agent_id},
                    )
                    await runner.run_drive_consultation(agent_id, config=cfg)
                    record.result = "done"
                except Exception as e:
                    record.result = f"error: {e}"
                    get_logger("system").error(
                        "tick_error", f"Error in drives for {agent_id}: {e}", {"type": "drives", "agent": agent_id}
                    )
                finally:
                    lock.close()
                result.dispatched.append(record)

    # --- Dream cycles ---
    if cfg.schedule_dreams_enabled and _is_time_match(cfg.schedule_dreams_time, config=cfg):
        for idx, agent_id in enumerate(agent_ids):
            # Stagger: only dispatch if minute offset matches
            stagger_offset = idx * cfg.schedule_dreams_stagger_minutes
            dream_minute = _parse_time(cfg.schedule_dreams_time)[1] + stagger_offset
            if _now(config=cfg).minute != dream_minute % 60:
                continue

            lock = acquire_lock(agent_id, "dream", config=cfg)
            if lock is None:
                result.skipped.append(f"dream:{agent_id} locked")
                continue

            record = DispatchRecord(type="dreams", agent=agent_id, at=now_iso)
            try:
                get_logger("system").info(
                    "tick_dispatch", f"Dispatching dream cycle for {agent_id}", {"type": "dreams", "agent": agent_id}
                )
                await runner.run_dream_cycle(agent_id, config=cfg)
                record.result = "done"
            except Exception as e:
                record.result = f"error: {e}"
                get_logger("system").error(
                    "tick_error", f"Error in dream for {agent_id}: {e}", {"type": "dreams", "agent": agent_id}
                )
            finally:
                lock.close()
            result.dispatched.append(record)

    # --- Maintenance tasks ---
    from . import maintenance

    # Archive
    if cfg.schedule_archive_enabled and _is_time_match(cfg.schedule_archive_time, config=cfg):
        record = DispatchRecord(type="archive", agent="system", at=now_iso)
        try:
            get_logger("system").info("tick_dispatch", "Running archive maintenance", {"type": "archive"})
            archive_result = maintenance.run_archive(config=cfg)
            record.result = f"done: {archive_result.total_archived} items archived"
        except Exception as e:
            record.result = f"error: {e}"
        result.dispatched.append(record)

        # Also archive old log files
        log_record = DispatchRecord(type="log_archive", agent="system", at=now_iso)
        try:
            log_result = maintenance.run_log_archive(config=cfg)
            if log_result.files_archived or log_result.files_deleted:
                log_record.result = f"done: {log_result.files_archived} archived, {log_result.files_deleted} deleted"
            else:
                log_record.result = "done: nothing to archive"
        except Exception as e:
            log_record.result = f"error: {e}"
        result.dispatched.append(log_record)

    # Manifest
    if cfg.schedule_manifest_enabled and _is_cadence_due(
        "system", "scheduler-manifest", cfg.schedule_manifest_interval_minutes, config=cfg
    ):
        record = DispatchRecord(type="manifest", agent="system", at=now_iso)
        try:
            get_logger("system").info("tick_dispatch", "Regenerating manifest", {"type": "manifest"})
            maintenance.run_manifest(config=cfg)
            record.result = "done"
            _mark_scheduler_cadence("system", "scheduler-manifest", config=cfg)
        except Exception as e:
            record.result = f"error: {e}"
        result.dispatched.append(record)

    # Watchdog
    if cfg.schedule_watchdog_enabled and _is_cadence_due(
        "system", "scheduler-watchdog", cfg.schedule_watchdog_interval_minutes, config=cfg
    ):
        record = DispatchRecord(type="watchdog", agent="system", at=now_iso)
        try:
            watchdog_result = maintenance.run_watchdog(config=cfg)
            if watchdog_result.alerts:
                record.result = f"alerts: {', '.join(watchdog_result.alerts)}"
            else:
                record.result = "done: all healthy"
            _mark_scheduler_cadence("system", "scheduler-watchdog", config=cfg)
        except Exception as e:
            record.result = f"error: {e}"
        result.dispatched.append(record)

    # Digest
    if cfg.schedule_digest_enabled and _is_time_match(cfg.schedule_digest_time, config=cfg):
        record = DispatchRecord(type="digest", agent="system", at=now_iso)
        try:
            get_logger("system").info("tick_dispatch", "Running daily digest", {"type": "digest"})
            maintenance.run_daily_digest(config=cfg)
            record.result = "done"
        except Exception as e:
            record.result = f"error: {e}"
        result.dispatched.append(record)

    # 5. Write state
    write_scheduler_state(result, config=cfg)
    return result


def get_schedule_status(*, config: Config | None = None) -> str:
    """Format a human-readable schedule status for CLI output."""
    cfg = config or get_config()

    lines = []
    lines.append("Schedule Status")
    lines.append("=" * 50)
    lines.append(f"Enabled: {cfg.schedule_enabled}")
    lines.append(f"Operating hours: {cfg.schedule_operating_hours or '24/7'}")
    lines.append(f"Within hours: {is_within_operating_hours(config=cfg)}")
    lines.append("")

    lines.append("Schedule Types  (* = respects operating hours)")
    lines.append("-" * 50)
    lines.append(
        f" *Cycles:          {'ON' if cfg.schedule_cycles_enabled else 'OFF'} (every {cfg.schedule_cycles_interval_minutes}m)"
    )
    lines.append(
        f" *Standing orders: {'ON' if cfg.schedule_standing_orders_enabled else 'OFF'} (every {cfg.schedule_standing_orders_interval_minutes}m)"
    )
    lines.append(
        f" *Drives:          {'ON' if cfg.schedule_drives_enabled else 'OFF'} (weekday: {', '.join(cfg.schedule_drives_weekday_times)}, weekend: {', '.join(cfg.schedule_drives_weekend_times)})"
    )
    lines.append(
        f"  Dreams:          {'ON' if cfg.schedule_dreams_enabled else 'OFF'} (at {cfg.schedule_dreams_time}, stagger {cfg.schedule_dreams_stagger_minutes}m)"
    )
    lines.append(
        f"  Archive:         {'ON' if cfg.schedule_archive_enabled else 'OFF'} (at {cfg.schedule_archive_time})"
    )
    lines.append(
        f"  Manifest:        {'ON' if cfg.schedule_manifest_enabled else 'OFF'} (every {cfg.schedule_manifest_interval_minutes}m)"
    )
    lines.append(
        f"  Watchdog:        {'ON' if cfg.schedule_watchdog_enabled else 'OFF'} (every {cfg.schedule_watchdog_interval_minutes}m)"
    )

    # Read last state file
    if cfg.scheduler_state_file.exists():
        try:
            state = json.loads(cfg.scheduler_state_file.read_text())
            lines.append("")
            lines.append(f"Last tick: {state.get('last_tick', 'unknown')}")
            dispatched = state.get("dispatched", [])
            if dispatched:
                lines.append(f"Last dispatched: {len(dispatched)} items")
                for d in dispatched[-5:]:
                    lines.append(f"  [{d['type']}] {d['agent']} -> {d['result']}")
            skipped = state.get("skipped", [])
            if skipped:
                lines.append(f"Skipped: {', '.join(skipped)}")
        except (json.JSONDecodeError, KeyError):
            pass

    return "\n".join(lines)
