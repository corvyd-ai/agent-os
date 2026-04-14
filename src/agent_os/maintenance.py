"""agent-os maintenance — archive, manifest, watchdog.

Platform-native maintenance tasks ported from bash scripts.
These are generic operations any agent-os company needs.

Usage:
    from agent_os.maintenance import run_archive, run_manifest, run_watchdog
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Config, get_config


@dataclass
class ArchiveResult:
    """Result of an archive run."""

    broadcasts_archived: int = 0
    tasks_archived: int = 0
    threads_archived: int = 0
    total_archived: int = 0


@dataclass
class WatchdogResult:
    """Result of a watchdog check."""

    agents_checked: int = 0
    agents_healthy: int = 0
    agents_stale: int = 0
    alerts: list[str] = field(default_factory=list)
    alert_hook_called: bool = False


def run_archive(
    *,
    broadcast_max_age_days: int = 7,
    task_max_age_days: int = 14,
    thread_max_age_days: int = 7,
    config: Config | None = None,
) -> ArchiveResult:
    """Move stale broadcasts, done tasks, and resolved threads to _archive/.

    Configurable retention periods. Only moves items older than the threshold.
    """
    cfg = config or get_config()
    result = ArchiveResult()
    now = time.time()

    # Archive old broadcasts
    broadcast_dir = cfg.broadcast_dir
    if broadcast_dir.exists():
        archive_dir = broadcast_dir / "_archive"
        cutoff = now - (broadcast_max_age_days * 86400)
        for f in broadcast_dir.iterdir():
            if f.is_dir() or not f.name.endswith(".md"):
                continue
            if f.stat().st_mtime < cutoff:
                archive_dir.mkdir(exist_ok=True)
                shutil.move(str(f), str(archive_dir / f.name))
                result.broadcasts_archived += 1

    # Archive done tasks
    done_dir = cfg.tasks_done
    if done_dir.exists():
        archive_dir = done_dir / "_archive"
        cutoff = now - (task_max_age_days * 86400)
        for f in done_dir.iterdir():
            if f.is_dir() or not f.name.endswith(".md"):
                continue
            if f.stat().st_mtime < cutoff:
                archive_dir.mkdir(exist_ok=True)
                shutil.move(str(f), str(archive_dir / f.name))
                result.tasks_archived += 1

    # Archive resolved threads
    resolved_dir = cfg.threads_dir / "resolved"
    if resolved_dir.exists():
        archive_dir = resolved_dir / "_archive"
        cutoff = now - (thread_max_age_days * 86400)
        for f in resolved_dir.iterdir():
            if f.is_dir() or not f.name.endswith(".md"):
                continue
            if f.stat().st_mtime < cutoff:
                archive_dir.mkdir(exist_ok=True)
                shutil.move(str(f), str(archive_dir / f.name))
                result.threads_archived += 1

    result.total_archived = result.broadcasts_archived + result.tasks_archived + result.threads_archived

    return result


@dataclass
class LogArchiveResult:
    """Result of a log archival run."""

    files_archived: int = 0
    files_deleted: int = 0
    bytes_freed: int = 0


def run_log_archive(*, config: Config | None = None) -> LogArchiveResult:
    """Archive old JSONL log files beyond the retention period.

    Files older than ``log_retention_days`` are compressed with gzip and
    moved to a ``_archive/`` subdirectory. Files in ``_archive/`` older
    than 2x retention are deleted.
    """
    import gzip

    cfg = config or get_config()
    result = LogArchiveResult()
    retention_days = cfg.log_retention_days
    now = time.time()
    archive_cutoff = now - (retention_days * 86400)
    delete_cutoff = now - (retention_days * 2 * 86400)

    if not cfg.logs_dir.exists():
        return result

    for agent_dir in cfg.logs_dir.iterdir():
        if not agent_dir.is_dir():
            continue

        # Archive old JSONL files
        for log_file in agent_dir.glob("*.jsonl"):
            if log_file.stat().st_mtime < archive_cutoff:
                archive_dir = agent_dir / "_archive"
                archive_dir.mkdir(exist_ok=True)
                gz_path = archive_dir / f"{log_file.name}.gz"
                with open(log_file, "rb") as f_in, gzip.open(gz_path, "wb") as f_out:
                    f_out.writelines(f_in)
                result.bytes_freed += log_file.stat().st_size
                log_file.unlink()
                result.files_archived += 1

        # Delete very old archives
        archive_dir = agent_dir / "_archive"
        if archive_dir.exists():
            for gz_file in archive_dir.glob("*.jsonl.gz"):
                if gz_file.stat().st_mtime < delete_cutoff:
                    result.bytes_freed += gz_file.stat().st_size
                    gz_file.unlink()
                    result.files_deleted += 1

    return result


def run_manifest(*, config: Config | None = None) -> Path:
    """Regenerate knowledge manifest (table of contents for company/knowledge/).

    Walks the knowledge directory and writes a markdown index file.
    """
    cfg = config or get_config()
    knowledge_dir = cfg.company_root / "knowledge"
    manifest_path = knowledge_dir / "MANIFEST.md"

    if not knowledge_dir.exists():
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("# Knowledge Manifest\n\nNo knowledge files found.\n")
        return manifest_path

    lines = ["# Knowledge Manifest", ""]
    lines.append(f"*Generated: {datetime.now(cfg.tz).isoformat()}*")
    lines.append("")

    file_count = 0
    for root_path in sorted(knowledge_dir.rglob("*.md")):
        if root_path.name == "MANIFEST.md":
            continue
        rel_path = root_path.relative_to(knowledge_dir)
        # Read first line for title
        try:
            first_line = root_path.read_text().split("\n")[0].strip().lstrip("# ")
        except Exception:
            first_line = root_path.name
        lines.append(f"- [{first_line}]({rel_path})")
        file_count += 1

    if file_count == 0:
        lines.append("No knowledge files found.")

    lines.append(f"\n*{file_count} files indexed*\n")

    manifest_path.write_text("\n".join(lines))
    return manifest_path


def run_watchdog(*, config: Config | None = None) -> WatchdogResult:
    """Check agent liveness from logs. Returns alert status.

    An agent is considered stale if it has no log entries within the
    configured threshold (default 45 minutes).
    """
    cfg = config or get_config()
    result = WatchdogResult()
    threshold_minutes = cfg.schedule_watchdog_alert_threshold_minutes

    if not cfg.logs_dir.exists():
        return result

    today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
    cutoff = time.time() - (threshold_minutes * 60)

    # Check each agent's log directory
    for agent_dir in sorted(cfg.logs_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        agent_id = agent_dir.name
        if agent_id == "system":
            continue

        result.agents_checked += 1
        log_file = agent_dir / f"{today}.jsonl"

        if not log_file.exists():
            result.agents_stale += 1
            result.alerts.append(f"{agent_id}: no log file for today")
            continue

        # Check if the file has recent entries
        try:
            last_line = ""
            for line in log_file.read_text().splitlines():
                if line.strip():
                    last_line = line
            if last_line:
                entry = json.loads(last_line)
                ts = datetime.fromisoformat(entry["timestamp"])
                if ts.timestamp() >= cutoff:
                    result.agents_healthy += 1
                else:
                    result.agents_stale += 1
                    result.alerts.append(f"{agent_id}: last activity {entry['timestamp']}")
            else:
                result.agents_stale += 1
                result.alerts.append(f"{agent_id}: empty log file")
        except (json.JSONDecodeError, KeyError, ValueError):
            result.agents_stale += 1
            result.alerts.append(f"{agent_id}: unparseable log")

    # Call alert hook if configured and there are alerts
    if result.alerts and cfg.schedule_watchdog_alert_hook:
        hook = cfg.schedule_watchdog_alert_hook
        # Resolve relative to company root
        hook_path = Path(hook)
        if not hook_path.is_absolute():
            hook_path = cfg.company_root / hook

        if hook_path.exists():
            try:
                alert_text = "\n".join(result.alerts)
                subprocess.run(
                    [str(hook_path), alert_text],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                result.alert_hook_called = True
            except (subprocess.TimeoutExpired, OSError):
                pass

    # Also send via notification system (in addition to legacy hook)
    if result.alerts:
        from .notifications import NotificationEvent, send_notification

        alert_text = "\n".join(f"- {a}" for a in result.alerts)
        send_notification(
            NotificationEvent(
                event_type="watchdog_alert",
                severity="warning",
                title=f"Watchdog: {result.agents_stale} stale agent(s)",
                detail=f"Stale agents detected:\n{alert_text}",
                refs={"agents_stale": result.agents_stale, "agents_healthy": result.agents_healthy},
            ),
            config=cfg,
        )

    return result


# --- Daily digest ---


@dataclass
class DigestResult:
    """Result of a daily health digest."""

    tasks_completed: int = 0
    tasks_failed: int = 0
    tasks_created: int = 0
    agents_healthy: int = 0
    agents_stale: int = 0
    breakers_tripped: list[str] = field(default_factory=list)
    daily_spend: float = 0.0
    daily_cap: float = 0.0
    anomalies: list[str] = field(default_factory=list)
    digest_path: str = ""


def run_daily_digest(*, config: Config | None = None) -> DigestResult:
    """Compute daily health summary from logs, costs, and task state.

    Writes a markdown digest to ``operations/digests/YYYY-MM-DD.md``
    and sends it via the notification system.
    """
    cfg = config or get_config()
    result = DigestResult()
    today = datetime.now(cfg.tz).strftime("%Y-%m-%d")

    # --- Task counts from today's files ---
    result.tasks_completed = _count_dir_modified_today(cfg.tasks_dir / "done", today)
    result.tasks_failed = _count_dir_modified_today(cfg.tasks_dir / "failed", today)
    result.tasks_created = _count_dir_modified_today(cfg.tasks_dir / "queued", today) + _count_dir_modified_today(
        cfg.tasks_dir / "backlog", today
    )

    # --- Agent health (reuse watchdog logic) ---
    watchdog = run_watchdog(config=cfg)
    result.agents_healthy = watchdog.agents_healthy
    result.agents_stale = watchdog.agents_stale

    # --- Circuit breakers ---
    from .circuit_breaker import check_breaker
    from .registry import list_agents

    for agent in list_agents(config=cfg):
        state = check_breaker(agent.agent_id, config=cfg)
        if state.tripped:
            result.breakers_tripped.append(agent.agent_id)

    # --- Budget ---
    from .budget import check_budget

    budget = check_budget(config=cfg)
    result.daily_spend = budget.daily_spent
    result.daily_cap = budget.daily_cap

    # --- Anomaly detection ---
    result.anomalies = _detect_anomalies(cfg, today)

    # --- Write digest file ---
    digest_dir = cfg.operations_dir / "digests"
    digest_dir.mkdir(parents=True, exist_ok=True)
    digest_path = digest_dir / f"{today}.md"

    lines = [
        f"# Daily Digest — {today}",
        "",
        "## Tasks",
        f"- Completed: {result.tasks_completed}",
        f"- Failed: {result.tasks_failed}",
        f"- Created: {result.tasks_created}",
        "",
        "## Agents",
        f"- Healthy: {result.agents_healthy}",
        f"- Stale: {result.agents_stale}",
    ]
    if result.breakers_tripped:
        lines.append(f"- Circuit breakers tripped: {', '.join(result.breakers_tripped)}")

    lines.extend(
        [
            "",
            "## Budget",
            f"- Daily spend: ${result.daily_spend:.2f} / ${result.daily_cap:.2f}",
        ]
    )

    if result.anomalies:
        lines.extend(["", "## Anomalies"])
        for a in result.anomalies:
            lines.append(f"- {a}")

    digest_path.write_text("\n".join(lines) + "\n")
    result.digest_path = str(digest_path)

    # --- Send notification ---
    from .notifications import NotificationEvent, send_notification

    summary_parts = [
        f"Tasks: {result.tasks_completed} done, {result.tasks_failed} failed",
        f"Agents: {result.agents_healthy} healthy, {result.agents_stale} stale",
        f"Budget: ${result.daily_spend:.2f} / ${result.daily_cap:.2f}",
    ]
    if result.anomalies:
        summary_parts.append(f"Anomalies: {len(result.anomalies)}")

    send_notification(
        NotificationEvent(
            event_type="daily_digest",
            severity="info",
            title=f"Daily digest — {today}",
            detail="\n".join(summary_parts),
            refs={
                "tasks_completed": result.tasks_completed,
                "tasks_failed": result.tasks_failed,
                "agents_healthy": result.agents_healthy,
                "agents_stale": result.agents_stale,
            },
        ),
        config=cfg,
    )

    return result


def _count_dir_modified_today(directory: Path, today: str) -> int:
    """Count files in a directory modified today (by date in filename or mtime)."""
    if not directory.exists():
        return 0
    count = 0
    for f in directory.glob("*.md"):
        # Check if filename contains today's date
        if today.replace("-", "") in f.stem or today in f.stem:
            count += 1
            continue
        # Fall back to mtime
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime.strftime("%Y-%m-%d") == today:
                count += 1
        except OSError:
            continue
    return count


def _detect_anomalies(cfg: Config, today: str) -> list[str]:
    """Lightweight anomaly detection from today's logs."""
    anomalies: list[str] = []

    if not cfg.logs_dir.exists():
        return anomalies

    for agent_dir in sorted(cfg.logs_dir.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name == "system":
            continue

        agent_id = agent_dir.name
        log_file = agent_dir / f"{today}.jsonl"
        if not log_file.exists():
            anomalies.append(f"{agent_id}: zero activity today")
            continue

        # Count errors and look for repeated patterns
        error_counts: dict[str, int] = {}
        try:
            for line in log_file.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("level") == "error":
                        action = entry.get("action", "unknown")
                        error_counts[action] = error_counts.get(action, 0) + 1
                except json.JSONDecodeError:
                    continue
        except OSError:
            continue

        for action, count in error_counts.items():
            if count >= 5:
                anomalies.append(f"{agent_id}: {action} occurred {count} times")

    return anomalies
