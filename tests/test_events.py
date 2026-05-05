"""Tests for agent_os.events — cycle outcome and dispatch skipped events."""

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from agent_os.config import Config
from agent_os.events import (
    CycleOutcomeEvent,
    DispatchSkippedEvent,
    emit_cycle_outcome,
    emit_dispatch_skipped,
    format_dispatch_status,
    get_dispatch_status,
)

# --- CycleOutcomeEvent ---


class TestCycleOutcomeEvent:
    def test_to_dict_includes_event_field(self):
        event = CycleOutcomeEvent(
            task_id="task-2026-0419-001",
            agent="agent-001-maker",
            cycle_type="task",
            process_status="completed",
            artifact_status="completed",
            artifact_type="task_completion",
        )
        d = event.to_dict()
        assert d["event"] == "cycle_outcome"
        assert d["task_id"] == "task-2026-0419-001"
        assert d["process_status"] == "completed"
        assert d["artifact_status"] == "completed"

    def test_to_dict_omits_empty_optional_fields(self):
        event = CycleOutcomeEvent(
            task_id="task-001",
            agent="agent-001",
            cycle_type="task",
            process_status="completed",
            artifact_status="none",
        )
        d = event.to_dict()
        assert "artifact_ref" not in d
        assert "failure_reason" not in d
        assert "workspace_git_commit" not in d
        assert "workspace_git_push" not in d
        assert "workspace_pr_url" not in d

    def test_to_dict_includes_workspace_fields_when_set(self):
        event = CycleOutcomeEvent(
            task_id="task-001",
            agent="agent-001",
            cycle_type="task",
            process_status="completed",
            artifact_status="completed",
            artifact_type="github_pr",
            artifact_ref="https://github.com/org/repo/compare/main...agent/task-001",
            workspace_git_commit="abc1234",
            workspace_git_push=True,
            workspace_pr_url="https://github.com/org/repo/compare/main...agent/task-001",
        )
        d = event.to_dict()
        assert d["workspace_git_commit"] == "abc1234"
        assert d["workspace_git_push"] is True
        assert d["workspace_pr_url"] == "https://github.com/org/repo/compare/main...agent/task-001"

    def test_to_dict_includes_failure_reason(self):
        event = CycleOutcomeEvent(
            task_id="task-001",
            agent="agent-001",
            cycle_type="task",
            process_status="completed",
            artifact_status="failed",
            failure_reason="git commit failed: author identity unknown",
        )
        d = event.to_dict()
        assert d["failure_reason"] == "git commit failed: author identity unknown"

    def test_to_dict_is_json_serializable(self):
        event = CycleOutcomeEvent(
            task_id="task-001",
            agent="agent-001",
            cycle_type="task",
            process_status="completed",
            artifact_status="completed",
            workspace_git_push=True,
        )
        # Should not raise
        json.dumps(event.to_dict())


class TestEmitCycleOutcome:
    def test_writes_to_agent_log(self, aios_config):
        event = CycleOutcomeEvent(
            task_id="task-001",
            agent="agent-001-maker",
            cycle_type="task",
            process_status="completed",
            artifact_status="completed",
            artifact_type="task_completion",
        )
        emit_cycle_outcome(event, config=aios_config)

        log_dir = aios_config.logs_dir / "agent-001-maker"
        assert log_dir.exists()
        log_files = list(log_dir.glob("*.jsonl"))
        assert len(log_files) == 1

        entries = [json.loads(line) for line in log_files[0].read_text().splitlines()]
        assert len(entries) == 1
        assert entries[0]["action"] == "cycle_outcome"
        assert entries[0]["level"] == "info"
        assert entries[0]["refs"]["event"] == "cycle_outcome"
        assert entries[0]["refs"]["process_status"] == "completed"

    def test_failed_artifact_logs_as_warn(self, aios_config):
        event = CycleOutcomeEvent(
            task_id="task-001",
            agent="agent-001-maker",
            cycle_type="task",
            process_status="completed",
            artifact_status="failed",
            failure_reason="Quality gates failed",
        )
        emit_cycle_outcome(event, config=aios_config)

        log_files = list((aios_config.logs_dir / "agent-001-maker").glob("*.jsonl"))
        entries = [json.loads(line) for line in log_files[0].read_text().splitlines()]
        assert entries[0]["level"] == "warn"

    def test_error_process_logs_as_warn(self, aios_config):
        event = CycleOutcomeEvent(
            task_id="task-001",
            agent="agent-001-maker",
            cycle_type="task",
            process_status="error",
            artifact_status="none",
            failure_reason="SDK crashed",
        )
        emit_cycle_outcome(event, config=aios_config)

        log_files = list((aios_config.logs_dir / "agent-001-maker").glob("*.jsonl"))
        entries = [json.loads(line) for line in log_files[0].read_text().splitlines()]
        assert entries[0]["level"] == "warn"


# --- DispatchSkippedEvent ---


class TestDispatchSkippedEvent:
    def test_to_dict_includes_event_field(self):
        event = DispatchSkippedEvent(
            agent="agent-001-maker",
            cycle_type="cycle",
            reason="cooldown_active",
            next_eligible="2026-04-21T02:10:00Z",
        )
        d = event.to_dict()
        assert d["event"] == "dispatch_skipped"
        assert d["agent"] == "agent-001-maker"
        assert d["reason"] == "cooldown_active"
        assert d["next_eligible"] == "2026-04-21T02:10:00Z"

    def test_to_dict_omits_none_next_eligible(self):
        event = DispatchSkippedEvent(
            agent="agent-001",
            cycle_type="drives",
            reason="outside_operating_hours",
        )
        d = event.to_dict()
        assert "next_eligible" not in d

    def test_to_dict_is_json_serializable(self):
        event = DispatchSkippedEvent(
            agent="agent-001",
            cycle_type="cycle",
            reason="budget_tripped",
        )
        json.dumps(event.to_dict())


class TestEmitDispatchSkipped:
    def test_writes_to_agent_log(self, aios_config):
        event = DispatchSkippedEvent(
            agent="agent-001-maker",
            cycle_type="cycle",
            reason="cooldown_active",
        )
        emit_dispatch_skipped(event, config=aios_config)

        log_dir = aios_config.logs_dir / "agent-001-maker"
        log_files = list(log_dir.glob("*.jsonl"))
        assert len(log_files) == 1

        entries = [json.loads(line) for line in log_files[0].read_text().splitlines()]
        assert len(entries) == 1
        assert entries[0]["action"] == "dispatch_skipped"
        assert entries[0]["level"] == "info"
        assert entries[0]["refs"]["event"] == "dispatch_skipped"
        assert entries[0]["refs"]["reason"] == "cooldown_active"


# --- dispatch-status ---


class TestGetDispatchStatus:
    def test_returns_rows_for_each_agent_and_type(self, tmp_path):
        root = tmp_path / "company"
        root.mkdir()
        (root / "agents" / "registry").mkdir(parents=True)
        (root / "agents" / "logs").mkdir(parents=True)
        (root / "operations").mkdir(parents=True)

        # Create a registry file for one agent
        reg_file = root / "agents" / "registry" / "agent-001-maker.md"
        reg_file.write_text(
            "---\n"
            "id: agent-001-maker\n"
            "name: The Maker\n"
            "role: Software Engineer\n"
            "model: claude-opus-4-6\n"
            "tools: [Read, Write]\n"
            "---\n\nTest agent.\n"
        )

        cfg = Config(
            company_root=root,
            schedule_cycles_enabled=True,
            schedule_cycles_interval_minutes=15,
            schedule_standing_orders_enabled=True,
            schedule_standing_orders_interval_minutes=60,
            schedule_drives_enabled=True,
            schedule_drives_weekday_times=["17:00"],
            schedule_dreams_enabled=True,
            schedule_dreams_time="02:00",
        )

        rows = get_dispatch_status(config=cfg)

        # Should have 4 rows per agent (cycle, standing_orders, drives, dreams)
        assert len(rows) == 4
        types = [r["cycle_type"] for r in rows]
        assert "cycle" in types
        assert "standing_orders" in types
        assert "drives" in types
        assert "dreams" in types

        # First run — all should say "never" for last_dispatch
        for row in rows:
            if row["cycle_type"] in ("cycle", "standing_orders"):
                assert row["last_dispatch"] == "never"
                assert row["next_eligible"] == "now"

    def test_cadence_file_updates_last_dispatch(self, tmp_path):
        root = tmp_path / "company"
        root.mkdir()
        (root / "agents" / "registry").mkdir(parents=True)
        (root / "agents" / "logs" / "agent-001-maker").mkdir(parents=True)
        (root / "operations").mkdir(parents=True)

        reg_file = root / "agents" / "registry" / "agent-001-maker.md"
        reg_file.write_text(
            "---\n"
            "id: agent-001-maker\n"
            "name: The Maker\n"
            "role: Software Engineer\n"
            "model: claude-opus-4-6\n"
            "tools: [Read]\n"
            "---\n\nTest.\n"
        )

        # Write a cadence file
        cadence_file = root / "agents" / "logs" / "agent-001-maker" / ".cadence-scheduler-cycle"
        last_time = datetime.now().astimezone()
        cadence_file.write_text(last_time.isoformat())

        cfg = Config(
            company_root=root,
            schedule_cycles_enabled=True,
            schedule_cycles_interval_minutes=15,
        )

        rows = get_dispatch_status(config=cfg)
        cycle_rows = [r for r in rows if r["cycle_type"] == "cycle"]
        assert len(cycle_rows) == 1
        assert cycle_rows[0]["last_dispatch"] != "never"


class TestFormatDispatchStatus:
    def test_no_agents_message(self, tmp_path):
        root = tmp_path / "company"
        root.mkdir()
        (root / "agents" / "registry").mkdir(parents=True)
        (root / "agents" / "logs").mkdir(parents=True)
        (root / "operations").mkdir(parents=True)

        cfg = Config(company_root=root)
        output = format_dispatch_status(config=cfg)
        assert "No agents registered" in output

    def test_includes_header(self, tmp_path):
        root = tmp_path / "company"
        root.mkdir()
        (root / "agents" / "registry").mkdir(parents=True)
        (root / "agents" / "logs").mkdir(parents=True)
        (root / "operations").mkdir(parents=True)

        reg_file = root / "agents" / "registry" / "agent-001-maker.md"
        reg_file.write_text(
            "---\n"
            "id: agent-001-maker\n"
            "name: The Maker\n"
            "role: Software Engineer\n"
            "model: claude-opus-4-6\n"
            "tools: [Read]\n"
            "---\n\nTest.\n"
        )

        cfg = Config(company_root=root)
        output = format_dispatch_status(config=cfg)
        assert "Agent" in output
        assert "Type" in output
        assert "agent-001-maker" in output


# --- Integration: dispatch_skipped in scheduler ---


class TestSchedulerDispatchSkipped:
    """Verify dispatch_skipped events are emitted when the scheduler skips agents."""

    @pytest.mark.asyncio
    async def test_outside_hours_emits_dispatch_skipped(self, tmp_path):
        """Cycles skipped due to operating hours should emit dispatch_skipped events."""
        from agent_os.scheduler import tick

        root = tmp_path / "company"
        root.mkdir()
        (root / "agents" / "registry").mkdir(parents=True)
        (root / "agents" / "logs").mkdir(parents=True)
        (root / "finance" / "costs").mkdir(parents=True)
        (root / "operations").mkdir(parents=True)

        cfg = Config(
            company_root=root,
            schedule_enabled=True,
            schedule_operating_hours="07:00-23:00",
            schedule_cycles_enabled=True,
            schedule_cycles_interval_minutes=15,
            schedule_standing_orders_enabled=True,
            schedule_standing_orders_interval_minutes=60,
            schedule_drives_enabled=True,
            schedule_drives_weekday_times=["17:00"],
            schedule_dreams_enabled=False,
            schedule_archive_enabled=False,
            schedule_manifest_enabled=False,
            schedule_watchdog_enabled=False,
            schedule_digest_enabled=False,
        )

        from dataclasses import dataclass

        @dataclass
        class _FakeAgent:
            agent_id: str

        @dataclass
        class _FakeBudget:
            daily_spent: float = 0.0
            daily_cap: float = 100.0
            daily_remaining: float = 100.0
            daily_pct: float = 0.0
            circuit_breaker_tripped: bool = False

        fake_now = datetime(2026, 4, 12, 3, 0, tzinfo=cfg.tz)  # 03:00 — outside hours

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=False),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001-maker")]),
        ):
            result = await tick(config=cfg)

        # Should have skipped cycles
        assert "cycles: outside operating hours" in result.skipped

        # Check that dispatch_skipped events were written to agent log
        log_dir = cfg.logs_dir / "agent-001-maker"
        assert log_dir.exists()
        log_files = list(log_dir.glob("*.jsonl"))
        assert len(log_files) >= 1

        entries = []
        for lf in log_files:
            for line in lf.read_text().splitlines():
                entry = json.loads(line)
                if entry.get("action") == "dispatch_skipped":
                    entries.append(entry)

        # Should have dispatch_skipped for cycles, standing_orders, and drives
        skipped_types = {e["refs"]["cycle_type"] for e in entries}
        assert "cycle" in skipped_types
        assert "standing_orders" in skipped_types
        assert "drives" in skipped_types

        # All should have reason "outside_operating_hours"
        for entry in entries:
            assert entry["refs"]["reason"] == "outside_operating_hours"
