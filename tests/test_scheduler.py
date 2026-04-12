"""Tests for agent_os.scheduler — tick dispatcher and schedule logic."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from agent_os.config import Config
from agent_os.scheduler import (
    _OPERATING_HOURS_GATED,
    DispatchRecord,
    TickResult,
    _is_cadence_due,
    _mark_scheduler_cadence,
    is_within_operating_hours,
    tick,
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


class TestOperatingHoursGatedConstant:
    """Verify the taxonomy is correct."""

    def test_gated_types(self):
        assert "cycle" in _OPERATING_HOURS_GATED
        assert "standing_orders" in _OPERATING_HOURS_GATED
        assert "drives" in _OPERATING_HOURS_GATED

    def test_exempt_types(self):
        assert "dreams" not in _OPERATING_HOURS_GATED
        assert "archive" not in _OPERATING_HOURS_GATED
        assert "log_archive" not in _OPERATING_HOURS_GATED
        assert "manifest" not in _OPERATING_HOURS_GATED
        assert "watchdog" not in _OPERATING_HOURS_GATED


# --- Helpers for tick() integration tests ---


@dataclass
class _FakeAgent:
    agent_id: str


@dataclass
class _FakeArchiveResult:
    total_archived: int = 0


@dataclass
class _FakeLogArchiveResult:
    files_archived: int = 0
    files_deleted: int = 0


@dataclass
class _FakeWatchdogResult:
    agents_checked: int = 0
    alerts: list[str] = field(default_factory=list)


@dataclass
class _FakeBudget:
    daily_spent: float = 0.0
    daily_cap: float = 100.0
    daily_remaining: float = 100.0
    daily_pct: float = 0.0
    circuit_breaker_tripped: bool = False


def _make_cfg(tmp_path, *, operating_hours="07:00-23:00", dreams_time="02:00", archive_time="03:00"):
    """Build a Config with common test defaults."""
    root = tmp_path / "company"
    root.mkdir(parents=True, exist_ok=True)
    (root / "agents" / "registry").mkdir(parents=True, exist_ok=True)
    (root / "agents" / "logs").mkdir(parents=True, exist_ok=True)
    (root / "finance" / "costs").mkdir(parents=True, exist_ok=True)
    (root / "operations").mkdir(parents=True, exist_ok=True)
    return Config(
        company_root=root,
        schedule_enabled=True,
        schedule_operating_hours=operating_hours,
        schedule_cycles_enabled=True,
        schedule_cycles_interval_minutes=15,
        schedule_standing_orders_enabled=True,
        schedule_standing_orders_interval_minutes=60,
        schedule_drives_enabled=True,
        schedule_drives_weekday_times=["17:00"],
        schedule_drives_weekend_times=["13:00"],
        schedule_dreams_enabled=True,
        schedule_dreams_time=dreams_time,
        schedule_dreams_stagger_minutes=0,
        schedule_archive_enabled=True,
        schedule_archive_time=archive_time,
        schedule_manifest_enabled=True,
        schedule_manifest_interval_minutes=120,
        schedule_watchdog_enabled=True,
        schedule_watchdog_interval_minutes=15,
    )


class TestTickOperatingHoursGating:
    """Integration tests: tick() selectively gates by operating hours."""

    @pytest.mark.asyncio
    async def test_dreams_fire_outside_operating_hours(self, tmp_path):
        """Dreams at 02:00 should dispatch even with operating_hours=07:00-23:00."""
        cfg = _make_cfg(tmp_path, operating_hours="07:00-23:00", dreams_time="02:00")

        fake_now = datetime(2026, 4, 12, 2, 0, tzinfo=cfg.tz)  # 02:00 — outside hours

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=False),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001")]),
            patch("agent_os.runner.run_dream_cycle", new_callable=AsyncMock) as mock_dream,
            patch("agent_os.scheduler._is_time_match", side_effect=lambda t, **kw: t == "02:00"),
            patch("agent_os.maintenance.run_archive", return_value=_FakeArchiveResult()),
            patch("agent_os.maintenance.run_log_archive", return_value=_FakeLogArchiveResult()),
            patch("agent_os.maintenance.run_manifest"),
            patch("agent_os.maintenance.run_watchdog", return_value=_FakeWatchdogResult()),
        ):
            result = await tick(config=cfg)

        # Dreams should have dispatched
        dream_dispatches = [d for d in result.dispatched if d.type == "dreams"]
        assert len(dream_dispatches) == 1
        assert dream_dispatches[0].result == "done"
        mock_dream.assert_called_once()

        # Cycles, standing_orders, drives should be skipped
        assert "cycles: outside operating hours" in result.skipped
        assert "standing_orders: outside operating hours" in result.skipped
        assert "drives: outside operating hours" in result.skipped

    @pytest.mark.asyncio
    async def test_archive_fires_outside_operating_hours(self, tmp_path):
        """Archive at 03:00 should dispatch even with operating_hours=07:00-23:00."""
        cfg = _make_cfg(tmp_path, operating_hours="07:00-23:00", archive_time="03:00")

        fake_now = datetime(2026, 4, 12, 3, 0, tzinfo=cfg.tz)

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=False),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[]),
            patch("agent_os.scheduler._is_time_match", side_effect=lambda t, **kw: t == "03:00"),
            patch("agent_os.maintenance.run_archive", return_value=_FakeArchiveResult()) as mock_archive,
            patch("agent_os.maintenance.run_log_archive", return_value=_FakeLogArchiveResult()),
            patch("agent_os.maintenance.run_manifest"),
            patch("agent_os.maintenance.run_watchdog", return_value=_FakeWatchdogResult()),
        ):
            result = await tick(config=cfg)

        archive_dispatches = [d for d in result.dispatched if d.type == "archive"]
        assert len(archive_dispatches) == 1
        mock_archive.assert_called_once()

    @pytest.mark.asyncio
    async def test_gated_types_blocked_outside_hours(self, tmp_path):
        """Cycles, standing_orders, drives should NOT dispatch outside operating hours."""
        cfg = _make_cfg(tmp_path, operating_hours="07:00-23:00")

        fake_now = datetime(2026, 4, 12, 3, 0, tzinfo=cfg.tz)

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=False),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001")]),
            patch("agent_os.runner.run_cycle", new_callable=AsyncMock) as mock_cycle,
            patch("agent_os.runner.run_standing_orders", new_callable=AsyncMock) as mock_so,
            patch("agent_os.runner.run_drive_consultation", new_callable=AsyncMock) as mock_drives,
            patch("agent_os.scheduler._is_time_match", return_value=False),
            patch("agent_os.maintenance.run_archive", return_value=_FakeArchiveResult()),
            patch("agent_os.maintenance.run_log_archive", return_value=_FakeLogArchiveResult()),
            patch("agent_os.maintenance.run_manifest"),
            patch("agent_os.maintenance.run_watchdog", return_value=_FakeWatchdogResult()),
        ):
            result = await tick(config=cfg)

        # None of the gated runners should have been called
        mock_cycle.assert_not_called()
        mock_so.assert_not_called()
        mock_drives.assert_not_called()

        # All three should appear in skipped
        assert "cycles: outside operating hours" in result.skipped
        assert "standing_orders: outside operating hours" in result.skipped
        assert "drives: outside operating hours" in result.skipped
        assert result.outside_hours is True

    @pytest.mark.asyncio
    async def test_all_types_run_during_operating_hours(self, tmp_path):
        """During operating hours, nothing is skipped for hours reasons."""
        cfg = _make_cfg(tmp_path, operating_hours="07:00-23:00")

        fake_now = datetime(2026, 4, 12, 12, 0, tzinfo=cfg.tz)  # noon

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001")]),
            patch("agent_os.runner.run_cycle", new_callable=AsyncMock),
            patch("agent_os.runner.run_standing_orders", new_callable=AsyncMock),
            patch("agent_os.runner.run_drive_consultation", new_callable=AsyncMock),
            patch("agent_os.runner.run_dream_cycle", new_callable=AsyncMock),
            patch("agent_os.scheduler._is_time_match", return_value=False),
            patch("agent_os.maintenance.run_archive", return_value=_FakeArchiveResult()),
            patch("agent_os.maintenance.run_log_archive", return_value=_FakeLogArchiveResult()),
            patch("agent_os.maintenance.run_manifest"),
            patch("agent_os.maintenance.run_watchdog", return_value=_FakeWatchdogResult()),
        ):
            result = await tick(config=cfg)

        hours_skips = [s for s in result.skipped if "outside operating hours" in s]
        assert hours_skips == []
        assert result.outside_hours is False

    @pytest.mark.asyncio
    async def test_no_operating_hours_means_no_gating(self, tmp_path):
        """With operating_hours unset, no types are skipped for hours reasons."""
        cfg = _make_cfg(tmp_path, operating_hours="")

        fake_now = datetime(2026, 4, 12, 3, 0, tzinfo=cfg.tz)  # 03:00

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001")]),
            patch("agent_os.runner.run_cycle", new_callable=AsyncMock),
            patch("agent_os.runner.run_standing_orders", new_callable=AsyncMock),
            patch("agent_os.runner.run_drive_consultation", new_callable=AsyncMock),
            patch("agent_os.runner.run_dream_cycle", new_callable=AsyncMock),
            patch("agent_os.scheduler._is_time_match", return_value=False),
            patch("agent_os.maintenance.run_archive", return_value=_FakeArchiveResult()),
            patch("agent_os.maintenance.run_log_archive", return_value=_FakeLogArchiveResult()),
            patch("agent_os.maintenance.run_manifest"),
            patch("agent_os.maintenance.run_watchdog", return_value=_FakeWatchdogResult()),
        ):
            result = await tick(config=cfg)

        hours_skips = [s for s in result.skipped if "outside operating hours" in s]
        assert hours_skips == []
        assert result.outside_hours is False
