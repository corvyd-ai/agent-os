"""Tests for agent_os.scheduler — tick dispatcher and schedule logic."""

import json

from agent_os.config import Config
from agent_os.scheduler import (
    DispatchRecord,
    TickResult,
    _is_cadence_due,
    _mark_scheduler_cadence,
    is_within_operating_hours,
    write_scheduler_state,
)


class TestOperatingHours:
    def test_no_restriction(self, aios_config):
        cfg = Config(company_root=aios_config.company_root, schedule_operating_hours="")
        assert is_within_operating_hours(config=cfg) is True

    def test_malformed_hours(self, aios_config):
        cfg = Config(company_root=aios_config.company_root, schedule_operating_hours="invalid")
        assert is_within_operating_hours(config=cfg) is True


class TestCadence:
    def test_first_run_is_due(self, aios_config):
        assert _is_cadence_due("agent-001", "test-cadence", 15, config=aios_config) is True

    def test_not_due_after_mark(self, aios_config):
        _mark_scheduler_cadence("agent-001", "test-cadence", config=aios_config)
        assert _is_cadence_due("agent-001", "test-cadence", 15, config=aios_config) is False

    def test_corrupt_cadence_file_is_due(self, aios_config):
        cadence_file = aios_config.logs_dir / "agent-001" / ".cadence-test-cadence"
        cadence_file.parent.mkdir(parents=True, exist_ok=True)
        cadence_file.write_text("not-a-date")
        assert _is_cadence_due("agent-001", "test-cadence", 15, config=aios_config) is True


class TestWriteSchedulerState:
    def test_writes_state_file(self, aios_config):
        result = TickResult(
            timestamp="2026-03-08T17:00:00Z",
            enabled=True,
            budget_tripped=False,
            outside_hours=False,
            dispatched=[DispatchRecord(type="cycle", agent="agent-001", at="2026-03-08T17:00:00Z", result="done")],
            skipped=[],
        )
        write_scheduler_state(result, config=aios_config)

        state_file = aios_config.scheduler_state_file
        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert state["last_tick"] == "2026-03-08T17:00:00Z"
        assert state["enabled"] is True
        assert len(state["dispatched"]) == 1
        assert state["dispatched"][0]["type"] == "cycle"

    def test_skipped_reasons(self, aios_config):
        result = TickResult(
            timestamp="2026-03-08T17:00:00Z",
            enabled=False,
            budget_tripped=False,
            outside_hours=False,
            skipped=["scheduler disabled"],
        )
        write_scheduler_state(result, config=aios_config)

        state = json.loads(aios_config.scheduler_state_file.read_text())
        assert "scheduler disabled" in state["skipped"]
