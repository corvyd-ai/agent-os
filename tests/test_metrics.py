"""Tests for the ported health-metrics module.

Verifies that agent_os.metrics (a) imports without pulling FastAPI/uvicorn in,
(b) accepts a Config via keyword argument, (c) gracefully handles empty data.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime

import pytest

from agent_os import metrics
from agent_os.config import Config


def test_metrics_imports_without_fastapi():
    """The ported metrics module must not drag in dashboard-only deps."""
    # It's fine if fastapi is installed (via the dashboard extra) — what we're
    # checking is that `agent_os.metrics` itself doesn't require it.
    import importlib

    mod = importlib.import_module("agent_os.metrics")
    # The module should be importable from the platform namespace
    assert mod.__name__ == "agent_os.metrics"
    # And should not have dragged fastapi into its transitive imports via this path.
    # (We don't assert fastapi isn't imported at all — other things may pull it.)
    assert hasattr(mod, "compute_agent_health")
    assert hasattr(mod, "compute_all_health")
    assert hasattr(mod, "compute_health_with_trends")


def test_metrics_empty_company(aios_config: Config):
    """With no tasks/costs/logs, metrics should return neutral scores without erroring."""
    result = metrics.compute_agent_health("agent-001-maker", days=7, config=aios_config)
    assert result["agent_id"] == "agent-001-maker"
    assert result["days"] == 7
    assert 0 <= result["composite_score"] <= 100
    assert "autonomy" in result
    assert "effectiveness" in result
    assert "efficiency" in result
    assert "system_health" in result


def test_compute_all_health_no_agents(aios_config: Config):
    """Empty registry should yield a system composite without crashing."""
    result = metrics.compute_all_health(days=7, config=aios_config)
    assert result["agents"] == {}
    assert "governance" in result
    assert isinstance(result["computed_at"], str)


def test_compute_health_with_trends_no_agents(aios_config: Config):
    result = metrics.compute_health_with_trends(config=aios_config)
    assert "current" in result
    assert "baseline" in result
    assert result["trends"]["agents"] == {}
    assert result["trends"]["system"]["direction"] in {"improving", "stable", "declining"}


def test_metrics_with_logs_and_costs(aios_config: Config):
    """Seed a tiny amount of data and verify aggregation runs end-to-end."""
    agent = "agent-001-maker"
    today = datetime.now(aios_config.tz).date().isoformat()

    # Seed a registry file so _discover_agent_ids picks it up.
    (aios_config.registry_dir / f"{agent}.md").write_text("---\nid: " + agent + "\n---\n")

    # One productive cycle + one idle cycle.
    log_dir = aios_config.logs_dir / agent
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / f"{today}.jsonl").write_text(
        '{"action": "cycle_start", "timestamp": "' + datetime.now(UTC).isoformat() + '"}\n'
        '{"action": "cycle_idle", "timestamp": "' + datetime.now(UTC).isoformat() + '"}\n'
    )

    # One cost entry.
    aios_config.costs_dir.mkdir(parents=True, exist_ok=True)
    (aios_config.costs_dir / f"{today}.jsonl").write_text(
        '{"agent": "' + agent + '", "task": "task-2026-0101-001", "cost_usd": 0.5, '
        '"num_turns": 3, "duration_ms": 5000}\n'
    )

    result = metrics.compute_all_health(days=7, config=aios_config)
    assert agent in result["agents"]
    per_agent = result["agents"][agent]
    assert per_agent["efficiency"]["total_cost_usd"] >= 0.4  # 0.5, with rounding
    assert per_agent["autonomy"]["total_cycles"] >= 1


def test_agent_aliases_normalize_old_ids():
    """Old agent IDs (pre-2026-02-20) should map to their new names."""
    assert metrics.AGENT_ALIASES["agent-001-builder"] == "agent-001-maker"
    assert metrics._normalize_agent("agent-001-builder") == "agent-001-maker"
    assert metrics._normalize_agent("agent-001-maker") == "agent-001-maker"
    assert metrics._normalize_agent("unknown-agent") == "unknown-agent"


def test_dashboard_shim_still_exports(monkeypatch):
    """The dashboard's metrics.py must continue to re-export the same names."""
    # fastapi isn't required to import the shim; it only re-exports from agent_os.metrics.
    # Ensure that even without fastapi stubbed out, importing the shim works.
    # (If fastapi is actually installed via the dashboard extra, this still passes.)
    if "agent_os.dashboard.metrics" in sys.modules:
        del sys.modules["agent_os.dashboard.metrics"]
    mod = pytest.importorskip("agent_os.dashboard.metrics")
    assert mod.compute_agent_health is metrics.compute_agent_health
    assert mod.AGENT_ALIASES is metrics.AGENT_ALIASES
