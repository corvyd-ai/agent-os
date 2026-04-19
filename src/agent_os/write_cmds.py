"""Mutating commands — budget caps, autonomy levels, schedule toggles.

All writes go through `toml_writer.update_toml`, which uses tomlkit when
available so comments and formatting survive the round-trip.
"""

from __future__ import annotations

from pathlib import Path

from .toml_writer import update_toml

AUTONOMY_LEVELS: tuple[str, ...] = ("low", "medium", "high")
SCHEDULE_KINDS: tuple[str, ...] = ("scheduler", "cycles", "standing-orders", "drives", "dreams")


def set_budget_caps(
    toml_path: Path,
    *,
    daily: float | None = None,
    weekly: float | None = None,
    monthly: float | None = None,
) -> None:
    """Set one or more budget caps in agent-os.toml."""
    updates: dict[str, float] = {}
    if daily is not None:
        updates["daily_cap"] = float(daily)
    if weekly is not None:
        updates["weekly_cap"] = float(weekly)
    if monthly is not None:
        updates["monthly_cap"] = float(monthly)
    if not updates:
        return
    update_toml(toml_path, "budget", updates)


def set_agent_autonomy(toml_path: Path, agent_id: str, level: str) -> None:
    """Set per-agent autonomy level under [autonomy.agents]."""
    if level not in AUTONOMY_LEVELS:
        raise ValueError(f"Invalid autonomy level: {level!r}. Must be one of {AUTONOMY_LEVELS}.")
    update_toml(toml_path, "autonomy.agents", {agent_id: level})


def toggle_schedule(toml_path: Path, kind: str, enabled: bool) -> None:
    """Toggle a scheduler feature on or off.

    `kind` in {scheduler, cycles, standing-orders, drives, dreams}. "scheduler"
    flips the master switch at [schedule]; the rest flip [schedule.<kind>].
    """
    if kind not in SCHEDULE_KINDS:
        raise ValueError(f"Unknown kind: {kind!r}. Must be one of {SCHEDULE_KINDS}.")

    if kind == "scheduler":
        update_toml(toml_path, "schedule", {"enabled": bool(enabled)})
        return

    # Sub-scheduler sections are dotted under `schedule`.
    # The config schema uses plain names for cycles/standing-orders/drives/dreams.
    section_name = kind.replace("-", "_") if kind == "standing-orders" else kind
    update_toml(toml_path, f"schedule.{section_name}", {"enabled": bool(enabled)})
