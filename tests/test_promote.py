"""Tests for agent-initiated task promotion, demotion, and batch detection.

Covers decision-2026-0502-001: high-autonomy agent self-promotion of backlog items.
"""

from datetime import datetime, timedelta

import pytest

from agent_os.config import Config
from agent_os.core import (
    _parse_frontmatter,
    _write_frontmatter,
    agent_promote_task,
    create_task_human,
    demote_task,
)


def _make_backlog_task(
    cfg,
    task_id="task-2026-0502-001",
    assigned_to="agent-001-maker",
    promotable=None,
    **extra_meta,
):
    """Helper: create a task file directly in backlog/."""
    meta = {
        "id": task_id,
        "title": "Test Task",
        "created_by": "human",
        "assigned_to": assigned_to,
        "priority": "medium",
        "status": "backlog",
        "created_at": datetime.now(cfg.tz).isoformat(),
    }
    if promotable is not None:
        meta["promotable"] = promotable
    meta.update(extra_meta)
    cfg.tasks_backlog.mkdir(parents=True, exist_ok=True)
    path = cfg.tasks_backlog / f"{task_id}.md"
    _write_frontmatter(path, meta, "Task body.\n")
    return path


class TestAgentPromoteTask:
    """Tests for agent_promote_task() — the guarded promotion path."""

    def test_happy_path(self, aios_config):
        """Assignee can promote their own task from backlog to queued."""
        cfg = aios_config
        _make_backlog_task(cfg, assigned_to="agent-001-maker")

        result = agent_promote_task("task-2026-0502-001", "agent-001-maker", config=cfg)

        assert result.parent == cfg.tasks_queued
        assert not (cfg.tasks_backlog / "task-2026-0502-001.md").exists()
        assert (cfg.tasks_queued / "task-2026-0502-001.md").exists()

        meta, _ = _parse_frontmatter(result)
        assert meta["status"] == "queued"
        assert meta["promoted_by"] == "agent-001-maker"
        assert "promoted_at" in meta

    def test_steward_can_promote_any_task(self, aios_config):
        """Steward can promote tasks assigned to other agents."""
        cfg = aios_config
        _make_backlog_task(cfg, assigned_to="agent-001-maker")

        result = agent_promote_task("task-2026-0502-001", "agent-000-steward", config=cfg)

        assert result is not None
        meta, _ = _parse_frontmatter(result)
        assert meta["promoted_by"] == "agent-000-steward"

    def test_promotable_false_rejected(self, aios_config):
        """Tasks with promotable: false cannot be promoted by agents."""
        cfg = aios_config
        _make_backlog_task(cfg, assigned_to="agent-001-maker", promotable=False)

        with pytest.raises(PermissionError, match="promotable: false"):
            agent_promote_task("task-2026-0502-001", "agent-001-maker", config=cfg)

        # Task stays in backlog
        assert (cfg.tasks_backlog / "task-2026-0502-001.md").exists()

    def test_wrong_caller_rejected(self, aios_config):
        """Non-assignee, non-Steward agents cannot promote."""
        cfg = aios_config
        _make_backlog_task(cfg, assigned_to="agent-001-maker")

        with pytest.raises(PermissionError, match="cannot promote"):
            agent_promote_task("task-2026-0502-001", "agent-005-grower", config=cfg)

    def test_nonexistent_task(self, aios_config):
        """Promoting a nonexistent task raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="not found"):
            agent_promote_task("task-nonexistent", "agent-001-maker", config=aios_config)

    def test_per_cycle_rate_limit(self, aios_config):
        """Exceeding per-cycle promotion limit (2) raises PermissionError."""
        cfg = Config(
            company_root=aios_config.company_root,
            schedule_cycles_interval_minutes=15,
        )
        # Promote 2 tasks (the per-cycle limit for non-Steward)
        for i in range(1, 3):
            tid = f"task-2026-0502-{i:03d}"
            _make_backlog_task(cfg, task_id=tid, assigned_to="agent-001-maker")
            agent_promote_task(tid, "agent-001-maker", config=cfg)

        # Third should fail
        _make_backlog_task(cfg, task_id="task-2026-0502-003", assigned_to="agent-001-maker")
        with pytest.raises(PermissionError, match="Per-cycle"):
            agent_promote_task("task-2026-0502-003", "agent-001-maker", config=cfg)

    def test_steward_higher_cycle_limit(self, aios_config):
        """Steward gets 5 promotions per cycle instead of 2."""
        cfg = Config(
            company_root=aios_config.company_root,
            schedule_cycles_interval_minutes=15,
        )
        # Steward promotes 5 tasks successfully
        for i in range(1, 6):
            tid = f"task-2026-0502-{i:03d}"
            _make_backlog_task(cfg, task_id=tid, assigned_to="agent-000-steward")
            agent_promote_task(tid, "agent-000-steward", config=cfg)

        # 6th should fail
        _make_backlog_task(cfg, task_id="task-2026-0502-006", assigned_to="agent-000-steward")
        with pytest.raises(PermissionError, match="Per-cycle"):
            agent_promote_task("task-2026-0502-006", "agent-000-steward", config=cfg)

    def test_per_day_rate_limit(self, aios_config):
        """Exceeding per-day promotion limit (5) raises PermissionError."""
        cfg = Config(
            company_root=aios_config.company_root,
            # Very short cycle window so cycle limit doesn't trigger
            schedule_cycles_interval_minutes=1,
        )
        now = datetime.now(cfg.tz)

        # Promote 5 tasks, adjusting timestamps to be outside the
        # 1-minute cycle window but still today
        for i in range(1, 6):
            tid = f"task-2026-0502-{i:03d}"
            _make_backlog_task(cfg, task_id=tid, assigned_to="agent-001-maker")
            result = agent_promote_task(tid, "agent-001-maker", config=cfg)
            # Move promoted_at outside cycle window (5 min ago) but same day
            meta, body = _parse_frontmatter(result)
            earlier = (now - timedelta(minutes=5)).isoformat()
            meta["promoted_at"] = earlier
            _write_frontmatter(result, meta, body)

        # 6th should fail on daily limit
        _make_backlog_task(cfg, task_id="task-2026-0502-006", assigned_to="agent-001-maker")
        with pytest.raises(PermissionError, match="Per-day"):
            agent_promote_task("task-2026-0502-006", "agent-001-maker", config=cfg)

    def test_concurrent_promotion_handled(self, aios_config):
        """Two promotions of the same task: first succeeds, second fails.

        The OS-level atomicity of file rename (shutil.move → os.rename)
        ensures only one wins. The second attempt finds the task gone
        from backlog/ and raises FileNotFoundError.
        """
        cfg = aios_config
        _make_backlog_task(cfg, assigned_to="agent-001-maker")

        # First promotion succeeds
        result = agent_promote_task("task-2026-0502-001", "agent-001-maker", config=cfg)
        assert result is not None

        # Second attempt: task no longer in backlog
        with pytest.raises(FileNotFoundError):
            agent_promote_task("task-2026-0502-001", "agent-001-maker", config=cfg)


class TestDemoteTask:
    """Tests for demote_task() — human-only rollback from queued to backlog."""

    def test_happy_path(self, aios_config):
        """Demote moves task from queued back to backlog, clearing promotion metadata."""
        cfg = aios_config
        _make_backlog_task(cfg, assigned_to="agent-001-maker")
        agent_promote_task("task-2026-0502-001", "agent-001-maker", config=cfg)
        assert (cfg.tasks_queued / "task-2026-0502-001.md").exists()

        result = demote_task("task-2026-0502-001", config=cfg)

        assert result is not None
        assert result.parent == cfg.tasks_backlog
        assert not (cfg.tasks_queued / "task-2026-0502-001.md").exists()

        meta, _ = _parse_frontmatter(result)
        assert meta["status"] == "backlog"
        assert "promoted_by" not in meta
        assert "promoted_at" not in meta

    def test_demote_nonexistent(self, aios_config):
        """Demoting a nonexistent task returns None."""
        result = demote_task("task-nonexistent", config=aios_config)
        assert result is None


class TestBatchDetection:
    """Tests for bulk-created batch detection in create_task_human."""

    def test_three_tasks_same_minute_marked(self, aios_config):
        """Three tasks by the same creator in the same minute get promotable: false."""
        cfg = aios_config
        ids = []
        for i in range(3):
            task_id, dest = create_task_human(f"Batch task {i}", body="Details", config=cfg)
            assert dest == "backlog"
            ids.append(task_id)

        # All should be marked non-promotable
        for tid in ids:
            meta, _ = _parse_frontmatter(cfg.tasks_backlog / f"{tid}.md")
            assert meta.get("promotable") is False, f"{tid} should be non-promotable"

    def test_two_tasks_not_marked(self, aios_config):
        """Two tasks in the same minute are NOT marked non-promotable."""
        cfg = aios_config
        ids = []
        for i in range(2):
            task_id, _dest = create_task_human(f"Small batch {i}", body="Details", config=cfg)
            ids.append(task_id)

        for tid in ids:
            meta, _ = _parse_frontmatter(cfg.tasks_backlog / f"{tid}.md")
            assert meta.get("promotable") is not False

    def test_assigned_tasks_skip_detection(self, aios_config):
        """Assigned tasks go to queued/, not backlog, so no batch detection."""
        cfg = aios_config
        for i in range(3):
            _task_id, dest = create_task_human(
                f"Assigned task {i}",
                body="Details",
                assigned_to="agent-001-maker",
                config=cfg,
            )
            assert dest == "queued"

        # Queued tasks should not have promotable: false
        for f in cfg.tasks_queued.iterdir():
            if f.name.endswith(".md"):
                meta, _ = _parse_frontmatter(f)
                assert meta.get("promotable") is not False

    def test_batch_detection_blocks_agent_promotion(self, aios_config):
        """Batch-detected tasks cannot be promoted by agents."""
        cfg = aios_config
        ids = []
        for i in range(3):
            task_id, _ = create_task_human(
                f"Batch task {i}",
                body="Details",
                assigned_to="agent-001-maker",
                config=cfg,
            )
            ids.append(task_id)

        # These went to queued (assigned), so create batch in backlog manually
        batch_ids = []
        for i in range(3):
            task_id, _ = create_task_human(f"Backlog batch {i}", body="Details", config=cfg)
            batch_ids.append(task_id)

        # Update the assigned_to so agent can try to promote
        for tid in batch_ids:
            path = cfg.tasks_backlog / f"{tid}.md"
            meta, body = _parse_frontmatter(path)
            meta["assigned_to"] = "agent-001-maker"
            _write_frontmatter(path, meta, body)

        # Agent should be blocked by promotable: false
        with pytest.raises(PermissionError, match="promotable: false"):
            agent_promote_task(batch_ids[0], "agent-001-maker", config=cfg)
