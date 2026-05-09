"""Tests for stale task requeue (deadlock recovery).

Covers: normal completion (no requeue), stale claim with worktree,
stale claim without worktree, disabled config, terminal event protection.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from agent_os.config import Config
from agent_os.core import _parse_frontmatter, _write_frontmatter
from agent_os.maintenance import (
    _find_last_task_event,
    requeue_stale_tasks,
)


def _make_task(cfg: Config, task_id: str, agent_id: str) -> None:
    """Create a task file in in-progress/."""
    meta = {
        "id": task_id,
        "title": f"Test task {task_id}",
        "status": "in-progress",
        "priority": "medium",
        "assigned_to": agent_id,
    }
    _write_frontmatter(cfg.tasks_in_progress / f"{task_id}.md", meta, "Work to do.")


def _write_log_entry(
    cfg: Config,
    agent_id: str,
    action: str,
    task_id: str,
    *,
    minutes_ago: float = 0,
) -> None:
    """Write a JSONL log entry for an agent at a specific time offset."""
    log_dir = cfg.logs_dir / agent_id
    log_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(cfg.tz) - timedelta(minutes=minutes_ago)
    date_str = ts.strftime("%Y-%m-%d")
    log_file = log_dir / f"{date_str}.jsonl"

    entry = {
        "timestamp": ts.isoformat(),
        "agent": agent_id,
        "level": "info",
        "action": action,
        "detail": f"{action} for {task_id}",
        "refs": {"task_id": task_id},
    }

    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── Normal completion: no requeue ──────────────────────────────────


def test_no_requeue_when_recently_active(aios_config):
    """A task with recent log activity should NOT be requeued."""
    cfg = aios_config
    task_id = "task-2026-0507-001"
    agent_id = "agent-001-maker"

    _make_task(cfg, task_id, agent_id)
    # Log an sdk_invoke 5 minutes ago — well within the 30-minute threshold
    _write_log_entry(cfg, agent_id, "sdk_invoke", task_id, minutes_ago=5)

    result = requeue_stale_tasks(config=cfg)

    assert result.tasks_checked == 1
    assert result.tasks_requeued == 0
    assert len(result.requeued) == 0
    # Task should still be in in-progress/
    assert (cfg.tasks_in_progress / f"{task_id}.md").exists()


def test_no_requeue_when_terminal_event(aios_config):
    """A task whose last event is terminal (sdk_complete) should NOT be requeued."""
    cfg = aios_config
    task_id = "task-2026-0507-002"
    agent_id = "agent-001-maker"

    _make_task(cfg, task_id, agent_id)
    # Log an sdk_complete 60 minutes ago — old but terminal
    _write_log_entry(cfg, agent_id, "sdk_complete", task_id, minutes_ago=60)

    result = requeue_stale_tasks(config=cfg)

    assert result.tasks_requeued == 0
    assert (cfg.tasks_in_progress / f"{task_id}.md").exists()


# ── Stale claim without worktree ───────────────────────────────────


def test_requeue_stale_task_no_worktree(aios_config):
    """A task with old sdk_invoke and no worktree should be requeued."""
    cfg = aios_config
    task_id = "task-2026-0507-003"
    agent_id = "agent-001-maker"

    _make_task(cfg, task_id, agent_id)
    # Log an sdk_invoke 60 minutes ago — exceeds 30-minute threshold
    _write_log_entry(cfg, agent_id, "sdk_invoke", task_id, minutes_ago=60)

    result = requeue_stale_tasks(config=cfg)

    assert result.tasks_checked == 1
    assert result.tasks_requeued == 1
    assert task_id in result.requeued
    # Task should be moved to queued/
    assert (cfg.tasks_queued / f"{task_id}.md").exists()
    assert not (cfg.tasks_in_progress / f"{task_id}.md").exists()
    # Verify requeue note in body
    meta, body = _parse_frontmatter(cfg.tasks_queued / f"{task_id}.md")
    assert meta["status"] == "queued"
    assert "Requeued" in body
    assert "Stale claim" in body


# ── Stale claim with worktree preserved ────────────────────────────


def test_requeue_stale_task_with_worktree(aios_config):
    """A task with a worktree should be requeued AND the worktree preserved."""
    cfg = aios_config
    task_id = "task-2026-0507-004"
    agent_id = "agent-001-maker"

    _make_task(cfg, task_id, agent_id)
    _write_log_entry(cfg, agent_id, "sdk_invoke", task_id, minutes_ago=60)

    # Create a fake worktree directory
    worktree_path = cfg.worktrees_root / task_id
    worktree_path.mkdir(parents=True, exist_ok=True)
    (worktree_path / "some_file.py").write_text("# uncommitted work")

    result = requeue_stale_tasks(config=cfg)

    assert result.tasks_requeued == 1
    assert task_id in result.requeued
    # Worktree should still exist (preserved, not deleted)
    assert worktree_path.exists()
    assert (worktree_path / "some_file.py").exists()
    # Task moved to queued/
    assert (cfg.tasks_queued / f"{task_id}.md").exists()


# ── Disabled config ────────────────────────────────────────────────


def test_requeue_disabled_when_minutes_zero(aios_config, tmp_path):
    """Setting stale_task_requeue_minutes=0 disables the feature."""
    cfg = Config(company_root=aios_config.company_root, stale_task_requeue_minutes=0)
    task_id = "task-2026-0507-005"
    agent_id = "agent-001-maker"

    _make_task(cfg, task_id, agent_id)
    _write_log_entry(cfg, agent_id, "sdk_invoke", task_id, minutes_ago=60)

    result = requeue_stale_tasks(config=cfg)

    assert result.tasks_checked == 0
    assert result.tasks_requeued == 0
    # Task stays in in-progress/
    assert (cfg.tasks_in_progress / f"{task_id}.md").exists()


# ── No log events, mtime fallback ─────────────────────────────────


def test_requeue_no_log_events_uses_mtime(aios_config):
    """When no log events exist, file mtime is used as the fallback."""
    cfg = aios_config
    task_id = "task-2026-0507-006"
    agent_id = "agent-001-maker"

    _make_task(cfg, task_id, agent_id)
    # No log entries written — mtime of the task file is recent (just created)
    # so the task should NOT be requeued

    result = requeue_stale_tasks(config=cfg)

    assert result.tasks_requeued == 0


def test_requeue_no_log_events_old_mtime(aios_config):
    """When no log events exist and mtime is old, task should be requeued."""
    import os

    cfg = aios_config
    task_id = "task-2026-0507-007"
    agent_id = "agent-001-maker"

    _make_task(cfg, task_id, agent_id)

    # Backdate the file mtime to 60 minutes ago
    task_path = cfg.tasks_in_progress / f"{task_id}.md"
    old_time = datetime.now(UTC).timestamp() - (60 * 60)
    os.utime(task_path, (old_time, old_time))

    result = requeue_stale_tasks(config=cfg)

    assert result.tasks_requeued == 1
    assert task_id in result.requeued


# ── Event logged ───────────────────────────────────────────────────


def test_requeue_logs_event(aios_config):
    """Requeue should log a task_requeued_stale_claim event."""
    cfg = aios_config
    task_id = "task-2026-0507-008"
    agent_id = "agent-001-maker"

    _make_task(cfg, task_id, agent_id)
    _write_log_entry(cfg, agent_id, "sdk_invoke", task_id, minutes_ago=60)

    requeue_stale_tasks(config=cfg)

    # Check system log for the requeue event
    today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
    system_log = cfg.logs_dir / "system" / f"{today}.jsonl"
    assert system_log.exists()

    found = False
    for line in system_log.read_text().splitlines():
        entry = json.loads(line)
        if entry["action"] == "task_requeued_stale_claim":
            assert entry["refs"]["task_id"] == task_id
            assert entry["refs"]["agent_id"] == agent_id
            assert entry["refs"]["elapsed_minutes"] > 0
            found = True
            break
    assert found, "task_requeued_stale_claim event not found in system log"


# ── Multiple tasks: mix of stale and active ────────────────────────


def test_requeue_mixed_tasks(aios_config):
    """Only stale tasks are requeued; active ones are left alone."""
    cfg = aios_config
    agent_id = "agent-001-maker"

    # Active task (recent activity)
    _make_task(cfg, "task-2026-0507-010", agent_id)
    _write_log_entry(cfg, agent_id, "sdk_invoke", "task-2026-0507-010", minutes_ago=5)

    # Stale task (old activity)
    _make_task(cfg, "task-2026-0507-011", agent_id)
    _write_log_entry(cfg, agent_id, "sdk_invoke", "task-2026-0507-011", minutes_ago=60)

    result = requeue_stale_tasks(config=cfg)

    assert result.tasks_checked == 2
    assert result.tasks_requeued == 1
    assert "task-2026-0507-011" in result.requeued
    assert "task-2026-0507-010" not in result.requeued
    # Active task still in progress
    assert (cfg.tasks_in_progress / "task-2026-0507-010.md").exists()
    # Stale task moved to queued
    assert (cfg.tasks_queued / "task-2026-0507-011.md").exists()


# ── _find_last_task_event helper ───────────────────────────────────


def test_find_last_task_event_found(aios_config):
    """Helper finds the most recent event for a task."""
    cfg = aios_config
    agent_id = "agent-001-maker"
    task_id = "task-2026-0507-012"

    _write_log_entry(cfg, agent_id, "claimed_task", task_id, minutes_ago=60)
    _write_log_entry(cfg, agent_id, "sdk_invoke", task_id, minutes_ago=55)

    ts, action = _find_last_task_event(agent_id, task_id, config=cfg)

    assert ts is not None
    assert action == "sdk_invoke"


def test_find_last_task_event_not_found(aios_config):
    """Helper returns None when no events exist for the task."""
    cfg = aios_config

    ts, action = _find_last_task_event("agent-001-maker", "task-nonexistent", config=cfg)

    assert ts is None
    assert action is None


def test_find_last_task_event_uses_task_key(aios_config):
    """Helper should find events that use 'task' instead of 'task_id' in refs."""
    cfg = aios_config
    agent_id = "agent-001-maker"
    task_id = "task-2026-0507-013"

    # Write an entry that uses "task" key (like sdk_complete does)
    log_dir = cfg.logs_dir / agent_id
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(cfg.tz) - timedelta(minutes=10)
    log_file = log_dir / f"{ts.strftime('%Y-%m-%d')}.jsonl"
    entry = {
        "timestamp": ts.isoformat(),
        "agent": agent_id,
        "level": "info",
        "action": "sdk_complete",
        "detail": "Done",
        "refs": {"task": task_id, "cost_usd": 1.23},
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")

    found_ts, found_action = _find_last_task_event(agent_id, task_id, config=cfg)

    assert found_ts is not None
    assert found_action == "sdk_complete"


# ── Unassigned tasks ───────────────────────────────────────────────


def test_requeue_skips_unassigned_tasks(aios_config):
    """Tasks without assigned_to should be skipped."""
    cfg = aios_config
    task_id = "task-2026-0507-014"

    # Create task with no agent assigned
    meta = {
        "id": task_id,
        "title": "Unassigned task",
        "status": "in-progress",
        "priority": "medium",
        "assigned_to": "",
    }
    _write_frontmatter(cfg.tasks_in_progress / f"{task_id}.md", meta, "Work.")

    result = requeue_stale_tasks(config=cfg)

    assert result.tasks_checked == 1
    assert result.tasks_requeued == 0


# ── Custom threshold ───────────────────────────────────────────────


def test_requeue_respects_custom_threshold(aios_config):
    """A custom stale_task_requeue_minutes threshold should be respected."""
    # Use a 120-minute threshold
    cfg = Config(
        company_root=aios_config.company_root,
        stale_task_requeue_minutes=120,
    )
    task_id = "task-2026-0507-015"
    agent_id = "agent-001-maker"

    _make_task(cfg, task_id, agent_id)
    # 60 minutes ago — within 120-minute threshold
    _write_log_entry(cfg, agent_id, "sdk_invoke", task_id, minutes_ago=60)

    result = requeue_stale_tasks(config=cfg)

    assert result.tasks_requeued == 0
    assert (cfg.tasks_in_progress / f"{task_id}.md").exists()
