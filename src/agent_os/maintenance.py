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

    return result
