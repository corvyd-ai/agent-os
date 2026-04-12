"""Tests for agent_os.status — compact system status overview."""

import json
from datetime import datetime, timedelta

from agent_os.config import Config
from agent_os.status import format_status


def _create_agent(cfg: Config, agent_id: str, name: str, role: str = "Software Engineer") -> None:
    """Create a minimal agent registry file."""
    cfg.registry_dir.mkdir(parents=True, exist_ok=True)
    registry_file = cfg.registry_dir / f"{agent_id}.md"
    registry_file.write_text(f"---\nid: {agent_id}\nname: {name}\nrole: {role}\n---\n\nI am {name}.\n")


def _create_task(cfg: Config, task_id: str, status_dir: str, assigned_to: str = "") -> None:
    """Create a minimal task file in the given status directory."""
    d = cfg.tasks_dir / status_dir
    d.mkdir(parents=True, exist_ok=True)
    meta = f"---\nid: {task_id}\ntitle: Test task\nassigned_to: {assigned_to}\npriority: medium\n---\n\nDo the thing.\n"
    (d / f"{task_id}.md").write_text(meta)


def _write_log_entry(cfg: Config, agent_id: str, minutes_ago: int = 5) -> None:
    """Write a JSONL log entry for an agent."""
    log_dir = cfg.logs_dir / agent_id
    log_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(cfg.tz)
    ts = now - timedelta(minutes=minutes_ago)
    today = now.strftime("%Y-%m-%d")
    log_file = log_dir / f"{today}.jsonl"
    entry = {
        "timestamp": ts.isoformat(),
        "agent": agent_id,
        "action": "cycle_start",
        "detail": "test",
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _write_cost_entry(cfg: Config, cost_usd: float) -> None:
    """Write a cost entry for today."""
    cfg.costs_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
    cost_file = cfg.costs_dir / f"{today}.jsonl"
    entry = {
        "timestamp": f"{today}T12:00:00+00:00",
        "agent": "agent-001",
        "task": "test-task",
        "cost_usd": cost_usd,
    }
    with open(cost_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _create_inbox_message(cfg: Config, agent_id: str = "human") -> None:
    """Create a message in an agent's inbox."""
    inbox = cfg.messages_dir / agent_id / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "msg-001.md").write_text("---\nid: msg-001\nfrom: agent-001\nto: human\nsubject: Test\n---\n\nHello.\n")


class TestFormatStatusNoAgents:
    def test_shows_zero_agents(self, aios_config):
        output, _code = format_status(no_color=True, config=aios_config)
        assert "0 agents" in output

    def test_exit_code_healthy(self, aios_config):
        _output, code = format_status(no_color=True, config=aios_config)
        assert code == 0


class TestFormatStatusWithAgents:
    def test_shows_agent_names(self, aios_config):
        _create_agent(aios_config, "agent-001-builder", "The Builder")
        _create_agent(aios_config, "agent-002-writer", "The Writer")

        output, _code = format_status(no_color=True, config=aios_config)
        assert "The Builder" in output
        assert "The Writer" in output

    def test_idle_agent_shows_idle(self, aios_config):
        _create_agent(aios_config, "agent-001-builder", "The Builder")

        output, _code = format_status(no_color=True, config=aios_config)
        assert "idle" in output

    def test_agent_with_last_cycle(self, aios_config):
        _create_agent(aios_config, "agent-001-builder", "The Builder")
        _write_log_entry(aios_config, "agent-001-builder", minutes_ago=12)

        output, _code = format_status(no_color=True, config=aios_config)
        assert "12 min ago" in output

    def test_agent_never_ran(self, aios_config):
        _create_agent(aios_config, "agent-001-builder", "The Builder")

        output, _code = format_status(no_color=True, config=aios_config)
        assert "never" in output


class TestFormatStatusWorkingOnTask:
    def test_shows_working_on_task(self, aios_config):
        _create_agent(aios_config, "agent-001-builder", "The Builder")
        _create_task(
            aios_config,
            "task-2026-0412-003",
            "in-progress",
            assigned_to="agent-001-builder",
        )

        output, _code = format_status(no_color=True, config=aios_config)
        assert "working on task-2026-0412-003" in output


class TestFormatStatusTaskCounts:
    def test_shows_task_counts(self, aios_config):
        _create_task(aios_config, "task-001", "queued")
        _create_task(aios_config, "task-002", "queued")
        _create_task(aios_config, "task-003", "in-progress", assigned_to="agent-001")
        _create_task(aios_config, "task-004", "done")

        output, _code = format_status(no_color=True, config=aios_config)
        assert "queued: 2" in output
        assert "in-progress: 1" in output
        assert "done: 1" in output

    def test_backlog_shown_when_present(self, aios_config):
        _create_task(aios_config, "task-001", "backlog")

        output, _code = format_status(no_color=True, config=aios_config)
        assert "backlog: 1" in output

    def test_in_review_shown_when_present(self, aios_config):
        _create_task(aios_config, "task-001", "in-review")

        output, _code = format_status(no_color=True, config=aios_config)
        assert "in-review: 1" in output


class TestFormatStatusBudget:
    def test_budget_display(self, aios_config):
        _write_cost_entry(aios_config, 8.42)

        output, _code = format_status(no_color=True, config=aios_config)
        assert "$8.42" in output
        assert "Budget today" in output
        assert "Budget weekly" in output

    def test_zero_budget(self, aios_config):
        output, _code = format_status(no_color=True, config=aios_config)
        assert "$0.00" in output


class TestFormatStatusNeedsAttention:
    def test_backlog_attention(self, aios_config):
        _create_task(aios_config, "task-001", "backlog")

        output, code = format_status(no_color=True, config=aios_config)
        assert "Needs attention:" in output
        assert "1 backlog item awaiting promotion" in output
        assert code == 1

    def test_human_inbox_attention(self, aios_config):
        _create_inbox_message(aios_config, "human")

        output, code = format_status(no_color=True, config=aios_config)
        assert "Needs attention:" in output
        assert "1 message in human inbox" in output
        assert code == 1

    def test_in_review_attention(self, aios_config):
        _create_task(aios_config, "task-001", "in-review")

        output, code = format_status(no_color=True, config=aios_config)
        assert "Needs attention:" in output
        assert "1 task awaiting review" in output
        assert code == 1

    def test_circuit_breaker_attention(self, aios_config):
        # Default daily cap is 100.00 — write enough to exceed it
        _write_cost_entry(aios_config, 105.00)

        output, code = format_status(no_color=True, config=aios_config)
        assert "Needs attention:" in output
        assert "circuit breaker tripped" in output.lower()
        assert code == 1

    def test_no_attention_healthy(self, aios_config):
        output, code = format_status(no_color=True, config=aios_config)
        assert "Needs attention:" not in output
        assert code == 0


class TestFormatStatusExitCode:
    def test_healthy_exit_code(self, aios_config):
        _output, code = format_status(no_color=True, config=aios_config)
        assert code == 0

    def test_unhealthy_exit_code(self, aios_config):
        _create_task(aios_config, "task-001", "backlog")
        _output, code = format_status(no_color=True, config=aios_config)
        assert code == 1


class TestFormatStatusNoColor:
    def test_no_ansi_escapes(self, aios_config):
        _create_agent(aios_config, "agent-001-builder", "The Builder")
        _create_task(aios_config, "task-001", "backlog")

        output, _code = format_status(no_color=True, config=aios_config)
        assert "\033[" not in output


class TestFormatStatusScheduleLabel:
    def test_disabled_schedule(self, aios_config):
        cfg = Config(company_root=aios_config.company_root, schedule_enabled=False)
        # Rebuild directory tree for the new config
        cfg.registry_dir.mkdir(parents=True, exist_ok=True)

        output, _code = format_status(no_color=True, config=cfg)
        assert "schedule: disabled" in output

    def test_enabled_schedule(self, aios_config):
        output, _code = format_status(no_color=True, config=aios_config)
        # Default schedule_enabled is True and no operating hours means active
        assert "schedule: active" in output
