"""Mutating commands — budget caps, autonomy levels, schedule toggles.

All writes go through `toml_writer.update_toml`, which uses tomlkit when
available so comments and formatting survive the round-trip.
"""

from __future__ import annotations

from pathlib import Path

from .toml_writer import remove_toml_key, update_toml

AUTONOMY_LEVELS: tuple[str, ...] = ("low", "medium", "high")
SCHEDULE_KINDS: tuple[str, ...] = ("scheduler", "cycles", "standing-orders", "drives", "dreams")
NOTIFICATION_SEVERITIES: tuple[str, ...] = ("info", "warning", "critical")
NOTIFICATION_CHANNELS: tuple[str, ...] = ("file", "desktop")


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


# --- Notifications ---


def set_notifications_enabled(toml_path: Path, enabled: bool) -> None:
    """Flip the master notifications switch."""
    update_toml(toml_path, "notifications", {"enabled": bool(enabled)})


def set_notifications_severity(toml_path: Path, severity: str) -> None:
    """Set the global minimum notification severity."""
    if severity not in NOTIFICATION_SEVERITIES:
        raise ValueError(f"Invalid severity: {severity!r}. Must be one of {NOTIFICATION_SEVERITIES}.")
    update_toml(toml_path, "notifications", {"min_severity": severity})


def set_notifications_channel(toml_path: Path, channel: str, enabled: bool) -> None:
    """Toggle a notification channel (file or desktop)."""
    if channel not in NOTIFICATION_CHANNELS:
        raise ValueError(
            f"Invalid channel: {channel!r}. Must be one of {NOTIFICATION_CHANNELS}. "
            f"Use `notifications webhook`/`script` to configure those channels."
        )
    update_toml(toml_path, "notifications", {channel: bool(enabled)})


def set_notifications_webhook(toml_path: Path, url: str) -> None:
    """Set the webhook URL (empty string clears it)."""
    update_toml(toml_path, "notifications", {"webhook_url": url})


def set_notifications_script(toml_path: Path, script_path: str) -> None:
    """Set the notification script path (empty string clears it)."""
    update_toml(toml_path, "notifications", {"script": script_path})


def set_notifications_event_override(toml_path: Path, event_type: str, severity: str) -> None:
    """Set a per-event-type severity override under [notifications.events]."""
    # Validate against the event registry.
    from .notifications import KNOWN_EVENT_TYPES

    if event_type not in KNOWN_EVENT_TYPES:
        known = ", ".join(sorted(KNOWN_EVENT_TYPES))
        raise ValueError(f"Unknown event_type: {event_type!r}. Known events: {known}.")
    if severity not in NOTIFICATION_SEVERITIES:
        raise ValueError(f"Invalid severity: {severity!r}. Must be one of {NOTIFICATION_SEVERITIES}.")
    update_toml(toml_path, "notifications.events", {event_type: severity})


def clear_notifications_event_override(toml_path: Path, event_type: str) -> bool:
    """Remove a per-event-type override. Returns True if it existed."""
    return remove_toml_key(toml_path, "notifications.events", event_type)
