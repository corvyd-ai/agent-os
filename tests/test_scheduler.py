"""Tests for agent_os.scheduler — tick dispatcher and schedule logic."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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

    def test_no_budget_snapshot_in_state_file(self, aios_config):
        """State file must NOT contain a budget snapshot — budget is always
        derived live from the cost JSONL (single source of truth).
        """
        result = TickResult(
            timestamp="2026-03-08T17:00:00Z",
            enabled=True,
            budget_tripped=False,
            outside_hours=False,
        )
        write_scheduler_state(result, config=aios_config)

        state = json.loads(aios_config.scheduler_state_file.read_text())
        assert "budget" not in state, "scheduler-state.json must not contain a budget snapshot"


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


# --- Helpers for multi-agent dispatch tests ---

FIVE_AGENTS = [
    _FakeAgent("agent-000-steward"),
    _FakeAgent("agent-001-maker"),
    _FakeAgent("agent-003-operator"),
    _FakeAgent("agent-005-grower"),
    _FakeAgent("agent-006-strategist"),
]

FIVE_AGENT_IDS = [a.agent_id for a in FIVE_AGENTS]


def _make_minimal_cfg(tmp_path, **overrides):
    """Build a Config with all schedule types disabled unless overridden."""
    root = tmp_path / "company"
    root.mkdir(parents=True, exist_ok=True)
    (root / "agents" / "registry").mkdir(parents=True, exist_ok=True)
    (root / "agents" / "logs").mkdir(parents=True, exist_ok=True)
    (root / "finance" / "costs").mkdir(parents=True, exist_ok=True)
    (root / "operations").mkdir(parents=True, exist_ok=True)
    defaults = dict(
        company_root=root,
        schedule_enabled=True,
        schedule_operating_hours="",
        schedule_cycles_enabled=False,
        schedule_standing_orders_enabled=False,
        schedule_drives_enabled=False,
        schedule_dreams_enabled=False,
        schedule_archive_enabled=False,
        schedule_manifest_enabled=False,
        schedule_watchdog_enabled=False,
        schedule_digest_enabled=False,
    )
    defaults.update(overrides)
    return Config(**defaults)


class TestDreamStaggerMultiAgent:
    """Regression: dream cycles must dispatch to ALL agents, not just index 0.

    The original bug: an outer _is_time_match(dream_time) gate only passed
    when the clock read exactly the base dream time (e.g. 02:00). Staggered
    agents at 02:10, 02:20, etc. were never dispatched because the outer
    gate failed at those minutes.
    """

    @pytest.mark.asyncio
    async def test_each_agent_dispatched_at_staggered_minute(self, tmp_path):
        """5 agents with 10-min stagger: agent N fires at 02:00 + N*10."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_dreams_enabled=True,
            schedule_dreams_time="02:00",
            schedule_dreams_stagger_minutes=10,
        )

        dispatched_agents = {}

        for minute in range(0, 50, 10):  # 02:00, 02:10, 02:20, 02:30, 02:40
            fake_now = datetime(2026, 4, 14, 2, minute, tzinfo=cfg.tz)

            with (
                patch("agent_os.scheduler._now", return_value=fake_now),
                patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
                patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
                patch("agent_os.runner.run_dream_cycle", new_callable=AsyncMock),
            ):
                result = await tick(config=cfg)

            for d in result.dispatched:
                if d.type == "dreams":
                    dispatched_agents[d.agent] = minute

        # All 5 agents dispatched at correct minutes
        assert len(dispatched_agents) == 5, f"Only {len(dispatched_agents)}/5 agents dispatched: {dispatched_agents}"
        assert dispatched_agents["agent-000-steward"] == 0
        assert dispatched_agents["agent-001-maker"] == 10
        assert dispatched_agents["agent-003-operator"] == 20
        assert dispatched_agents["agent-005-grower"] == 30
        assert dispatched_agents["agent-006-strategist"] == 40

    @pytest.mark.asyncio
    async def test_only_one_agent_per_stagger_slot(self, tmp_path):
        """At 02:10, exactly one agent (index 1) should dispatch, not others."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_dreams_enabled=True,
            schedule_dreams_time="02:00",
            schedule_dreams_stagger_minutes=10,
        )

        fake_now = datetime(2026, 4, 14, 2, 10, tzinfo=cfg.tz)  # 02:10

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
            patch("agent_os.runner.run_dream_cycle", new_callable=AsyncMock) as mock_dream,
        ):
            result = await tick(config=cfg)

        dream_dispatches = [d for d in result.dispatched if d.type == "dreams"]
        assert len(dream_dispatches) == 1
        assert dream_dispatches[0].agent == "agent-001-maker"
        mock_dream.assert_called_once_with("agent-001-maker", config=cfg)

    @pytest.mark.asyncio
    async def test_no_stagger_dispatches_all_at_same_minute(self, tmp_path):
        """With stagger_minutes=0, all agents dispatch at the base dream time."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_dreams_enabled=True,
            schedule_dreams_time="02:00",
            schedule_dreams_stagger_minutes=0,
        )

        fake_now = datetime(2026, 4, 14, 2, 0, tzinfo=cfg.tz)

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
            patch("agent_os.runner.run_dream_cycle", new_callable=AsyncMock) as mock_dream,
        ):
            result = await tick(config=cfg)

        dream_dispatches = [d for d in result.dispatched if d.type == "dreams"]
        assert len(dream_dispatches) == 5
        dispatched_ids = {d.agent for d in dream_dispatches}
        assert dispatched_ids == set(FIVE_AGENT_IDS)
        assert mock_dream.call_count == 5

    @pytest.mark.asyncio
    async def test_stagger_wraps_past_hour_boundary(self, tmp_path):
        """Stagger from 02:55 with 10-min offsets should wrap into 03:xx."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_dreams_enabled=True,
            schedule_dreams_time="02:55",
            schedule_dreams_stagger_minutes=10,
        )

        # Agent 0: 02:55, Agent 1: 03:05, Agent 2: 03:15
        expected = [
            (2, 55, "agent-000-steward"),
            (3, 5, "agent-001-maker"),
            (3, 15, "agent-003-operator"),
            (3, 25, "agent-005-grower"),
            (3, 35, "agent-006-strategist"),
        ]

        dispatched_agents = {}
        for hour, minute, _agent_id in expected:
            fake_now = datetime(2026, 4, 14, hour, minute, tzinfo=cfg.tz)

            with (
                patch("agent_os.scheduler._now", return_value=fake_now),
                patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
                patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
                patch("agent_os.runner.run_dream_cycle", new_callable=AsyncMock),
            ):
                result = await tick(config=cfg)

            for d in result.dispatched:
                if d.type == "dreams":
                    dispatched_agents[d.agent] = (hour, minute)

        assert len(dispatched_agents) == 5, f"Only {len(dispatched_agents)}/5 agents dispatched"
        for hour, minute, agent_id in expected:
            assert dispatched_agents[agent_id] == (hour, minute), (
                f"{agent_id} expected at {hour:02d}:{minute:02d}, got {dispatched_agents.get(agent_id)}"
            )

    @pytest.mark.asyncio
    async def test_non_dream_minutes_dispatch_nothing(self, tmp_path):
        """At 02:05 (between stagger slots), no agent should be dispatched."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_dreams_enabled=True,
            schedule_dreams_time="02:00",
            schedule_dreams_stagger_minutes=10,
        )

        fake_now = datetime(2026, 4, 14, 2, 5, tzinfo=cfg.tz)  # 02:05 — not a slot

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
            patch("agent_os.runner.run_dream_cycle", new_callable=AsyncMock) as mock_dream,
        ):
            result = await tick(config=cfg)

        dream_dispatches = [d for d in result.dispatched if d.type == "dreams"]
        assert len(dream_dispatches) == 0
        mock_dream.assert_not_called()


class TestStandingOrdersMultiAgent:
    """Standing orders must dispatch to all agents across multiple ticks.

    With the one-per-tick stagger, each tick dispatches at most one agent.
    The cadence marks naturally spread agents across consecutive minutes.
    """

    @pytest.mark.asyncio
    async def test_all_agents_receive_standing_orders_across_ticks(self, tmp_path):
        """All 5 agents get standing orders over 5 consecutive ticks."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_standing_orders_enabled=True,
            schedule_standing_orders_interval_minutes=60,
        )

        dispatched_ids: list[str] = []
        fake_now = datetime(2026, 4, 14, 12, 0, tzinfo=cfg.tz)

        for minute in range(5):
            tick_time = fake_now.replace(minute=minute)
            with (
                patch("agent_os.scheduler._now", return_value=tick_time),
                patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
                patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
                patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
                patch("agent_os.runner.run_standing_orders", new_callable=AsyncMock),
            ):
                result = await tick(config=cfg)
            for d in result.dispatched:
                if d.type == "standing_orders":
                    dispatched_ids.append(d.agent)

        assert set(dispatched_ids) == set(FIVE_AGENT_IDS), f"Expected all 5 agents, got {dispatched_ids}"

    @pytest.mark.asyncio
    async def test_only_one_standing_order_per_tick(self, tmp_path):
        """A single tick dispatches at most one standing-order agent."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_standing_orders_enabled=True,
            schedule_standing_orders_interval_minutes=60,
        )

        fake_now = datetime(2026, 4, 14, 12, 0, tzinfo=cfg.tz)

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
            patch("agent_os.runner.run_standing_orders", new_callable=AsyncMock) as mock_so,
        ):
            result = await tick(config=cfg)

        so_dispatches = [d for d in result.dispatched if d.type == "standing_orders"]
        assert len(so_dispatches) == 1, f"Expected 1 dispatch per tick, got {len(so_dispatches)}"
        assert mock_so.call_count == 1


class TestCycleOnePerTick:
    """Cycles must dispatch at most one agent per tick.

    The original design serialized N ``run_cycle`` awaits in a single tick
    window. With 5 agents doing LLM-backed work, the systemd oneshot
    timeout killed the tick before later agents ran.

    Fix: dispatch the first due agent and break. Cadence timestamps
    self-stagger — after the first round each agent's mark is offset by
    ~1 minute, so they never bunch up again.
    """

    @pytest.mark.asyncio
    async def test_only_one_cycle_per_tick(self, tmp_path):
        """A single tick dispatches at most one cycle agent."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_cycles_enabled=True,
            schedule_cycles_interval_minutes=15,
        )

        fake_now = datetime(2026, 4, 14, 12, 0, tzinfo=cfg.tz)

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
            patch("agent_os.runner.run_cycle", new_callable=AsyncMock) as mock_cycle,
        ):
            result = await tick(config=cfg)

        cycle_dispatches = [d for d in result.dispatched if d.type == "cycle"]
        assert len(cycle_dispatches) == 1, f"Expected 1 dispatch per tick, got {len(cycle_dispatches)}"
        assert cycle_dispatches[0].agent == "agent-000-steward"  # First in list
        assert mock_cycle.call_count == 1

    @pytest.mark.asyncio
    async def test_all_agents_dispatched_across_ticks(self, tmp_path):
        """All 5 agents get cycles over 5 consecutive ticks."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_cycles_enabled=True,
            schedule_cycles_interval_minutes=15,
        )

        dispatched_agents: list[str] = []

        for minute in range(5):
            fake_now = datetime(2026, 4, 14, 12, minute, tzinfo=cfg.tz)
            with (
                patch("agent_os.scheduler._now", return_value=fake_now),
                patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
                patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
                patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
                patch("agent_os.runner.run_cycle", new_callable=AsyncMock),
            ):
                result = await tick(config=cfg)
            for d in result.dispatched:
                if d.type == "cycle":
                    dispatched_agents.append(d.agent)

        assert len(dispatched_agents) == 5, f"Expected 5 dispatches over 5 ticks, got {len(dispatched_agents)}"
        assert set(dispatched_agents) == set(FIVE_AGENT_IDS)

    @pytest.mark.asyncio
    async def test_cycle_error_marks_cadence(self, tmp_path):
        """A failed cycle marks cadence so the failing agent doesn't block others."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_cycles_enabled=True,
            schedule_cycles_interval_minutes=15,
        )

        fake_now = datetime(2026, 4, 14, 12, 0, tzinfo=cfg.tz)

        # First tick: agent-000 fails
        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
            patch(
                "agent_os.runner.run_cycle",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM down"),
            ),
        ):
            result = await tick(config=cfg)

        cycle_dispatches = [d for d in result.dispatched if d.type == "cycle"]
        assert len(cycle_dispatches) == 1
        assert "error" in cycle_dispatches[0].result

        # Second tick at same time: agent-000 is NOT retried (cadence marked),
        # agent-001 gets dispatched instead.
        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
            patch("agent_os.runner.run_cycle", new_callable=AsyncMock) as mock_cycle,
        ):
            result = await tick(config=cfg)

        cycle_dispatches = [d for d in result.dispatched if d.type == "cycle"]
        assert len(cycle_dispatches) == 1
        assert cycle_dispatches[0].agent == "agent-001-maker"
        mock_cycle.assert_called_once_with("agent-001-maker", config=cfg)

    @pytest.mark.asyncio
    async def test_locked_agent_skipped_next_dispatched(self, tmp_path):
        """A locked agent is skipped; the next due agent dispatches in the same tick."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_cycles_enabled=True,
            schedule_cycles_interval_minutes=15,
        )

        fake_now = datetime(2026, 4, 14, 12, 0, tzinfo=cfg.tz)

        # Lock returns None for steward (index 0), real lock for others
        original_acquire = __import__("agent_os.scheduler", fromlist=["acquire_lock"]).acquire_lock

        def selective_lock(agent_id, mode, *, config=None):
            if agent_id == "agent-000-steward":
                return None
            return original_acquire(agent_id, mode, config=config)

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
            patch("agent_os.scheduler.acquire_lock", side_effect=selective_lock),
            patch("agent_os.runner.run_cycle", new_callable=AsyncMock) as mock_cycle,
        ):
            result = await tick(config=cfg)

        # Steward was locked (skipped), maker dispatched
        assert "cycle:agent-000-steward locked" in result.skipped
        cycle_dispatches = [d for d in result.dispatched if d.type == "cycle"]
        assert len(cycle_dispatches) == 1
        assert cycle_dispatches[0].agent == "agent-001-maker"
        mock_cycle.assert_called_once()


class TestDrivesMultiAgent:
    """Drive consultations must dispatch to all agents across staggered ticks.

    Drives now follow the same per-agent stagger pattern as dreams. With
    ``stagger_minutes=0`` they all fire at the base drive time (legacy
    behavior); with ``stagger_minutes>0`` each agent fires at
    ``base + idx * stagger`` so a single tick can never serialize all N
    agents and silently drop the late ones.
    """

    @pytest.mark.asyncio
    async def test_all_agents_receive_drive_consultation_with_zero_stagger(self, tmp_path):
        """With stagger=0, all agents should dispatch at the base drive time."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_drives_enabled=True,
            schedule_drives_weekday_times=["17:00"],
            schedule_drives_weekend_times=["13:00"],
            schedule_drives_stagger_minutes=0,
        )

        # Tuesday at 17:00
        fake_now = datetime(2026, 4, 14, 17, 0, tzinfo=cfg.tz)

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
            patch("agent_os.scheduler._is_weekend", return_value=False),
            patch("agent_os.runner.run_drive_consultation", new_callable=AsyncMock) as mock_drives,
        ):
            result = await tick(config=cfg)

        drive_dispatches = [d for d in result.dispatched if d.type == "drives"]
        assert len(drive_dispatches) == 5, f"Only {len(drive_dispatches)}/5 agents got drive consultation"
        dispatched_ids = {d.agent for d in drive_dispatches}
        assert dispatched_ids == set(FIVE_AGENT_IDS)
        assert mock_drives.call_count == 5


class TestDrivesStaggerMultiAgent:
    """Regression: drive consultations must reach ALL agents, not just index 0.

    Original bug (pre-fix): ``_is_time_match`` was a 1-minute window, dispatch
    was a sequential await loop, and the cron tick only fires once per minute.
    Whichever agents' LLM consultations finished fast enough during the ~10-15
    min the originating tick stayed alive got a drive; the rest were silently
    skipped until the next scheduled drive time. Coverage decayed by agent
    index — Strategist (index 4) hit 12.5% over 8 windows.

    Fix: per-agent stagger, mirroring dreams. Each agent fires at
    ``base_time + idx * stagger_minutes`` and each tick handles at most one
    agent per scheduled drive time, so the bug class disappears structurally.
    """

    @pytest.mark.asyncio
    async def test_each_agent_dispatched_at_staggered_minute(self, tmp_path):
        """5 agents with 10-min stagger: agent N fires at 17:00 + N*10."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_drives_enabled=True,
            schedule_drives_weekday_times=["17:00"],
            schedule_drives_weekend_times=["13:00"],
            schedule_drives_stagger_minutes=10,
        )

        dispatched_agents: dict[str, int] = {}

        # Tuesday Apr 14 2026 — weekday
        for minute in range(0, 50, 10):  # 17:00, 17:10, 17:20, 17:30, 17:40
            fake_now = datetime(2026, 4, 14, 17, minute, tzinfo=cfg.tz)

            with (
                patch("agent_os.scheduler._now", return_value=fake_now),
                patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
                patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
                patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
                patch("agent_os.scheduler._is_weekend", return_value=False),
                patch("agent_os.runner.run_drive_consultation", new_callable=AsyncMock),
            ):
                result = await tick(config=cfg)

            for d in result.dispatched:
                if d.type == "drives":
                    dispatched_agents[d.agent] = minute

        assert len(dispatched_agents) == 5, f"Only {len(dispatched_agents)}/5 agents dispatched: {dispatched_agents}"
        assert dispatched_agents["agent-000-steward"] == 0
        assert dispatched_agents["agent-001-maker"] == 10
        assert dispatched_agents["agent-003-operator"] == 20
        assert dispatched_agents["agent-005-grower"] == 30
        assert dispatched_agents["agent-006-strategist"] == 40

    @pytest.mark.asyncio
    async def test_only_one_agent_per_stagger_slot(self, tmp_path):
        """At 17:10, exactly one agent (index 1) should dispatch, not others."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_drives_enabled=True,
            schedule_drives_weekday_times=["17:00"],
            schedule_drives_stagger_minutes=10,
        )

        fake_now = datetime(2026, 4, 14, 17, 10, tzinfo=cfg.tz)

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
            patch("agent_os.scheduler._is_weekend", return_value=False),
            patch("agent_os.runner.run_drive_consultation", new_callable=AsyncMock) as mock_drives,
        ):
            result = await tick(config=cfg)

        drive_dispatches = [d for d in result.dispatched if d.type == "drives"]
        assert len(drive_dispatches) == 1
        assert drive_dispatches[0].agent == "agent-001-maker"
        mock_drives.assert_called_once_with("agent-001-maker", config=cfg)

    @pytest.mark.asyncio
    async def test_non_drive_minutes_dispatch_nothing(self, tmp_path):
        """At 17:05 (between stagger slots), no agent should be dispatched."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_drives_enabled=True,
            schedule_drives_weekday_times=["17:00"],
            schedule_drives_stagger_minutes=10,
        )

        fake_now = datetime(2026, 4, 14, 17, 5, tzinfo=cfg.tz)

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
            patch("agent_os.scheduler._is_weekend", return_value=False),
            patch("agent_os.runner.run_drive_consultation", new_callable=AsyncMock) as mock_drives,
        ):
            result = await tick(config=cfg)

        drive_dispatches = [d for d in result.dispatched if d.type == "drives"]
        assert len(drive_dispatches) == 0
        mock_drives.assert_not_called()

    @pytest.mark.asyncio
    async def test_stagger_applies_per_drive_time(self, tmp_path):
        """Multiple drive times each get their own staggered fan-out."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_drives_enabled=True,
            schedule_drives_weekday_times=["09:00", "17:00"],
            schedule_drives_stagger_minutes=10,
        )

        # Agent 1 should fire at both 09:10 (idx 1 of 09:00 window) and
        # 17:10 (idx 1 of 17:00 window).
        hits = []
        for hour in (9, 17):
            fake_now = datetime(2026, 4, 14, hour, 10, tzinfo=cfg.tz)
            with (
                patch("agent_os.scheduler._now", return_value=fake_now),
                patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
                patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
                patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
                patch("agent_os.scheduler._is_weekend", return_value=False),
                patch("agent_os.runner.run_drive_consultation", new_callable=AsyncMock),
            ):
                result = await tick(config=cfg)
            for d in result.dispatched:
                if d.type == "drives":
                    hits.append((hour, d.agent))

        assert hits == [(9, "agent-001-maker"), (17, "agent-001-maker")]

    @pytest.mark.asyncio
    async def test_stagger_wraps_past_hour_boundary(self, tmp_path):
        """Stagger from 17:55 with 10-min offsets should wrap into 18:xx."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_drives_enabled=True,
            schedule_drives_weekday_times=["17:55"],
            schedule_drives_stagger_minutes=10,
        )

        expected = [
            (17, 55, "agent-000-steward"),
            (18, 5, "agent-001-maker"),
            (18, 15, "agent-003-operator"),
            (18, 25, "agent-005-grower"),
            (18, 35, "agent-006-strategist"),
        ]

        dispatched_agents: dict[str, tuple[int, int]] = {}
        for hour, minute, _agent_id in expected:
            fake_now = datetime(2026, 4, 14, hour, minute, tzinfo=cfg.tz)
            with (
                patch("agent_os.scheduler._now", return_value=fake_now),
                patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
                patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
                patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
                patch("agent_os.scheduler._is_weekend", return_value=False),
                patch("agent_os.runner.run_drive_consultation", new_callable=AsyncMock),
            ):
                result = await tick(config=cfg)
            for d in result.dispatched:
                if d.type == "drives":
                    dispatched_agents[d.agent] = (hour, minute)

        assert len(dispatched_agents) == 5
        for hour, minute, agent_id in expected:
            assert dispatched_agents[agent_id] == (hour, minute)


class TestWeeklySimulation:
    """Simulate a week of scheduler ticks for 5 agents.

    Regression test: asserts that each agent receives at least one dream
    cycle, standing-order dispatch, and drive consultation per day across
    a full simulated week. This is the acceptance test that would have
    caught the original stagger bug.
    """

    @pytest.mark.asyncio
    async def test_full_week_coverage(self, tmp_path):
        """7 days of ticks: every agent gets dreams, standing orders, and drives."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_dreams_enabled=True,
            schedule_dreams_time="02:00",
            schedule_dreams_stagger_minutes=10,
            schedule_standing_orders_enabled=True,
            schedule_standing_orders_interval_minutes=60,
            schedule_drives_enabled=True,
            schedule_drives_weekday_times=["17:00"],
            schedule_drives_weekend_times=["13:00"],
            schedule_drives_stagger_minutes=10,
        )

        # Counters per agent per type
        dream_count = {a: 0 for a in FIVE_AGENT_IDS}
        so_count = {a: 0 for a in FIVE_AGENT_IDS}
        drive_count = {a: 0 for a in FIVE_AGENT_IDS}

        # Simulate 7 days: Mon Apr 13 through Sun Apr 19, 2026
        base_date = datetime(2026, 4, 13, 0, 0, tzinfo=cfg.tz)  # Monday

        for day_offset in range(7):
            day_start = base_date + timedelta(days=day_offset)
            is_weekend = day_start.weekday() >= 5

            # --- Dream window ---
            for minute_offset in range(0, 50, 10):
                tick_time = day_start.replace(hour=2, minute=minute_offset)
                with (
                    patch("agent_os.scheduler._now", return_value=tick_time),
                    patch("agent_os.scheduler.is_within_operating_hours", return_value=False),
                    patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
                    patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
                    patch("agent_os.runner.run_dream_cycle", new_callable=AsyncMock),
                ):
                    result = await tick(config=cfg)
                for d in result.dispatched:
                    if d.type == "dreams":
                        dream_count[d.agent] += 1

            # --- Standing orders (one agent per tick, 5 ticks to cover all) ---
            for so_minute in range(5):
                tick_time = day_start.replace(hour=12, minute=so_minute)
                with (
                    patch("agent_os.scheduler._now", return_value=tick_time),
                    patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
                    patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
                    patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
                    patch("agent_os.runner.run_standing_orders", new_callable=AsyncMock),
                    patch("agent_os.scheduler._is_time_match", return_value=False),
                    patch("agent_os.scheduler._is_weekend", return_value=is_weekend),
                ):
                    result = await tick(config=cfg)
                for d in result.dispatched:
                    if d.type == "standing_orders":
                        so_count[d.agent] += 1

            # --- Drive consultation window (staggered, mirrors dream window) ---
            drive_hour = 13 if is_weekend else 17
            for minute_offset in range(0, 50, 10):  # base + idx*10 for 5 agents
                tick_time = day_start.replace(hour=drive_hour, minute=minute_offset)
                with (
                    patch("agent_os.scheduler._now", return_value=tick_time),
                    patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
                    patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
                    patch("agent_os.scheduler.list_agents", return_value=FIVE_AGENTS),
                    patch("agent_os.runner.run_drive_consultation", new_callable=AsyncMock),
                    patch("agent_os.scheduler._is_weekend", return_value=is_weekend),
                ):
                    result = await tick(config=cfg)
                for d in result.dispatched:
                    if d.type == "drives":
                        drive_count[d.agent] += 1

        # --- Assertions: every agent gets every type every day ---
        for agent_id in FIVE_AGENT_IDS:
            assert dream_count[agent_id] >= 7, f"{agent_id}: expected ≥7 dream cycles, got {dream_count[agent_id]}"
            assert so_count[agent_id] >= 7, (
                f"{agent_id}: expected ≥7 standing-order dispatches, got {so_count[agent_id]}"
            )
            assert drive_count[agent_id] >= 7, (
                f"{agent_id}: expected ≥7 drive consultations, got {drive_count[agent_id]}"
            )

        # Exact totals: 5 agents x 7 days = 35
        assert sum(dream_count.values()) == 35
        assert sum(so_count.values()) == 35
        assert sum(drive_count.values()) == 35


class TestDreamDispatchErrorEvents:
    """Dream cycle errors must produce structured error events."""

    @pytest.mark.asyncio
    async def test_dream_error_produces_dispatch_record(self, tmp_path):
        """When a dream cycle raises, the TickResult contains an error record."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_dreams_enabled=True,
            schedule_dreams_time="02:00",
            schedule_dreams_stagger_minutes=0,
        )

        fake_now = datetime(2026, 4, 14, 2, 0, tzinfo=cfg.tz)

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001")]),
            patch(
                "agent_os.runner.run_dream_cycle",
                new_callable=AsyncMock,
                side_effect=RuntimeError("SDK crash"),
            ),
        ):
            result = await tick(config=cfg)

        dream_dispatches = [d for d in result.dispatched if d.type == "dreams"]
        assert len(dream_dispatches) == 1
        assert "error" in dream_dispatches[0].result
        assert "SDK crash" in dream_dispatches[0].result


def _read_dispatch_outcomes(cfg: Config, agent_id: str) -> list[dict]:
    """Read dispatch_outcome lines from an agent's per-day log."""
    log_dir = cfg.logs_dir / agent_id
    if not log_dir.exists():
        return []
    outcomes = []
    for log_file in sorted(log_dir.glob("*.jsonl")):
        for line in log_file.read_text().splitlines():
            entry = json.loads(line)
            if entry.get("action") == "dispatch_outcome":
                outcomes.append(entry)
    return outcomes


class TestDispatchOutcomeJournal:
    """Every dispatch attempt must leave a primary-source record in the
    agent's own log (``logs/<agent-id>/<date>.jsonl``).

    This is the "cycle outcome events" observability layer: silent skips,
    locked dispatches, and errors all produce structured entries agents can
    read directly. Without this, missed dispatches were invisible by absence
    — the same gap that hid the drive-stagger bug for weeks.
    """

    @pytest.mark.asyncio
    async def test_drive_success_writes_outcome(self, tmp_path):
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_drives_enabled=True,
            schedule_drives_weekday_times=["17:00"],
            schedule_drives_stagger_minutes=0,
        )
        fake_now = datetime(2026, 4, 14, 17, 0, tzinfo=cfg.tz)

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001-maker")]),
            patch("agent_os.scheduler._is_weekend", return_value=False),
            patch("agent_os.runner.run_drive_consultation", new_callable=AsyncMock),
        ):
            await tick(config=cfg)

        outcomes = _read_dispatch_outcomes(cfg, "agent-001-maker")
        assert len(outcomes) == 1
        assert outcomes[0]["refs"]["type"] == "drives"
        assert outcomes[0]["refs"]["outcome"] == "success"
        assert outcomes[0]["level"] == "info"

    @pytest.mark.asyncio
    async def test_drive_error_writes_error_outcome(self, tmp_path):
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_drives_enabled=True,
            schedule_drives_weekday_times=["17:00"],
            schedule_drives_stagger_minutes=0,
        )
        fake_now = datetime(2026, 4, 14, 17, 0, tzinfo=cfg.tz)

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001-maker")]),
            patch("agent_os.scheduler._is_weekend", return_value=False),
            patch(
                "agent_os.runner.run_drive_consultation",
                new_callable=AsyncMock,
                side_effect=RuntimeError("LLM down"),
            ),
        ):
            await tick(config=cfg)

        outcomes = _read_dispatch_outcomes(cfg, "agent-001-maker")
        assert len(outcomes) == 1
        assert outcomes[0]["refs"]["outcome"] == "error"
        assert outcomes[0]["refs"]["error"] == "LLM down"
        assert outcomes[0]["level"] == "error"

    @pytest.mark.asyncio
    async def test_drive_locked_writes_locked_outcome(self, tmp_path):
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_drives_enabled=True,
            schedule_drives_weekday_times=["17:00"],
            schedule_drives_stagger_minutes=0,
        )
        fake_now = datetime(2026, 4, 14, 17, 0, tzinfo=cfg.tz)

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001-maker")]),
            patch("agent_os.scheduler._is_weekend", return_value=False),
            patch("agent_os.scheduler.acquire_lock", return_value=None),
            patch("agent_os.runner.run_drive_consultation", new_callable=AsyncMock) as mock_drives,
        ):
            await tick(config=cfg)

        outcomes = _read_dispatch_outcomes(cfg, "agent-001-maker")
        assert len(outcomes) == 1
        assert outcomes[0]["refs"]["outcome"] == "locked"
        assert outcomes[0]["refs"]["type"] == "drives"
        mock_drives.assert_not_called()

    @pytest.mark.asyncio
    async def test_dream_success_writes_outcome(self, tmp_path):
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_dreams_enabled=True,
            schedule_dreams_time="02:00",
            schedule_dreams_stagger_minutes=0,
        )
        fake_now = datetime(2026, 4, 14, 2, 0, tzinfo=cfg.tz)

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001-maker")]),
            patch("agent_os.runner.run_dream_cycle", new_callable=AsyncMock),
        ):
            await tick(config=cfg)

        outcomes = _read_dispatch_outcomes(cfg, "agent-001-maker")
        types = [o["refs"]["type"] for o in outcomes]
        outcome_kinds = [o["refs"]["outcome"] for o in outcomes]
        assert "dreams" in types
        assert all(k == "success" for k in outcome_kinds)

    @pytest.mark.asyncio
    async def test_cycle_success_writes_outcome(self, tmp_path):
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_cycles_enabled=True,
            schedule_cycles_interval_minutes=15,
        )
        fake_now = datetime(2026, 4, 14, 12, 0, tzinfo=cfg.tz)

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001-maker")]),
            patch("agent_os.runner.run_cycle", new_callable=AsyncMock),
        ):
            await tick(config=cfg)

        outcomes = _read_dispatch_outcomes(cfg, "agent-001-maker")
        cycle_outcomes = [o for o in outcomes if o["refs"]["type"] == "cycle"]
        assert len(cycle_outcomes) == 1
        assert cycle_outcomes[0]["refs"]["outcome"] == "success"
        assert "duration_sec" in cycle_outcomes[0]["refs"]

    @pytest.mark.asyncio
    async def test_outcome_includes_duration(self, tmp_path):
        """Successful dispatches record duration_sec for downstream analysis."""
        cfg = _make_minimal_cfg(
            tmp_path,
            schedule_drives_enabled=True,
            schedule_drives_weekday_times=["17:00"],
            schedule_drives_stagger_minutes=0,
        )
        fake_now = datetime(2026, 4, 14, 17, 0, tzinfo=cfg.tz)

        with (
            patch("agent_os.scheduler._now", return_value=fake_now),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001-maker")]),
            patch("agent_os.scheduler._is_weekend", return_value=False),
            patch("agent_os.runner.run_drive_consultation", new_callable=AsyncMock),
        ):
            await tick(config=cfg)

        outcomes = _read_dispatch_outcomes(cfg, "agent-001-maker")
        assert len(outcomes) == 1
        assert "duration_sec" in outcomes[0]["refs"]
        assert isinstance(outcomes[0]["refs"]["duration_sec"], (int, float))
