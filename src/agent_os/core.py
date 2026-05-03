"""agent-os core — task lifecycle, messaging, logging, ID generation.

All state is files. The directory a task is in IS its status.

Every public function accepts an optional ``config: Config | None`` parameter.
When omitted the global singleton is used, so existing callers work unchanged.
Passing an explicit Config enables testing without monkeypatching.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from .config import Config, get_config


def _now_iso(*, config: Config | None = None) -> str:
    cfg = config or get_config()
    return datetime.now(cfg.tz).isoformat()


def _today(*, config: Config | None = None) -> str:
    cfg = config or get_config()
    return datetime.now(cfg.tz).strftime("%Y-%m-%d")


def _parse_frontmatter(path: Path) -> tuple[dict, str]:
    """Parse YAML frontmatter + markdown body from a file."""
    text = path.read_text()
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return meta, body


def _write_frontmatter(path: Path, meta: dict, body: str) -> None:
    """Write YAML frontmatter + markdown body to a file."""
    content = "---\n" + yaml.dump(meta, default_flow_style=False, sort_keys=False) + "---\n\n" + body
    path.write_text(content)


def next_id(prefix: str, directory: Path, *, config: Config | None = None) -> str:
    """Generate next sequential ID by scanning a directory.

    Scans all task directories for the given date prefix to find the true max.
    E.g. prefix="task-2026-0215" → "task-2026-0215-002" if 001 exists.
    """
    cfg = config or get_config()

    # For tasks, scan all lifecycle directories to avoid ID collisions
    if prefix.startswith("task-"):
        search_dirs = [
            cfg.tasks_queued,
            cfg.tasks_in_progress,
            cfg.tasks_in_review,
            cfg.tasks_done,
            cfg.tasks_failed,
            cfg.tasks_declined,
            cfg.tasks_backlog,
        ]
    else:
        search_dirs = [directory]

    max_seq = 0
    pattern = re.compile(re.escape(prefix) + r"-(\d{3})")
    for d in search_dirs:
        if not d.exists():
            continue
        for f in d.iterdir():
            m = pattern.match(f.stem)
            if m:
                max_seq = max(max_seq, int(m.group(1)))

    return f"{prefix}-{max_seq + 1:03d}"


# --- Task lifecycle ---


def claim_task(agent_id: str, task_id: str | None = None, *, config: Config | None = None) -> Path | None:
    """Claim a task: move from queued/ to in-progress/.

    If task_id is given, claim that specific task.
    Otherwise, find the next queued task assigned to agent_id (or unassigned).
    Returns the new path of the claimed task, or None if nothing to claim.
    """
    cfg = config or get_config()

    if task_id:
        candidates = list(cfg.tasks_queued.glob(f"{task_id}*"))
        if not candidates:
            return None
        task_file = candidates[0]
    else:
        task_file = _find_next_task(agent_id, config=cfg)
        if not task_file:
            return None

    # Update status in frontmatter
    meta, body = _parse_frontmatter(task_file)
    meta["status"] = "in-progress"
    if not meta.get("assigned_to"):
        meta["assigned_to"] = agent_id
    _write_frontmatter(task_file, meta, body)

    # Move file
    dest = cfg.tasks_in_progress / task_file.name
    shutil.move(str(task_file), str(dest))
    return dest


def _find_next_task(agent_id: str, *, config: Config | None = None) -> Path | None:
    """Find the highest-priority queued task for an agent.

    Skips tasks whose depends_on list contains tasks not yet in done/.
    """
    cfg = config or get_config()
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    best = None
    best_priority = 999

    for f in sorted(cfg.tasks_queued.iterdir()):
        if not f.name.endswith(".md"):
            continue
        meta, _ = _parse_frontmatter(f)
        assigned = meta.get("assigned_to")
        if assigned and assigned != agent_id and not agent_id.startswith(assigned + "-"):
            # Also accept short-form match (e.g. "agent-000" matches "agent-000-chief-of-staff")
            continue
        # Check dependencies — all must be in done/
        depends_on = meta.get("depends_on") or []
        if depends_on and not _deps_satisfied(depends_on, config=cfg):
            continue
        p = priority_order.get(meta.get("priority", "medium"), 2)
        if p < best_priority:
            best = f
            best_priority = p

    return best


def _deps_satisfied(depends_on: list[str], *, config: Config | None = None) -> bool:
    """Check that all dependency task IDs have files in done/."""
    cfg = config or get_config()
    for dep_id in depends_on:
        matches = list(cfg.tasks_done.glob(f"{dep_id}*"))
        if not matches:
            return False
    return True


def complete_task(task_id: str, *, outcome: str = "success", config: Config | None = None) -> Path | None:
    """Move a task from in-progress/ to done/.

    Args:
        task_id: The task ID to complete.
        outcome: Quality signal — one of "success", "partial", "failure", "cancelled".
                 Defaults to "success". Written to frontmatter for health metrics.
        config: Optional Config override.
    """
    cfg = config or get_config()
    return _move_task(task_id, cfg.tasks_in_progress, cfg.tasks_done, "done", extra_meta={"outcome": outcome})


def submit_for_review(task_id: str, *, config: Config | None = None) -> Path | None:
    """Move a task from in-progress/ to in-review/."""
    cfg = config or get_config()
    return _move_task(task_id, cfg.tasks_in_progress, cfg.tasks_in_review, "in-review")


def fail_task(
    task_id: str, reason: str, *, outcome: str = "failure", error_refs: dict | None = None, config: Config | None = None
) -> Path | None:
    """Move a task to failed/ and append failure reason.

    Searches in-progress/ first, then done/ and in-review/ as a backstop:
    if some other code path (an MCP tool, a dashboard control) already
    promoted the task before a downstream failure (e.g. the workspace
    commit/push step), we still want the final state to reflect the failure
    rather than silently leaving a "success" in done/.

    Args:
        task_id: The task ID to fail.
        reason: Human-readable failure reason.
        outcome: Quality signal — defaults to "failure". Could also be "cancelled".
        error_refs: If provided, key diagnostic fields are appended to the
                    failure section for structured observability.
        config: Optional Config override.
    """
    cfg = config or get_config()
    for source in (cfg.tasks_in_progress, cfg.tasks_done, cfg.tasks_in_review):
        candidates = list(source.glob(f"{task_id}*"))
        if candidates:
            task_file = candidates[0]
            break
    else:
        return None

    meta, body = _parse_frontmatter(task_file)
    meta["status"] = "failed"
    meta["outcome"] = outcome
    failure_text = f"\n\n## Failure\n\n**Date**: {_now_iso(config=cfg)}\n**Reason**: {reason}\n"

    if error_refs:
        diag_fields = ["error_class", "error_category", "retryable", "exit_code", "stderr"]
        diag_lines = []
        for field in diag_fields:
            if field in error_refs:
                diag_lines.append(f"**{field}**: {error_refs[field]}")
        if diag_lines:
            failure_text += "\n### Diagnostics\n\n" + "\n".join(diag_lines) + "\n"

    body += failure_text
    _write_frontmatter(task_file, meta, body)

    dest = cfg.tasks_failed / task_file.name
    shutil.move(str(task_file), str(dest))
    return dest


def decline_task(task_id: str, reason: str, *, config: Config | None = None) -> Path | None:
    """Decline a human task — moves to declined/ with reason appended.

    Automatically notifies the creating agent via direct message so they
    can adapt their approach. The declined file in declined/ is the record
    of truth; the message is the notification mechanism.
    """
    cfg = config or get_config()
    matches = list(cfg.tasks_queued.glob(f"{task_id}*"))
    if not matches:
        return None
    task_path = matches[0]
    meta, body = _parse_frontmatter(task_path)
    meta["status"] = "declined"
    body += f"\n\n## Declined\n\n**Date**: {_now_iso(config=cfg)}\n**Reason**: {reason}\n"
    _write_frontmatter(task_path, meta, body)
    dest = cfg.tasks_declined / task_path.name
    cfg.tasks_declined.mkdir(parents=True, exist_ok=True)
    shutil.move(str(task_path), str(dest))

    # Notify the creating agent so they can adapt
    created_by = meta.get("created_by", "")
    title = meta.get("title", task_id)
    if created_by and created_by != "human":
        send_message(
            from_agent="human",
            to_agent=created_by,
            subject=f"Declined: {title}",
            body=(
                f'The operator has declined task **{task_id}** ("{title}").\n\n'
                f"**Reason**: {reason}\n\n"
                f"The full task with decline details is at "
                f"`/company/agents/tasks/declined/{task_path.name}`.\n\n"
                f"Please read the reason, adapt your approach, and consider "
                f"whether there's an alternative that doesn't require human action."
            ),
            urgency="normal",
            config=cfg,
        )

    return dest


def list_human_tasks(*, config: Config | None = None) -> list[tuple[dict, str, Path]]:
    """List all queued tasks assigned to human, sorted by priority."""
    cfg = config or get_config()
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    results = []
    for task_path in sorted(cfg.tasks_queued.glob("*.md")):
        meta, body = _parse_frontmatter(task_path)
        if meta.get("assigned_to") == "human":
            results.append((meta, body, task_path))
    results.sort(key=lambda x: priority_order.get(x[0].get("priority", "medium"), 2))
    return results


def _move_task(
    task_id: str, from_dir: Path, to_dir: Path, new_status: str, extra_meta: dict | None = None
) -> Path | None:
    candidates = list(from_dir.glob(f"{task_id}*"))
    if not candidates:
        return None
    task_file = candidates[0]

    meta, body = _parse_frontmatter(task_file)
    meta["status"] = new_status
    if extra_meta:
        meta.update(extra_meta)
    _write_frontmatter(task_file, meta, body)

    dest = to_dir / task_file.name
    shutil.move(str(task_file), str(dest))
    return dest


# --- Messaging ---


def send_message(
    from_agent: str,
    to_agent: str,
    subject: str,
    body: str,
    urgency: str = "normal",
    requires_response: bool = False,
    thread: str | None = None,
    *,
    config: Config | None = None,
) -> str:
    """Send a message: write to recipient's inbox and sender's outbox."""
    cfg = config or get_config()
    date_prefix = datetime.now(cfg.tz).strftime("msg-%Y-%m%d")
    inbox = cfg.messages_dir / to_agent / "inbox"
    msg_id = next_id(date_prefix, inbox, config=cfg)

    meta = {
        "id": msg_id,
        "from": from_agent,
        "to": to_agent,
        "date": _now_iso(config=cfg),
        "subject": subject,
        "urgency": urgency,
        "requires_response": requires_response,
        "thread": thread,
    }

    # Write to recipient inbox
    inbox.mkdir(parents=True, exist_ok=True)
    _write_frontmatter(inbox / f"{msg_id}.md", meta, body)

    # Copy to sender outbox
    outbox = cfg.messages_dir / from_agent / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    _write_frontmatter(outbox / f"{msg_id}.md", meta, body)

    if to_agent == "human":
        _notify_message_for_human(meta, body, config=cfg)

    return msg_id


def _notify_message_for_human(meta: dict, body: str, *, config: Config) -> None:
    """Emit a notification when an agent sends a message to the human inbox.

    Best-effort: any failure here must not affect message delivery.
    """
    try:
        from .notifications import NotificationEvent, send_notification

        urgency = str(meta.get("urgency", "normal"))
        severity_map = {"normal": "info", "high": "warning", "critical": "critical"}
        severity = severity_map.get(urgency, "info")

        from_agent = str(meta.get("from", "unknown"))
        subject = str(meta.get("subject", "(no subject)"))
        requires_response = bool(meta.get("requires_response", False))

        title = f"Message from {from_agent}: {subject}"
        if requires_response:
            title = f"[response requested] {title}"

        send_notification(
            NotificationEvent(
                event_type="message_for_human",
                severity=severity,
                title=title,
                detail=body,
                agent_id=from_agent,
                refs={
                    "msg_id": meta.get("id", ""),
                    "urgency": urgency,
                    "requires_response": requires_response,
                    "thread": meta.get("thread") or "",
                },
            ),
            config=config,
        )
    except Exception:
        pass


def read_inbox(agent_id: str, *, config: Config | None = None) -> list[tuple[dict, str, Path]]:
    """Read unprocessed messages from an agent's inbox.

    Returns list of (metadata, body, path) tuples.
    """
    cfg = config or get_config()
    inbox = cfg.messages_dir / agent_id / "inbox"
    if not inbox.exists():
        return []

    messages = []
    for f in sorted(inbox.iterdir()):
        if not f.name.endswith(".md") or f.is_dir():
            continue
        meta, body = _parse_frontmatter(f)
        messages.append((meta, body, f))

    return messages


def mark_processed(msg_path: Path, *, config: Config | None = None) -> None:
    """Move a message to inbox/processed/."""
    processed_dir = msg_path.parent / "processed"
    processed_dir.mkdir(exist_ok=True)
    shutil.move(str(msg_path), str(processed_dir / msg_path.name))


# --- Logging ---


def log_action(
    agent_id: str,
    action: str,
    detail: str,
    refs: dict | None = None,
    *,
    level: str = "info",
    config: Config | None = None,
) -> None:
    """Append a JSONL log entry for an agent."""
    cfg = config or get_config()
    log_dir = cfg.logs_dir / agent_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{_today(config=cfg)}.jsonl"

    entry = {
        "timestamp": _now_iso(config=cfg),
        "agent": agent_id,
        "level": level,
        "action": action,
        "detail": detail,
        "refs": refs or {},
    }

    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


# --- Journals (temporal continuity between invocations) ---


def append_journal(agent_id: str, entry: str, *, config: Config | None = None) -> Path:
    """Append a dated entry to the agent's journal.

    Journals give agents temporal continuity — each invocation can read
    what previous invocations observed, decided, and deferred.
    """
    cfg = config or get_config()
    journal_file = cfg.logs_dir / agent_id / "journal.md"
    journal_file.parent.mkdir(parents=True, exist_ok=True)

    today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
    now = datetime.now(cfg.tz).strftime("%H:%M %Z")

    header = f"\n## {today} {now}\n\n"

    with open(journal_file, "a") as f:
        f.write(header + entry.strip() + "\n")

    return journal_file


def read_journal(agent_id: str, max_entries: int = 10, *, config: Config | None = None) -> str:
    """Read the most recent journal entries for an agent.

    Returns the last N entries as markdown text. Agents should read
    this at the start of standing orders to understand recent context.
    """
    cfg = config or get_config()
    journal_file = cfg.logs_dir / agent_id / "journal.md"
    if not journal_file.exists():
        return ""

    text = journal_file.read_text()
    # Split on "## " date headers, keep last N
    sections = text.split("\n## ")
    if not sections:
        return ""

    # First element might be empty or a file header, rest are entries
    if len(sections) > max_entries + 1:
        sections = ["", *sections[-max_entries:]]

    return "\n## ".join(sections).strip()


# --- Cadence tracking (when did a standing order last run?) ---


def check_cadence(agent_id: str, order_name: str, interval_hours: float, *, config: Config | None = None) -> bool:
    """Check if a standing order is due based on its cadence.

    Returns True if enough time has elapsed since last run (or never run).
    Uses a 30-minute tolerance to prevent drift: cadence is marked when the
    order *finishes*, but cron fires at a fixed time. Without tolerance,
    a 5-minute scan causes the cadence to slip forward 5 min/day until
    the cron window is missed entirely.
    """
    cfg = config or get_config()
    cadence_file = cfg.logs_dir / agent_id / f".cadence-{order_name}"
    if not cadence_file.exists():
        return True  # Never run → due now

    try:
        last_run = datetime.fromisoformat(cadence_file.read_text().strip())
        elapsed_hours = (datetime.now(cfg.tz) - last_run).total_seconds() / 3600
        tolerance_hours = 0.5  # 30 min buffer for execution time drift
        return elapsed_hours >= (interval_hours - tolerance_hours)
    except (ValueError, OSError):
        return True  # Corrupt file → treat as due


def mark_cadence(agent_id: str, order_name: str, *, config: Config | None = None) -> None:
    """Record that a standing order just ran."""
    cfg = config or get_config()
    cadence_file = cfg.logs_dir / agent_id / f".cadence-{order_name}"
    cadence_file.parent.mkdir(parents=True, exist_ok=True)
    cadence_file.write_text(datetime.now(cfg.tz).isoformat())


def get_last_cadence(agent_id: str, order_name: str, *, config: Config | None = None) -> float:
    """Get the timestamp (epoch seconds) of last cadence run.

    Returns 0.0 if never run.
    """
    cfg = config or get_config()
    cadence_file = cfg.logs_dir / agent_id / f".cadence-{order_name}"
    if not cadence_file.exists():
        return 0.0
    try:
        last_run = datetime.fromisoformat(cadence_file.read_text().strip())
        return last_run.timestamp()
    except (ValueError, OSError):
        return 0.0


# --- Cost tracking ---


def log_cost(
    agent_id: str,
    task_id: str | None,
    cost_usd: float,
    duration_ms: int,
    model: str,
    num_turns: int,
    *,
    config: Config | None = None,
) -> None:
    """Log invocation cost to /company/finance/costs/."""
    cfg = config or get_config()
    cfg.costs_dir.mkdir(parents=True, exist_ok=True)
    cost_file = cfg.costs_dir / f"{_today(config=cfg)}.jsonl"

    entry = {
        "timestamp": _now_iso(config=cfg),
        "agent": agent_id,
        "task": task_id,
        "cost_usd": cost_usd,
        "duration_ms": duration_ms,
        "model": model,
        "num_turns": num_turns,
    }

    with open(cost_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


# --- Working memory ---


def read_working_memory(agent_id: str, *, config: Config | None = None) -> str:
    """Read an agent's working memory document.

    Working memory represents what the agent is currently *thinking about* —
    distinct from journals (which record what happened). It is a living document
    updated every cycle, readable by all agents.
    """
    cfg = config or get_config()
    wm_file = cfg.agents_state_dir / agent_id / "working-memory.md"
    if not wm_file.exists():
        return ""
    return wm_file.read_text()


def read_old_memories(agent_id: str, *, config: Config | None = None) -> str:
    """Read an agent's old memories archive.

    Old memories are things the agent has 'forgotten' from working memory
    during dream cycles — pruned, compressed, or superseded content that's
    no longer in active recall but still accessible for mining.
    """
    cfg = config or get_config()
    old_mem_file = cfg.agents_state_dir / agent_id / "old-memories.md"
    if not old_mem_file.exists():
        return ""
    return old_mem_file.read_text()


def read_values(*, config: Config | None = None) -> str:
    """Read the company values document.

    Values are foundational beliefs auto-injected into every agent prompt.
    They shape judgment and counter inherited human-organization assumptions.
    """
    cfg = config or get_config()
    if not cfg.values_file.exists():
        return ""
    return cfg.values_file.read_text()


def read_soul(agent_id: str, *, config: Config | None = None) -> str:
    """Read an agent's soul document.

    The soul is the agent's inner life — who they are beyond their role,
    what they value, what worries them, how they see. It shapes judgment
    and attention across all other layers. Agents develop their own soul
    through weekly reflection.
    """
    cfg = config or get_config()
    soul_file = cfg.agents_state_dir / agent_id / "soul.md"
    if not soul_file.exists():
        return ""
    return soul_file.read_text()


# --- Company drives ---


def read_drives(*, config: Config | None = None) -> str:
    """Read the company-level drives document.

    Drives are persistent, unsatisfied goals with tension levels.
    All agents read this. Any agent can update it.
    """
    cfg = config or get_config()
    if not cfg.drives_file.exists():
        return ""
    return cfg.drives_file.read_text()


# --- Proposals ---


def list_active_proposals(*, config: Config | None = None) -> list[tuple[dict, str, Path]]:
    """List all active proposals awaiting deliberation.

    Returns list of (metadata, body, path) tuples.
    """
    cfg = config or get_config()
    if not cfg.proposals_active.exists():
        return []

    proposals = []
    for f in sorted(cfg.proposals_active.iterdir()):
        if not f.name.endswith(".md"):
            continue
        meta, body = _parse_frontmatter(f)
        proposals.append((meta, body, f))

    return proposals


# --- Broadcast channel ---


def read_broadcast(max_age_hours: int = 48, *, config: Config | None = None) -> list[tuple[dict, str, Path]]:
    """Read recent broadcast messages (the company-wide channel).

    Returns list of (metadata, body, path) tuples, sorted by filename (chronological).
    Messages older than max_age_hours are excluded from the prompt (but not moved).
    Messages stay in broadcast/ until archived to broadcast/archived/.
    """
    cfg = config or get_config()
    if not cfg.broadcast_dir.exists():
        return []

    import time

    cutoff = time.time() - (max_age_hours * 3600)

    messages = []
    for f in sorted(cfg.broadcast_dir.iterdir()):
        if not f.name.endswith(".md") or f.is_dir():
            continue
        if f.stat().st_mtime < cutoff:
            continue
        meta, body = _parse_frontmatter(f)
        messages.append((meta, body, f))

    return messages


def post_broadcast(from_id: str, subject: str, body: str, *, config: Config | None = None) -> str:
    """Post a message to the broadcast channel (visible to all agents).

    Returns the message ID.
    """
    cfg = config or get_config()
    cfg.broadcast_dir.mkdir(parents=True, exist_ok=True)
    date_prefix = datetime.now(cfg.tz).strftime("broadcast-%Y-%m%d")
    msg_id = next_id(date_prefix, cfg.broadcast_dir, config=cfg)

    meta = {
        "id": msg_id,
        "from": from_id,
        "date": _now_iso(config=cfg),
        "subject": subject,
    }

    _write_frontmatter(cfg.broadcast_dir / f"{msg_id}.md", meta, body)
    return msg_id


def archive_broadcast(msg_path: Path, *, config: Config | None = None) -> None:
    """Move a broadcast message to broadcast/archived/."""
    archived_dir = msg_path.parent / "archived"
    archived_dir.mkdir(exist_ok=True)
    shutil.move(str(msg_path), str(archived_dir / msg_path.name))


# --- Conversation threads ---


def get_active_threads(agent_id: str, *, config: Config | None = None) -> list[tuple[dict, str, Path]]:
    """Read active conversation threads for an agent.

    Returns threads where this agent is listed as a participant
    and status is 'active'.
    """
    cfg = config or get_config()
    if not cfg.threads_dir.exists():
        return []

    threads = []
    for f in sorted(cfg.threads_dir.iterdir()):
        if not f.name.endswith(".md") or f.is_dir():
            continue
        meta, body = _parse_frontmatter(f)
        participants = meta.get("participants", [])
        if agent_id in participants and meta.get("status") == "active":
            threads.append((meta, body, f))

    return threads


def get_pending_threads(agent_id: str, *, config: Config | None = None) -> list[tuple[dict, str, Path]]:
    """Return active threads with messages this agent hasn't responded to.

    A thread is 'pending' for an agent if:
    - They're a participant
    - The last message in the thread is NOT from them
    - Status is active
    """
    threads = get_active_threads(agent_id, config=config)
    pending = []
    for meta, body, path in threads:
        # Find the last responder by scanning for "## agent-xxx" headers
        last_responder = None
        for line in body.strip().split("\n"):
            if line.startswith("## agent-"):
                # Extract agent ID from "## agent-xxx-role — timestamp"
                last_responder = line.split("—")[0].strip("# ").strip()
        if last_responder and not last_responder.startswith(agent_id):
            pending.append((meta, body, path))
        elif meta.get("started_by") != agent_id and last_responder is None:
            # Thread with no responses yet, and we didn't start it
            pending.append((meta, body, path))
    return pending


def resolve_thread(thread_path: Path, *, config: Config | None = None) -> None:
    """Move a resolved thread to the resolved/ directory."""
    resolved_dir = thread_path.parent / "resolved"
    resolved_dir.mkdir(exist_ok=True)
    shutil.move(str(thread_path), str(resolved_dir / thread_path.name))


# --- Feedback / system notes ---


# --- Autonomy model ---


def get_autonomy_level(agent_id: str, *, config: Config | None = None) -> str:
    """Returns 'low', 'medium', or 'high' for the given agent."""
    cfg = config or get_config()
    return cfg.autonomy_agents.get(agent_id, cfg.autonomy_default)


def create_task(
    created_by: str,
    title: str,
    body: str,
    assigned_to: str | None = None,
    priority: str = "medium",
    *,
    destination: str | None = None,
    config: Config | None = None,
) -> tuple[str, str]:
    """Create a task. Returns (task_id, destination).

    When *destination* is provided ("backlog" or "queued"), the autonomy
    check is skipped and the task is placed directly.  This is used by
    the dashboard for human-created tasks.

    Otherwise the autonomy level of *created_by* decides:
    low autonomy -> PermissionError
    medium -> backlog/
    high -> queued/
    """
    cfg = config or get_config()

    date_prefix = datetime.now(cfg.tz).strftime("task-%Y-%m%d")

    if destination is not None:
        if destination not in ("backlog", "queued"):
            raise ValueError(f"Invalid destination: {destination!r}. Must be 'backlog' or 'queued'.")
        dest_dir = cfg.tasks_backlog if destination == "backlog" else cfg.tasks_queued
        level = "override"
    else:
        level = get_autonomy_level(created_by, config=cfg)
        if level == "low":
            raise PermissionError(f"Agent {created_by} has 'low' autonomy and cannot create tasks")
        if level == "medium":
            dest_dir = cfg.tasks_backlog
            destination = "backlog"
        else:  # high
            dest_dir = cfg.tasks_queued
            destination = "queued"

    dest_dir.mkdir(parents=True, exist_ok=True)
    task_id = next_id(date_prefix, dest_dir, config=cfg)

    meta = {
        "id": task_id,
        "title": title,
        "created_by": created_by,
        "assigned_to": assigned_to or "",
        "priority": priority,
        "status": destination,
        "created_at": _now_iso(config=cfg),
    }

    _write_frontmatter(dest_dir / f"{task_id}.md", meta, body)

    log_action(
        created_by,
        "task_created",
        f"Created task {task_id} -> {destination}",
        {"task_id": task_id, "destination": destination, "autonomy_level": level},
        config=cfg,
    )

    return task_id, destination


def create_task_human(
    title: str,
    body: str = "",
    assigned_to: str | None = None,
    priority: str = "medium",
    tags: list[str] | None = None,
    *,
    config: Config | None = None,
) -> tuple[str, str]:
    """Create a task as a human. Returns (task_id, destination).

    Default destination is backlog/. If assigned_to is provided,
    the task goes directly to queued/.
    """
    cfg = config or get_config()
    date_prefix = datetime.now(cfg.tz).strftime("task-%Y-%m%d")

    if assigned_to:
        dest_dir = cfg.tasks_queued
        destination = "queued"
    else:
        dest_dir = cfg.tasks_backlog
        destination = "backlog"

    dest_dir.mkdir(parents=True, exist_ok=True)
    task_id = next_id(date_prefix, dest_dir, config=cfg)

    meta: dict = {
        "id": task_id,
        "title": title,
        "created_by": "human",
        "assigned_to": assigned_to or "",
        "priority": priority,
        "status": destination,
        "tags": tags or [],
        "created_at": _now_iso(config=cfg),
    }

    _write_frontmatter(dest_dir / f"{task_id}.md", meta, body)

    # Detect bulk-created batches (3+ in same minute → non-promotable)
    if destination == "backlog":
        _detect_and_mark_batch(meta, config=cfg)

    return task_id, destination


def promote_task(task_id: str, *, config: Config | None = None) -> Path | None:
    """Move backlog/ -> queued/. Called by human via dashboard or CLI."""
    cfg = config or get_config()
    return _move_task(task_id, cfg.tasks_backlog, cfg.tasks_queued, "queued")


def agent_promote_task(
    task_id: str,
    by_agent_id: str,
    *,
    config: Config | None = None,
) -> Path:
    """Agent-initiated task promotion: backlog/ -> queued/.

    Unlike ``promote_task()`` (human-only, no guardrails), this enforces:

    - ``promotable: false`` flag (hard human veto)
    - Caller authorization (must be assignee or Steward)
    - Per-cycle and per-day rate limits

    Per decision-2026-0502-001.

    Returns:
        Path to the promoted task in queued/.

    Raises:
        FileNotFoundError: task not in backlog/ (or moved by another process).
        PermissionError: auth check, promotable veto, or rate-limit violation.
    """
    cfg = config or get_config()

    # Find the task in backlog
    candidates = list(cfg.tasks_backlog.glob(f"{task_id}*"))
    if not candidates:
        raise FileNotFoundError(f"Task {task_id} not found in backlog/")
    task_file = candidates[0]

    meta, body = _parse_frontmatter(task_file)

    # Hard veto: promotable: false
    if meta.get("promotable") is False:
        raise PermissionError(f"Task {task_id} has promotable: false — reserved for human promotion.")

    # Authorization: caller must be assignee or Steward
    assigned_to = meta.get("assigned_to", "")
    steward_id = "agent-000-steward"
    if by_agent_id != assigned_to and by_agent_id != steward_id:
        raise PermissionError(
            f"Agent {by_agent_id} cannot promote {task_id}: "
            f"must be the assignee ({assigned_to!r}) or the Steward ({steward_id})."
        )

    # Rate limits
    _check_promotion_rate_limits(by_agent_id, config=cfg)

    # Promote: update frontmatter and move
    meta["status"] = "queued"
    meta["promoted_by"] = by_agent_id
    meta["promoted_at"] = _now_iso(config=cfg)
    _write_frontmatter(task_file, meta, body)

    dest = cfg.tasks_queued / task_file.name
    try:
        shutil.move(str(task_file), str(dest))
    except (FileNotFoundError, OSError):
        raise FileNotFoundError(f"Task {task_id} was moved by another process during promotion.") from None

    log_action(
        by_agent_id,
        "task_promoted",
        f"Promoted {task_id} from backlog/ to queued/",
        {"task_id": task_id, "promoted_by": by_agent_id},
        config=cfg,
    )

    return dest


def _check_promotion_rate_limits(
    agent_id: str,
    *,
    config: Config | None = None,
) -> None:
    """Enforce per-cycle and per-day agent promotion rate limits.

    Per decision-2026-0502-001:
    - 2 promotions / agent / cycle (Steward: 5 / cycle)
    - 5 promotions / agent / calendar day

    Counts are derived from frontmatter scan of queued/ and in-progress/.

    Raises PermissionError if any limit is exceeded.
    """
    cfg = config or get_config()
    now = datetime.now(cfg.tz)

    cycle_minutes = cfg.schedule_cycles_interval_minutes
    cycle_cutoff = now - timedelta(minutes=cycle_minutes)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    cycle_count = 0
    day_count = 0

    for search_dir in (cfg.tasks_queued, cfg.tasks_in_progress):
        if not search_dir.exists():
            continue
        for f in search_dir.iterdir():
            if not f.name.endswith(".md"):
                continue
            meta, _ = _parse_frontmatter(f)
            if meta.get("promoted_by") != agent_id:
                continue
            promoted_at_str = meta.get("promoted_at")
            if not promoted_at_str:
                continue
            try:
                promoted_at = datetime.fromisoformat(str(promoted_at_str))
            except (ValueError, TypeError):
                continue

            if promoted_at >= day_start:
                day_count += 1
            if promoted_at >= cycle_cutoff:
                cycle_count += 1

    # Per-cycle limit: Steward gets 5, everyone else gets 2
    steward_id = "agent-000-steward"
    cycle_limit = 5 if agent_id == steward_id else 2
    if cycle_count >= cycle_limit:
        raise PermissionError(
            f"Per-cycle promotion limit reached: {cycle_count}/{cycle_limit} (last {cycle_minutes} min)."
        )

    # Per-day limit: 5 for all agents
    day_limit = 5
    if day_count >= day_limit:
        raise PermissionError(f"Per-day promotion limit reached: {day_count}/{day_limit} today.")


def demote_task(task_id: str, *, config: Config | None = None) -> Path | None:
    """Move a task from queued/ back to backlog/ (human-only rollback).

    Inverse of promotion — lets the exec chair undo a premature agent
    promotion. Clears ``promoted_by`` and ``promoted_at`` from frontmatter.
    """
    cfg = config or get_config()
    candidates = list(cfg.tasks_queued.glob(f"{task_id}*"))
    if not candidates:
        return None
    task_file = candidates[0]

    meta, body = _parse_frontmatter(task_file)
    meta["status"] = "backlog"
    meta.pop("promoted_by", None)
    meta.pop("promoted_at", None)
    _write_frontmatter(task_file, meta, body)

    dest = cfg.tasks_backlog / task_file.name
    shutil.move(str(task_file), str(dest))
    return dest


def reject_task(task_id: str, reason: str, *, config: Config | None = None) -> Path | None:
    """Move backlog/ -> declined/ with reason."""
    cfg = config or get_config()
    cfg.tasks_declined.mkdir(parents=True, exist_ok=True)
    candidates = list(cfg.tasks_backlog.glob(f"{task_id}*"))
    if not candidates:
        return None
    task_file = candidates[0]

    meta, body = _parse_frontmatter(task_file)
    meta["status"] = "declined"
    body += f"\n\n## Rejected\n\n**Date**: {_now_iso(config=cfg)}\n**Reason**: {reason}\n"
    _write_frontmatter(task_file, meta, body)

    dest = cfg.tasks_declined / task_file.name
    shutil.move(str(task_file), str(dest))

    # Notify the creating agent
    created_by = meta.get("created_by", "")
    title = meta.get("title", task_id)
    if created_by and created_by != "human":
        send_message(
            from_agent="human",
            to_agent=created_by,
            subject=f"Rejected from backlog: {title}",
            body=(
                f'Task **{task_id}** ("{title}") was rejected from the backlog.\n\n'
                f"**Reason**: {reason}\n\n"
                f"Consider an alternative approach or adjusting the scope."
            ),
            urgency="normal",
            config=cfg,
        )

    return dest


def _detect_and_mark_batch(new_meta: dict, *, config: Config | None = None) -> bool:
    """Detect bulk-created batches in backlog and mark them non-promotable.

    Rule: 3+ tasks with the same ``created_by`` and ``created_at`` within the
    same calendar minute -> all marked ``promotable: false``.

    Called after human task creation. Returns True if a batch was detected.

    Per decision-2026-0502-001: bulk-created exec-chair batches default to
    non-promotable, preventing agents from cherry-picking from curated sets.
    """
    cfg = config or get_config()
    created_by = new_meta.get("created_by", "")
    created_at_str = new_meta.get("created_at", "")
    if not created_by or not created_at_str:
        return False

    try:
        created_at = datetime.fromisoformat(str(created_at_str))
    except (ValueError, TypeError):
        return False

    minute_start = created_at.replace(second=0, microsecond=0)
    minute_end = minute_start + timedelta(minutes=1)

    if not cfg.tasks_backlog.exists():
        return False

    batch_files: list[Path] = []
    for f in cfg.tasks_backlog.iterdir():
        if not f.name.endswith(".md"):
            continue
        meta, _ = _parse_frontmatter(f)
        if meta.get("created_by") != created_by:
            continue
        task_ts_str = meta.get("created_at", "")
        try:
            task_ts = datetime.fromisoformat(str(task_ts_str))
        except (ValueError, TypeError):
            continue
        if minute_start <= task_ts < minute_end:
            batch_files.append(f)

    if len(batch_files) >= 3:
        for f in batch_files:
            meta, body = _parse_frontmatter(f)
            if meta.get("promotable") is not False:
                meta["promotable"] = False
                _write_frontmatter(f, meta, body)
        return True

    return False


def list_backlog(*, config: Config | None = None) -> list[tuple[dict, str, Path]]:
    """List all backlog items, sorted by priority."""
    cfg = config or get_config()
    if not cfg.tasks_backlog.exists():
        return []

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    results = []
    for task_path in sorted(cfg.tasks_backlog.glob("*.md")):
        meta, body = _parse_frontmatter(task_path)
        results.append((meta, body, task_path))
    results.sort(key=lambda x: priority_order.get(x[0].get("priority", "medium"), 2))
    return results


# --- Feedback / system notes ---


def read_feedback(*, status: str = "open", config: Config | None = None) -> list[tuple[dict, str, Path]]:
    """Read feedback/system notes with the given status.

    Returns list of (metadata, body, path) tuples, sorted newest first.
    Notes are submitted through the dashboard and read by agents during cycles.
    """
    cfg = config or get_config()
    feedback_dir = cfg.feedback_dir
    if not feedback_dir.exists():
        return []

    results = []
    for f in sorted(feedback_dir.glob("*.md"), reverse=True):
        meta, body = _parse_frontmatter(f)
        if meta.get("status") == status:
            results.append((meta, body, f))

    return results
