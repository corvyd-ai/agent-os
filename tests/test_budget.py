"""Tests for agent_os.budget — circuit breaker and cost aggregation."""

import json
from datetime import UTC, datetime, timedelta

from agent_os.budget import (
    check_agent_budget,
    check_budget,
    format_budget_report,
    get_daily_costs,
    get_period_costs,
)
from agent_os.config import Config


def _write_cost_entry(cfg, date_str, agent_id, cost_usd):
    """Write a single cost entry to a JSONL file."""
    cfg.costs_dir.mkdir(parents=True, exist_ok=True)
    cost_file = cfg.costs_dir / f"{date_str}.jsonl"
    entry = {
        "timestamp": f"{date_str}T12:00:00+00:00",
        "agent": agent_id,
        "task": "test-task",
        "cost_usd": cost_usd,
        "duration_ms": 1000,
        "model": "test-model",
        "num_turns": 5,
    }
    with open(cost_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


class TestGetDailyCosts:
    def test_no_cost_file(self, aios_config):
        assert get_daily_costs("2026-03-07", config=aios_config) == 0.0

    def test_single_entry(self, aios_config):
        _write_cost_entry(aios_config, "2026-03-07", "agent-001", 1.50)
        assert get_daily_costs("2026-03-07", config=aios_config) == 1.50

    def test_multiple_entries(self, aios_config):
        _write_cost_entry(aios_config, "2026-03-07", "agent-001", 1.50)
        _write_cost_entry(aios_config, "2026-03-07", "agent-002", 2.25)
        assert get_daily_costs("2026-03-07", config=aios_config) == 3.75

    def test_empty_lines_ignored(self, aios_config):
        aios_config.costs_dir.mkdir(parents=True, exist_ok=True)
        cost_file = aios_config.costs_dir / "2026-03-07.jsonl"
        cost_file.write_text('\n{"cost_usd": 1.0}\n\n')
        assert get_daily_costs("2026-03-07", config=aios_config) == 1.0

    def test_malformed_json_skipped(self, aios_config):
        aios_config.costs_dir.mkdir(parents=True, exist_ok=True)
        cost_file = aios_config.costs_dir / "2026-03-07.jsonl"
        cost_file.write_text('not-json\n{"cost_usd": 2.0}\n')
        assert get_daily_costs("2026-03-07", config=aios_config) == 2.0


class TestGetPeriodCosts:
    def test_single_day(self, aios_config):
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        _write_cost_entry(aios_config, today, "agent-001", 5.0)
        assert get_period_costs(1, config=aios_config) == 5.0

    def test_no_data(self, aios_config):
        assert get_period_costs(7, config=aios_config) == 0.0


class TestCheckBudget:
    def test_under_budget(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            daily_budget_cap_usd=100.0,
            weekly_budget_cap_usd=500.0,
            monthly_budget_cap_usd=2000.0,
        )
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        _write_cost_entry(cfg, today, "agent-001", 10.0)

        status = check_budget(config=cfg)
        assert not status.circuit_breaker_tripped
        assert status.daily_spent == 10.0
        assert status.daily_cap == 100.0
        assert status.daily_remaining == 90.0
        assert status.daily_pct == 10.0

    def test_daily_cap_tripped(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            daily_budget_cap_usd=10.0,
            weekly_budget_cap_usd=500.0,
            monthly_budget_cap_usd=2000.0,
        )
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        _write_cost_entry(cfg, today, "agent-001", 15.0)

        status = check_budget(config=cfg)
        assert status.circuit_breaker_tripped
        assert status.daily_remaining == 0.0

    def test_no_spend(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            daily_budget_cap_usd=100.0,
            weekly_budget_cap_usd=500.0,
            monthly_budget_cap_usd=2000.0,
        )
        status = check_budget(config=cfg)
        assert not status.circuit_breaker_tripped
        assert status.daily_spent == 0.0
        assert status.daily_remaining == 100.0


class TestCheckAgentBudget:
    def test_no_cap_configured(self, aios_config):
        within, spent = check_agent_budget("agent-001", config=aios_config)
        assert within is True
        assert spent == 0.0

    def test_within_cap(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            agent_daily_caps={"agent-001": 20.0},
        )
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        _write_cost_entry(cfg, today, "agent-001", 5.0)

        within, spent = check_agent_budget("agent-001", config=cfg)
        assert within is True
        assert spent == 5.0

    def test_over_cap(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            agent_daily_caps={"agent-001": 5.0},
        )
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        _write_cost_entry(cfg, today, "agent-001", 10.0)

        within, spent = check_agent_budget("agent-001", config=cfg)
        assert within is False
        assert spent == 10.0

    def test_other_agent_costs_not_counted(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            agent_daily_caps={"agent-001": 5.0},
        )
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        _write_cost_entry(cfg, today, "agent-002", 100.0)

        within, spent = check_agent_budget("agent-001", config=cfg)
        assert within is True
        assert spent == 0.0


class TestFormatBudgetReport:
    def test_basic_report(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            daily_budget_cap_usd=100.0,
            weekly_budget_cap_usd=500.0,
            monthly_budget_cap_usd=2000.0,
        )
        report = format_budget_report(config=cfg)
        assert "Budget Status" in report
        assert "Circuit breaker: OK" in report

    def test_tripped_report(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            daily_budget_cap_usd=1.0,
            weekly_budget_cap_usd=500.0,
            monthly_budget_cap_usd=2000.0,
        )
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        _write_cost_entry(cfg, today, "agent-001", 5.0)

        report = format_budget_report(config=cfg)
        assert "TRIPPED" in report


class TestBudgetSingleSourceOfTruth:
    """Budget totals must always derive from cost JSONL — no secondary counters."""

    def test_check_budget_reflects_jsonl_additions(self, aios_config):
        """check_budget() must reflect new JSONL entries written after a prior call."""
        cfg = Config(
            company_root=aios_config.company_root,
            daily_budget_cap_usd=100.0,
            weekly_budget_cap_usd=500.0,
            monthly_budget_cap_usd=2000.0,
        )
        today = datetime.now(UTC).strftime("%Y-%m-%d")

        # First check — no spend
        status1 = check_budget(config=cfg)
        assert status1.daily_spent == 0.0

        # Write cost entry
        _write_cost_entry(cfg, today, "agent-001", 7.50)

        # Second check — must reflect the new entry
        status2 = check_budget(config=cfg)
        assert status2.daily_spent == 7.50

        # Write another entry
        _write_cost_entry(cfg, today, "agent-003", 2.50)

        # Third check — cumulative
        status3 = check_budget(config=cfg)
        assert status3.daily_spent == 10.0

    def test_circuit_breaker_reconciles_against_jsonl(self, aios_config):
        """Circuit breaker trips based on live JSONL totals, not a cached counter."""
        cfg = Config(
            company_root=aios_config.company_root,
            daily_budget_cap_usd=10.0,
            weekly_budget_cap_usd=500.0,
            monthly_budget_cap_usd=2000.0,
        )
        today = datetime.now(UTC).strftime("%Y-%m-%d")

        # Under cap
        _write_cost_entry(cfg, today, "agent-001", 5.0)
        assert not check_budget(config=cfg).circuit_breaker_tripped

        # Push over cap
        _write_cost_entry(cfg, today, "agent-001", 6.0)
        assert check_budget(config=cfg).circuit_breaker_tripped

    def test_weekly_cap_derived_from_jsonl(self, aios_config):
        """Weekly cap checks must sum across multiple JSONL date files."""
        cfg = Config(
            company_root=aios_config.company_root,
            daily_budget_cap_usd=100.0,
            weekly_budget_cap_usd=20.0,
            monthly_budget_cap_usd=2000.0,
        )
        today = datetime.now(UTC)
        for i in range(3):
            date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            _write_cost_entry(cfg, date_str, "agent-001", 8.0)

        status = check_budget(config=cfg)
        assert status.weekly_spent == 24.0
        assert status.circuit_breaker_tripped  # 24 >= 20
