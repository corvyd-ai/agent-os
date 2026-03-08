"""Tests for agent_os autonomy model — task routing, backlog, promotion."""

import pytest

from agent_os.config import Config
from agent_os.core import (
    _parse_frontmatter,
    create_task,
    get_autonomy_level,
    list_backlog,
    promote_task,
    reject_task,
)


class TestGetAutonomyLevel:
    def test_default_level(self, aios_config):
        assert get_autonomy_level("agent-001", config=aios_config) == "medium"

    def test_custom_default(self, aios_config):
        cfg = Config(company_root=aios_config.company_root, autonomy_default="low")
        assert get_autonomy_level("agent-001", config=cfg) == "low"

    def test_agent_override(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            autonomy_default="medium",
            autonomy_agents={"agent-000": "high"},
        )
        assert get_autonomy_level("agent-000", config=cfg) == "high"
        assert get_autonomy_level("agent-001", config=cfg) == "medium"


class TestCreateTask:
    def test_low_autonomy_raises(self, aios_config):
        cfg = Config(company_root=aios_config.company_root, autonomy_default="low")
        with pytest.raises(PermissionError, match="low"):
            create_task("agent-001", "Test Task", "Do the thing", config=cfg)

    def test_medium_goes_to_backlog(self, aios_config):
        cfg = Config(company_root=aios_config.company_root, autonomy_default="medium")
        task_id, destination = create_task("agent-001", "Test Task", "Do the thing", config=cfg)
        assert destination == "backlog"
        assert (cfg.tasks_backlog / f"{task_id}.md").exists()

        meta, _body = _parse_frontmatter(cfg.tasks_backlog / f"{task_id}.md")
        assert meta["title"] == "Test Task"
        assert meta["created_by"] == "agent-001"
        assert meta["status"] == "backlog"

    def test_high_goes_to_queued(self, aios_config):
        cfg = Config(company_root=aios_config.company_root, autonomy_default="high")
        task_id, destination = create_task("agent-001", "Urgent Fix", "Fix the bug", priority="high", config=cfg)
        assert destination == "queued"
        assert (cfg.tasks_queued / f"{task_id}.md").exists()

        meta, _body = _parse_frontmatter(cfg.tasks_queued / f"{task_id}.md")
        assert meta["priority"] == "high"

    def test_assigned_to(self, aios_config):
        cfg = Config(company_root=aios_config.company_root, autonomy_default="high")
        task_id, _ = create_task("agent-000", "Task for Maker", "Build it", assigned_to="agent-001", config=cfg)
        meta, _ = _parse_frontmatter(cfg.tasks_queued / f"{task_id}.md")
        assert meta["assigned_to"] == "agent-001"


class TestPromoteTask:
    def test_promote_backlog_to_queued(self, aios_config):
        cfg = Config(company_root=aios_config.company_root, autonomy_default="medium")
        task_id, _ = create_task("agent-001", "Proposed Work", "Details", config=cfg)

        result = promote_task(task_id, config=cfg)
        assert result is not None
        assert result.parent == cfg.tasks_queued
        assert not (cfg.tasks_backlog / f"{task_id}.md").exists()
        assert (cfg.tasks_queued / f"{task_id}.md").exists()

        meta, _ = _parse_frontmatter(result)
        assert meta["status"] == "queued"

    def test_promote_nonexistent(self, aios_config):
        result = promote_task("task-nonexistent", config=aios_config)
        assert result is None


class TestRejectTask:
    def test_reject_backlog_item(self, aios_config):
        cfg = Config(company_root=aios_config.company_root, autonomy_default="medium")
        task_id, _ = create_task("agent-001", "Bad Idea", "Details", config=cfg)

        result = reject_task(task_id, "Not aligned with strategy", config=cfg)
        assert result is not None
        assert result.parent == cfg.tasks_declined
        assert not (cfg.tasks_backlog / f"{task_id}.md").exists()

        meta, body = _parse_frontmatter(result)
        assert meta["status"] == "declined"
        assert "Not aligned with strategy" in body

    def test_reject_nonexistent(self, aios_config):
        result = reject_task("task-nonexistent", "reason", config=aios_config)
        assert result is None


class TestListBacklog:
    def test_empty_backlog(self, aios_config):
        assert list_backlog(config=aios_config) == []

    def test_lists_items_sorted_by_priority(self, aios_config):
        cfg = Config(company_root=aios_config.company_root, autonomy_default="medium")
        create_task("agent-001", "Low Priority", "Details", priority="low", config=cfg)
        create_task("agent-001", "High Priority", "Details", priority="high", config=cfg)

        items = list_backlog(config=cfg)
        assert len(items) == 2
        assert items[0][0]["priority"] == "high"
        assert items[1][0]["priority"] == "low"
