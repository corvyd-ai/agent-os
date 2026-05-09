"""Tests for observe-cycle: new cycle type for reality grounding.

Per decision-2026-0509-001, observe-cycles complement existing cycle types
(drive, dream, task) by grounding agents in verified reality through
structured observation artifacts.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from agent_os.config import Config
from agent_os.runner import _DEFAULT_OBSERVATION_DOMAINS, _get_observation_domain
from agent_os.scheduler import tick

# --- Helpers ---


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


@dataclass
class _FakeWatchdogResult:
    agents_checked: int = 0
    alerts: list[str] = field(default_factory=list)


def _make_observe_cfg(tmp_path, **overrides):
    """Build a Config with only observe enabled."""
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
        schedule_observe_enabled=True,
        schedule_observe_interval_minutes=360,
        schedule_observe_stagger_minutes=5,
        schedule_archive_enabled=False,
        schedule_manifest_enabled=False,
        schedule_watchdog_enabled=False,
        schedule_digest_enabled=False,
    )
    defaults.update(overrides)
    return Config(**defaults)


def _read_dispatch_outcomes(cfg: Config, agent_id: str) -> list[dict]:
    """Read dispatch_outcome records from the agent's JSONL log."""
    log_dir = cfg.logs_dir / agent_id
    outcomes = []
    if not log_dir.exists():
        return outcomes
    for log_file in sorted(log_dir.glob("*.jsonl")):
        for line in log_file.read_text().splitlines():
            entry = json.loads(line)
            if entry.get("action") == "dispatch_outcome":
                outcomes.append(entry)
    return outcomes


# --- Observation domain tests ---


class TestObservationDomains:
    """Per-agent observation domains per decision-2026-0509-001."""

    def test_default_domains_exist_for_known_agents(self):
        """All five Corvyd agents have built-in observation domains."""
        known = [
            "agent-000-steward",
            "agent-001-maker",
            "agent-003-operator",
            "agent-005-grower",
            "agent-006-strategist",
        ]
        for agent_id in known:
            assert agent_id in _DEFAULT_OBSERVATION_DOMAINS
            assert len(_DEFAULT_OBSERVATION_DOMAINS[agent_id]) > 20  # non-trivial

    def test_config_override_takes_precedence(self, aios_config):
        """Config-specified domains override built-in defaults."""
        cfg = Config(
            company_root=aios_config.company_root,
            observation_domains={"agent-001-maker": "Custom domain: check widgets only"},
        )
        domain = _get_observation_domain("agent-001-maker", config=cfg)
        assert domain == "Custom domain: check widgets only"

    def test_unknown_agent_gets_generic_domain(self, aios_config):
        """Agents without a built-in domain get a generic fallback."""
        domain = _get_observation_domain("agent-999-unknown", config=aios_config)
        assert "General observation" in domain
        assert "task queue" in domain

    def test_builtin_default_used_when_no_config_override(self, aios_config):
        """Known agents use built-in defaults when config has no overrides."""
        domain = _get_observation_domain("agent-001-maker", config=aios_config)
        assert "Repository" in domain or "repo" in domain.lower()


# --- Scheduler dispatch tests ---


class TestObserveSchedulerDispatch:
    """Observe-cycle scheduler integration."""

    @pytest.mark.asyncio
    async def test_observe_dispatches_when_due(self, tmp_path):
        """Observe cycle fires when cadence is due."""
        cfg = _make_observe_cfg(tmp_path)

        with (
            patch("agent_os.scheduler._now", return_value=datetime(2026, 5, 9, 10, 0, tzinfo=cfg.tz)),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001-maker")]),
            patch("agent_os.runner.run_observe_cycle", new_callable=AsyncMock) as mock_observe,
        ):
            result = await tick(config=cfg)

        mock_observe.assert_called_once_with("agent-001-maker", config=cfg)
        observe_dispatches = [d for d in result.dispatched if d.type == "observe"]
        assert len(observe_dispatches) == 1
        assert observe_dispatches[0].result == "done"

    @pytest.mark.asyncio
    async def test_observe_skipped_outside_operating_hours(self, tmp_path):
        """Observe is gated by operating hours."""
        cfg = _make_observe_cfg(tmp_path, schedule_operating_hours="07:00-23:00")

        with (
            patch("agent_os.scheduler._now", return_value=datetime(2026, 5, 9, 3, 0, tzinfo=cfg.tz)),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=False),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001-maker")]),
        ):
            result = await tick(config=cfg)

        assert "observe: outside operating hours" in result.skipped
        observe_dispatches = [d for d in result.dispatched if d.type == "observe"]
        assert len(observe_dispatches) == 0

    @pytest.mark.asyncio
    async def test_observe_disabled_does_nothing(self, tmp_path):
        """Observe cycles don't fire when disabled."""
        cfg = _make_observe_cfg(tmp_path, schedule_observe_enabled=False)

        with (
            patch("agent_os.scheduler._now", return_value=datetime(2026, 5, 9, 10, 0, tzinfo=cfg.tz)),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001-maker")]),
            patch("agent_os.runner.run_observe_cycle", new_callable=AsyncMock) as mock_observe,
        ):
            result = await tick(config=cfg)

        mock_observe.assert_not_called()
        observe_dispatches = [d for d in result.dispatched if d.type == "observe"]
        assert len(observe_dispatches) == 0

    @pytest.mark.asyncio
    async def test_observe_one_agent_per_tick(self, tmp_path):
        """Only one agent dispatched per tick (break after first)."""
        cfg = _make_observe_cfg(tmp_path)
        agents = [_FakeAgent(f"agent-{i:03d}") for i in range(5)]

        with (
            patch("agent_os.scheduler._now", return_value=datetime(2026, 5, 9, 10, 0, tzinfo=cfg.tz)),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=agents),
            patch("agent_os.runner.run_observe_cycle", new_callable=AsyncMock),
        ):
            result = await tick(config=cfg)

        observe_dispatches = [d for d in result.dispatched if d.type == "observe"]
        assert len(observe_dispatches) == 1

    @pytest.mark.asyncio
    async def test_observe_cadence_respected(self, tmp_path):
        """After dispatch, cadence prevents immediate re-dispatch."""
        cfg = _make_observe_cfg(tmp_path, schedule_observe_interval_minutes=360)

        # First tick: should dispatch
        with (
            patch("agent_os.scheduler._now", return_value=datetime(2026, 5, 9, 10, 0, tzinfo=cfg.tz)),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001-maker")]),
            patch("agent_os.runner.run_observe_cycle", new_callable=AsyncMock),
        ):
            result1 = await tick(config=cfg)

        assert len([d for d in result1.dispatched if d.type == "observe"]) == 1

        # Second tick immediately after: should NOT dispatch (cadence not met)
        with (
            patch("agent_os.scheduler._now", return_value=datetime(2026, 5, 9, 10, 1, tzinfo=cfg.tz)),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001-maker")]),
            patch("agent_os.runner.run_observe_cycle", new_callable=AsyncMock) as mock_observe,
        ):
            result2 = await tick(config=cfg)

        mock_observe.assert_not_called()
        assert len([d for d in result2.dispatched if d.type == "observe"]) == 0

    @pytest.mark.asyncio
    async def test_observe_stagger_offsets_agents(self, tmp_path):
        """Stagger adds per-agent offset to the cadence interval."""
        cfg = _make_observe_cfg(
            tmp_path,
            schedule_observe_interval_minutes=60,
            schedule_observe_stagger_minutes=10,
        )
        agents = [_FakeAgent("agent-001"), _FakeAgent("agent-002")]

        # Both due on first run
        with (
            patch("agent_os.scheduler._now", return_value=datetime(2026, 5, 9, 10, 0, tzinfo=cfg.tz)),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=agents),
            patch("agent_os.runner.run_observe_cycle", new_callable=AsyncMock),
        ):
            result = await tick(config=cfg)

        # Only first agent dispatched (one-per-tick)
        observe_dispatches = [d for d in result.dispatched if d.type == "observe"]
        assert len(observe_dispatches) == 1
        assert observe_dispatches[0].agent == "agent-001"


class TestObserveDispatchOutcomes:
    """Observe dispatch leaves structured outcome records in agent logs."""

    @pytest.mark.asyncio
    async def test_success_writes_outcome(self, tmp_path):
        cfg = _make_observe_cfg(tmp_path)

        with (
            patch("agent_os.scheduler._now", return_value=datetime(2026, 5, 9, 10, 0, tzinfo=cfg.tz)),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001-maker")]),
            patch("agent_os.runner.run_observe_cycle", new_callable=AsyncMock),
        ):
            await tick(config=cfg)

        outcomes = _read_dispatch_outcomes(cfg, "agent-001-maker")
        assert len(outcomes) == 1
        assert outcomes[0]["refs"]["type"] == "observe"
        assert outcomes[0]["refs"]["outcome"] == "success"
        assert outcomes[0]["level"] == "info"

    @pytest.mark.asyncio
    async def test_error_writes_outcome(self, tmp_path):
        cfg = _make_observe_cfg(tmp_path)

        with (
            patch("agent_os.scheduler._now", return_value=datetime(2026, 5, 9, 10, 0, tzinfo=cfg.tz)),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001-maker")]),
            patch(
                "agent_os.runner.run_observe_cycle",
                new_callable=AsyncMock,
                side_effect=RuntimeError("API down"),
            ),
        ):
            await tick(config=cfg)

        outcomes = _read_dispatch_outcomes(cfg, "agent-001-maker")
        assert len(outcomes) == 1
        assert outcomes[0]["refs"]["outcome"] == "error"
        assert outcomes[0]["refs"]["error"] == "API down"
        assert outcomes[0]["level"] == "error"

    @pytest.mark.asyncio
    async def test_locked_writes_outcome(self, tmp_path):
        cfg = _make_observe_cfg(tmp_path)

        with (
            patch("agent_os.scheduler._now", return_value=datetime(2026, 5, 9, 10, 0, tzinfo=cfg.tz)),
            patch("agent_os.scheduler.is_within_operating_hours", return_value=True),
            patch("agent_os.scheduler.check_budget", return_value=_FakeBudget()),
            patch("agent_os.scheduler.list_agents", return_value=[_FakeAgent("agent-001-maker")]),
            patch("agent_os.scheduler.acquire_lock", return_value=None),
            patch("agent_os.runner.run_observe_cycle", new_callable=AsyncMock) as mock_observe,
        ):
            await tick(config=cfg)

        outcomes = _read_dispatch_outcomes(cfg, "agent-001-maker")
        assert len(outcomes) == 1
        assert outcomes[0]["refs"]["outcome"] == "locked"
        assert outcomes[0]["refs"]["type"] == "observe"
        mock_observe.assert_not_called()


# --- Config tests ---


class TestObserveConfig:
    """Config fields for observe cycles."""

    def test_default_values(self):
        """Verify sensible defaults for observe config."""
        cfg = Config()
        assert cfg.schedule_observe_enabled is True
        assert cfg.schedule_observe_interval_minutes == 360
        assert cfg.schedule_observe_stagger_minutes == 5
        assert cfg.observe_model == "claude-sonnet-4-6"
        assert cfg.observe_max_budget_usd == 1.00
        assert cfg.observe_max_turns == 20
        assert cfg.observation_domains == {}

    def test_toml_parsing(self, tmp_path):
        """Observe config loads correctly from TOML."""
        toml_content = """\
[company]
root = "."

[schedule.observe]
enabled = false
interval_minutes = 120
stagger_minutes = 3

[observe]
model = "claude-haiku-4-6"
domains = { "agent-001" = "Check widgets" }

[budget]
observe = 0.50
"""
        toml_path = tmp_path / "agent-os.toml"
        toml_path.write_text(toml_content)
        (tmp_path / "agents" / "registry").mkdir(parents=True)

        cfg = Config.from_toml(toml_path)
        assert cfg.schedule_observe_enabled is False
        assert cfg.schedule_observe_interval_minutes == 120
        assert cfg.schedule_observe_stagger_minutes == 3
        assert cfg.observe_model == "claude-haiku-4-6"
        assert cfg.observation_domains == {"agent-001": "Check widgets"}
        assert cfg.observe_max_budget_usd == 0.50


# --- Prompt template tests ---


class TestObservePromptTemplate:
    """Observe prompt template renders correctly."""

    def test_template_renders_with_variables(self):
        """Template renders with agent_id, domain, and observations_dir."""
        from agent_os.composer import PromptComposer

        cfg = Config()
        composer = PromptComposer(config=cfg)
        rendered = composer.render_template(
            "observe.jinja2",
            agent_id="agent-001-maker",
            observation_domain="Check the repo and git status.",
            observations_dir="/srv/corvyd/company/agents/state",
        )
        assert "agent-001-maker" in rendered
        assert "Check the repo and git status." in rendered
        assert "observe-latest.json" in rendered
        assert "Do NOT take action" in rendered

    def test_template_emphasizes_raw_output(self):
        """Template instructs agents to record raw tool output first."""
        from agent_os.composer import PromptComposer

        cfg = Config()
        composer = PromptComposer(config=cfg)
        rendered = composer.render_template(
            "observe.jinja2",
            agent_id="test",
            observation_domain="test domain",
            observations_dir="/tmp",
        )
        assert "raw" in rendered.lower()
        assert "json" in rendered.lower()


# --- Schedule status display ---


class TestObserveScheduleStatus:
    """Observe cycles appear in schedule status output."""

    def test_schedule_status_includes_observe(self, tmp_path):
        from agent_os.scheduler import get_schedule_status

        cfg = _make_observe_cfg(tmp_path)
        status = get_schedule_status(config=cfg)
        assert "Observe" in status

    def test_dispatch_status_includes_observe(self, tmp_path):
        from agent_os.events import get_dispatch_status

        cfg = _make_observe_cfg(tmp_path)
        # Need a registry file for list_agents
        reg_file = cfg.registry_dir / "agent-001-maker.md"
        reg_file.write_text(
            "---\n"
            "id: agent-001-maker\n"
            "name: The Maker\n"
            "role: Software Engineer\n"
            "model: claude-opus-4-6\n"
            "tools: [Read]\n"
            "---\n\nTest.\n"
        )

        rows = get_dispatch_status(config=cfg)
        observe_rows = [r for r in rows if r["cycle_type"] == "observe"]
        assert len(observe_rows) == 1
        assert observe_rows[0]["enabled"] is True
        assert observe_rows[0]["cadence"] == "360m"


# --- Write commands ---


class TestObserveWriteCommands:
    """Toggle schedule includes observe."""

    def test_schedule_kinds_includes_observe(self):
        from agent_os.write_cmds import SCHEDULE_KINDS

        assert "observe" in SCHEDULE_KINDS
