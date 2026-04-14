"""agent-os failure circuit breaker — stop dispatching after repeated failures.

Modeled on the budget circuit breaker: counts consecutive error-level entries
in the agent's JSONL log. If the count exceeds a threshold, the breaker
trips and blocks further dispatches until the cooldown elapses and the
underlying issue resolves (validated via pre-flight check).

The JSONL log IS the failure counter — no separate counter state is maintained.
Only the tripped/not-tripped state is persisted to a JSON file so it survives
process restarts.

Usage:
    from agent_os.circuit_breaker import check_breaker, trip_breaker, reset_breaker

    state = check_breaker("agent-001", config=cfg)
    if state.tripped:
        print(f"Breaker tripped: {state.reason}")
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Config, get_config


@dataclass(frozen=True)
class BreakerState:
    """Current state of an agent's failure circuit breaker."""

    agent_id: str
    tripped: bool = False
    consecutive_failures: int = 0
    last_error_category: str = ""
    last_error_detail: str = ""
    reason: str = ""
    tripped_at: str = ""  # ISO timestamp when tripped

    @property
    def summary(self) -> str:
        if not self.tripped:
            return "OK"
        return f"Tripped: {self.reason}"


def _breaker_file(agent_id: str, *, config: Config) -> Path:
    """Path to the circuit breaker state file."""
    return config.agents_state_dir / agent_id / ".circuit-breaker.json"


def _read_breaker_file(agent_id: str, *, config: Config) -> dict:
    """Read persisted breaker state, or empty dict if not tripped."""
    path = _breaker_file(agent_id, config=config)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _count_consecutive_errors(agent_id: str, *, config: Config) -> tuple[int, str, str]:
    """Count consecutive error-level entries at the tail of today's log.

    Returns (count, last_error_category, last_error_detail).
    """
    log_dir = config.logs_dir / agent_id
    today = datetime.now(config.tz).strftime("%Y-%m-%d")
    log_file = log_dir / f"{today}.jsonl"

    if not log_file.exists():
        return 0, "", ""

    try:
        lines = log_file.read_text().splitlines()
    except OSError:
        return 0, "", ""

    count = 0
    last_category = ""
    last_detail = ""

    # Walk backward from the end of the log
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if entry.get("level") == "error":
            count += 1
            if count == 1:
                refs = entry.get("refs", {})
                last_category = refs.get("error_category", "unknown")
                last_detail = entry.get("detail", "")
        else:
            # First non-error breaks the streak
            break

    return count, last_category, last_detail


def check_breaker(agent_id: str, *, config: Config | None = None) -> BreakerState:
    """Check the current circuit breaker state for an agent.

    Reads from persisted state file (for tripped status) and from JSONL
    logs (for consecutive failure count).
    """
    cfg = config or get_config()

    if not cfg.circuit_breaker_enabled:
        return BreakerState(agent_id=agent_id)

    # Check persisted tripped state
    persisted = _read_breaker_file(agent_id, config=cfg)
    if persisted.get("tripped"):
        return BreakerState(
            agent_id=agent_id,
            tripped=True,
            reason=persisted.get("reason", ""),
            tripped_at=persisted.get("tripped_at", ""),
            last_error_category=persisted.get("last_error_category", ""),
            last_error_detail=persisted.get("last_error_detail", ""),
            consecutive_failures=persisted.get("consecutive_failures", 0),
        )

    # Count consecutive errors from log tail
    count, category, detail = _count_consecutive_errors(agent_id, config=cfg)

    return BreakerState(
        agent_id=agent_id,
        tripped=False,
        consecutive_failures=count,
        last_error_category=category,
        last_error_detail=detail,
    )


def trip_breaker(agent_id: str, reason: str, *, config: Config | None = None) -> BreakerState:
    """Trip the circuit breaker for an agent and send a notification.

    Writes state to the breaker file and dispatches a critical notification.
    """
    cfg = config or get_config()

    count, category, detail = _count_consecutive_errors(agent_id, config=cfg)
    now = datetime.now(cfg.tz).isoformat()

    state_data = {
        "tripped": True,
        "tripped_at": now,
        "reason": reason,
        "last_error_category": category,
        "last_error_detail": detail,
        "consecutive_failures": count,
    }

    # Write state file
    breaker_path = _breaker_file(agent_id, config=cfg)
    breaker_path.parent.mkdir(parents=True, exist_ok=True)
    breaker_path.write_text(json.dumps(state_data, indent=2))

    # Log the trip
    from .logger import get_logger

    log = get_logger(agent_id, config=cfg)
    log.error(
        "circuit_breaker_tripped",
        f"Failure circuit breaker tripped: {reason}",
        {
            "consecutive_failures": count,
            "last_error_category": category,
        },
    )

    # Send notification
    from .notifications import NotificationEvent, send_notification

    send_notification(
        NotificationEvent(
            event_type="circuit_breaker_tripped",
            severity="critical",
            title=f"Circuit breaker tripped for {agent_id}",
            detail=f"{reason}\n\nConsecutive failures: {count}\nLast error: {detail[:200]}",
            agent_id=agent_id,
            refs={"consecutive_failures": count, "last_error_category": category},
        ),
        config=cfg,
    )

    return BreakerState(
        agent_id=agent_id,
        tripped=True,
        reason=reason,
        tripped_at=now,
        consecutive_failures=count,
        last_error_category=category,
        last_error_detail=detail,
    )


def reset_breaker(agent_id: str, *, config: Config | None = None) -> None:
    """Reset (clear) the circuit breaker for an agent."""
    cfg = config or get_config()
    breaker_path = _breaker_file(agent_id, config=cfg)
    if breaker_path.exists():
        breaker_path.unlink()

    from .logger import get_logger

    log = get_logger(agent_id, config=cfg)
    log.info("circuit_breaker_reset", f"Failure circuit breaker reset for {agent_id}")


def auto_check_reset(agent_id: str, *, config: Config | None = None) -> bool:
    """Check if a tripped breaker should auto-reset.

    If the cooldown has elapsed, runs a pre-flight check. If pre-flight
    passes, resets the breaker. Returns True if the breaker was reset.
    """
    cfg = config or get_config()
    persisted = _read_breaker_file(agent_id, config=cfg)

    if not persisted.get("tripped"):
        return False

    tripped_at = persisted.get("tripped_at", "")
    if not tripped_at:
        return False

    try:
        tripped_time = datetime.fromisoformat(tripped_at)
        elapsed_minutes = (datetime.now(cfg.tz) - tripped_time).total_seconds() / 60
    except (ValueError, TypeError):
        return False

    if elapsed_minutes < cfg.circuit_breaker_cooldown_minutes:
        return False

    # Cooldown elapsed — run preflight to see if issue is resolved
    from .preflight import run_preflight

    preflight = run_preflight(agent_id, config=cfg)
    if preflight.passed:
        reset_breaker(agent_id, config=cfg)
        return True

    return False


def evaluate_breaker(agent_id: str, *, config: Config | None = None) -> BreakerState:
    """Evaluate whether the breaker should trip after a failure.

    Called after a task failure. Counts consecutive errors and trips the
    breaker if the threshold is exceeded.
    """
    cfg = config or get_config()

    if not cfg.circuit_breaker_enabled:
        return BreakerState(agent_id=agent_id)

    count, category, detail = _count_consecutive_errors(agent_id, config=cfg)

    if count >= cfg.circuit_breaker_max_failures:
        return trip_breaker(
            agent_id,
            f"{count} consecutive failures (last: {category})",
            config=cfg,
        )

    return BreakerState(
        agent_id=agent_id,
        tripped=False,
        consecutive_failures=count,
        last_error_category=category,
        last_error_detail=detail,
    )
