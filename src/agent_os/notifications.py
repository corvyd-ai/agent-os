"""agent-os notifications — push alerts to humans via multiple channels.

Lightweight, pluggable notification layer. Every notification flows through
``send_notification()`` which dispatches to all configured channels.

Built-in channels:
- **file**: always-on, writes ``.md`` files to ``operations/notifications/``
- **desktop**: ``notify-send`` (Linux) / ``osascript`` (macOS)
- **webhook**: ``curl`` POST to any URL (Slack, Discord, ntfy.sh)
- **script**: runs a user-provided script with the notification as argument

Usage:
    from agent_os.notifications import send_notification, NotificationEvent

    event = NotificationEvent(
        event_type="preflight_failed",
        severity="critical",
        title="Agent agent-001 blocked by pre-flight check",
        detail="Cannot write to agents/tasks/queued/",
        agent_id="agent-001",
    )
    results = send_notification(event, config=cfg)
"""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Config, get_config

# Severity levels in ascending order
SEVERITIES = ("info", "warning", "critical")
_SEVERITY_ORDER = {s: i for i, s in enumerate(SEVERITIES)}


# Registry of all event types the platform emits. Used for CLI discoverability
# (`agent-os notifications events`) and for validating per-event severity
# overrides. When you add a new event_type, register it here.
KNOWN_EVENT_TYPES: dict[str, str] = {
    "preflight_failed": "Agent blocked by a pre-flight check (cannot claim tasks).",
    "circuit_breaker_tripped": "Agent hit the consecutive-failure threshold and is cooling down.",
    "workspace_push_failed": "Git push failed after completing a task. Work is committed locally.",
    "workspace_salvaged": "Task failed mid-flight; the runner salvage-committed the agent's uncommitted work so it isn't lost.",
    "workspace_preserved": "Salvage commit itself failed; the worktree has been preserved on disk for manual recovery.",
    "workspace_leftover_archived": "Found a leftover worktree at the primary path; archived it before creating the fresh workspace.",
    "workspace_fetch_failed": "Fetch of remote default branch failed during workspace create; branch cut from local (possibly stale) ref instead.",
    "workspace_local_default_diverged": "The base clone's local default branch has commits the remote doesn't — fast-forward skipped to avoid destroying work. Shouldn't happen on a service deployment.",
    "workspace_per_attempt_path_used": "Could not free the primary worktree path; workspace created on a per-attempt fallback path.",
    "workspace_cleanup_failed": "Workspace cleanup (delete or archive) failed — future tasks may hit leftover state.",
    "workspace_pr_ready": "Branch pushed; a pre-filled GitHub compare URL is ready for a human to click-open as a PR.",
    "task_submitted_for_review": "Agent hit the turn limit but the work passed validation; task moved to in-review for human sign-off.",
    "watchdog_alert": "A scheduled agent hasn't run within its expected interval.",
    "daily_digest": "Daily system health summary.",
    "message_for_human": "An agent sent a message to the human inbox.",
}


@dataclass(frozen=True)
class NotificationEvent:
    """A structured notification event."""

    event_type: str  # "preflight_failed", "circuit_breaker_tripped", "budget_warning", "watchdog_alert", "daily_digest", "message_for_human"
    severity: str  # "info", "warning", "critical"
    title: str  # one-line summary
    detail: str  # full message body
    agent_id: str = ""  # which agent (empty for system-wide)
    refs: dict = field(default_factory=dict)  # structured metadata

    @property
    def timestamp(self) -> str:
        return datetime.now().astimezone().isoformat()


@dataclass(frozen=True)
class NotificationResult:
    """Result of a single channel delivery attempt."""

    channel: str  # "file", "desktop", "webhook", "script"
    success: bool
    error: str = ""


def _meets_severity(event_severity: str, min_severity: str) -> bool:
    """Check if event severity meets the minimum threshold."""
    ev = _SEVERITY_ORDER.get(event_severity, 0)
    mn = _SEVERITY_ORDER.get(min_severity, 0)
    return ev >= mn


# --- Channel implementations ---


def notify_file(event: NotificationEvent, *, config: Config) -> NotificationResult:
    """Write notification as a markdown file to operations/notifications/."""
    try:
        notif_dir = config.operations_dir / "notifications"
        notif_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(config.tz)
        filename = f"{ts.strftime('%Y-%m-%dT%H%M%S')}-{event.event_type}.md"

        content = f"""---
event_type: {event.event_type}
severity: {event.severity}
agent_id: "{event.agent_id}"
timestamp: {ts.isoformat()}
---

# {event.title}

{event.detail}
"""
        (notif_dir / filename).write_text(content)
        return NotificationResult(channel="file", success=True)
    except OSError as e:
        return NotificationResult(channel="file", success=False, error=str(e))


def notify_desktop(event: NotificationEvent) -> NotificationResult:
    """Send a desktop notification via notify-send (Linux) or osascript (macOS)."""
    try:
        system = platform.system()
        urgency_map = {"info": "low", "warning": "normal", "critical": "critical"}
        urgency = urgency_map.get(event.severity, "normal")

        if system == "Linux":
            cmd = [
                "notify-send",
                "--urgency",
                urgency,
                "--app-name",
                "agent-os",
                event.title,
                event.detail[:200],  # truncate for desktop notification
            ]
        elif system == "Darwin":
            # macOS: osascript -e 'display notification "detail" with title "title"'
            script = f'display notification "{_escape_applescript(event.detail[:200])}" with title "{_escape_applescript(event.title)}"'
            cmd = ["osascript", "-e", script]
        else:
            return NotificationResult(channel="desktop", success=False, error=f"Unsupported platform: {system}")

        subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return NotificationResult(channel="desktop", success=True)
    except FileNotFoundError:
        return NotificationResult(channel="desktop", success=False, error="notify-send/osascript not found")
    except subprocess.TimeoutExpired:
        return NotificationResult(channel="desktop", success=False, error="Timed out")
    except OSError as e:
        return NotificationResult(channel="desktop", success=False, error=str(e))


def notify_webhook(event: NotificationEvent, *, url: str) -> NotificationResult:
    """POST notification as JSON to a webhook URL via curl."""
    if not url:
        return NotificationResult(channel="webhook", success=False, error="No URL configured")

    try:
        payload = json.dumps(
            {
                "event_type": event.event_type,
                "severity": event.severity,
                "title": event.title,
                "detail": event.detail,
                "agent_id": event.agent_id,
                "timestamp": event.timestamp,
                "refs": event.refs,
            }
        )

        result = subprocess.run(
            [
                "curl",
                "-s",
                "-S",
                "-X",
                "POST",
                "-H",
                "Content-Type: application/json",
                "-d",
                payload,
                "--max-time",
                "15",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            return NotificationResult(channel="webhook", success=False, error=result.stderr[:200])
        return NotificationResult(channel="webhook", success=True)
    except FileNotFoundError:
        return NotificationResult(channel="webhook", success=False, error="curl not found")
    except subprocess.TimeoutExpired:
        return NotificationResult(channel="webhook", success=False, error="Timed out")
    except OSError as e:
        return NotificationResult(channel="webhook", success=False, error=str(e))


def notify_script(event: NotificationEvent, *, script_path: Path) -> NotificationResult:
    """Run a user-provided script with the notification as argument."""
    if not script_path.exists():
        return NotificationResult(channel="script", success=False, error=f"Script not found: {script_path}")

    try:
        payload = json.dumps(
            {
                "event_type": event.event_type,
                "severity": event.severity,
                "title": event.title,
                "detail": event.detail,
                "agent_id": event.agent_id,
                "timestamp": event.timestamp,
                "refs": event.refs,
            }
        )

        result = subprocess.run(
            [str(script_path), payload],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return NotificationResult(channel="script", success=False, error=result.stderr[:200])
        return NotificationResult(channel="script", success=True)
    except subprocess.TimeoutExpired:
        return NotificationResult(channel="script", success=False, error="Timed out")
    except OSError as e:
        return NotificationResult(channel="script", success=False, error=str(e))


# --- Main dispatch ---


def send_notification(
    event: NotificationEvent,
    *,
    config: Config | None = None,
) -> list[NotificationResult]:
    """Send a notification via all configured channels.

    Returns a list of results (one per channel attempted). Also logs the
    notification to the system JSONL log.
    """
    cfg = config or get_config()
    results: list[NotificationResult] = []

    if not cfg.notifications_enabled:
        return results

    # Per-event override takes precedence over the global min_severity.
    min_severity = cfg.notifications_event_overrides.get(event.event_type, cfg.notifications_min_severity)
    if not _meets_severity(event.severity, min_severity):
        return results

    # File notifier (always-on default)
    if cfg.notifications_file:
        results.append(notify_file(event, config=cfg))

    # Desktop notifications
    if cfg.notifications_desktop:
        results.append(notify_desktop(event))

    # Webhook
    if cfg.notifications_webhook_url:
        results.append(notify_webhook(event, url=cfg.notifications_webhook_url))

    # Script
    if cfg.notifications_script:
        script_path = Path(cfg.notifications_script)
        if not script_path.is_absolute():
            script_path = cfg.company_root / script_path
        results.append(notify_script(event, script_path=script_path))

    # Log the notification itself
    from .logger import get_logger

    log = get_logger("system", config=cfg)
    succeeded = [r for r in results if r.success]
    failed = [r for r in results if not r.success]
    log.info(
        "notification_sent",
        f"[{event.severity}] {event.title}",
        {
            "event_type": event.event_type,
            "severity": event.severity,
            "agent_id": event.agent_id,
            "channels_ok": [r.channel for r in succeeded],
            "channels_failed": {r.channel: r.error for r in failed},
        },
    )

    return results


# --- Helpers ---


def _escape_applescript(text: str) -> str:
    """Escape a string for use in an AppleScript string literal."""
    return text.replace("\\", "\\\\").replace('"', '\\"')
