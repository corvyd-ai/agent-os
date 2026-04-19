"""Tests for the ported health-metrics module.

Three layers:
  - smoke: imports, empty-company graceful paths
  - numerical correctness: seeded fixtures with hand-computed expected scores
    for each of the 5 sub-metrics (the primary defense against port drift)
  - aliasing + parity: old agent IDs roll up correctly; dashboard shim stays
    identity-equal to the platform module
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_os import metrics
from agent_os.config import Config

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _write_task(directory: Path, task_id: str, **frontmatter) -> None:
    """Write a task markdown file with the given frontmatter."""
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"id: {task_id}"]
    for key, value in frontmatter.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    (directory / f"{task_id}.md").write_text("\n".join(lines))


def _write_log(cfg: Config, agent: str, date_iso: str, entries: list[dict]) -> None:
    log_dir = cfg.logs_dir / agent
    log_dir.mkdir(parents=True, exist_ok=True)
    import json

    (log_dir / f"{date_iso}.jsonl").write_text("\n".join(json.dumps(e) for e in entries) + "\n")


def _write_costs(cfg: Config, date_iso: str, entries: list[dict]) -> None:
    cfg.costs_dir.mkdir(parents=True, exist_ok=True)
    import json

    (cfg.costs_dir / f"{date_iso}.jsonl").write_text("\n".join(json.dumps(e) for e in entries) + "\n")


def _today(cfg: Config) -> str:
    return datetime.now(cfg.tz).date().isoformat()


def _register(cfg: Config, agent_id: str) -> None:
    cfg.registry_dir.mkdir(parents=True, exist_ok=True)
    (cfg.registry_dir / f"{agent_id}.md").write_text(f"---\nid: {agent_id}\n---\n")


# --------------------------------------------------------------------------
# Smoke / import hygiene
# --------------------------------------------------------------------------


def test_metrics_module_is_importable_standalone():
    """agent_os.metrics should be importable without the dashboard being present."""
    import importlib

    mod = importlib.import_module("agent_os.metrics")
    assert mod.__name__ == "agent_os.metrics"
    for name in (
        "compute_agent_health",
        "compute_all_health",
        "compute_health_with_trends",
        "compute_autonomy",
        "compute_effectiveness",
        "compute_efficiency",
        "compute_governance",
        "compute_system_health",
        "AGENT_ALIASES",
    ):
        assert hasattr(mod, name), f"missing export: {name}"


def test_metrics_empty_company_returns_neutral(aios_config: Config):
    """With zero data, every sub-score should be finite and in [0, 100]."""
    result = metrics.compute_agent_health("agent-001-maker", days=7, config=aios_config)
    assert result["agent_id"] == "agent-001-maker"
    assert 0 <= result["composite_score"] <= 100
    for key in ("autonomy", "effectiveness", "efficiency", "system_health"):
        assert 0 <= result[key]["score"] <= 100


def test_compute_all_health_empty_registry(aios_config: Config):
    result = metrics.compute_all_health(days=7, config=aios_config)
    assert result["agents"] == {}
    assert "governance" in result
    assert 0 <= result["system_composite"] <= 100


def test_compute_health_with_trends_empty(aios_config: Config):
    result = metrics.compute_health_with_trends(config=aios_config)
    assert result["trends"]["agents"] == {}
    assert result["trends"]["system"]["direction"] in {"improving", "stable", "declining"}


# --------------------------------------------------------------------------
# A. Autonomy — numerical correctness
# --------------------------------------------------------------------------


def test_autonomy_empty_state_uses_defaults(aios_config: Config):
    """No logs / tasks / decisions → documented default values.

    With an empty state:
      - cycle_actions = 0, idle = 0, total_cycles = max(0, 1) = 1
      - productive_cycles = 1 - 0 = 1, ratio = 1/1 = 1.0
      - escalation_rate = 0 / max(0, 1) = 0.0
      - self_initiated_ratio = 0 / max(0, 1) = 0.0
      - decision_autonomy = default 0.5 (no decisions)
      - score = 1.0*30 + (1-0)*25 + 0*20 + 0.5*25 = 30 + 25 + 0 + 12.5 = 67.5
    """
    result = metrics.compute_autonomy("agent-001-maker", days=7, config=aios_config)
    assert result["productive_cycle_ratio"] == 1.0
    assert result["escalation_rate"] == 0.0
    assert result["self_initiated_ratio"] == 0.0
    assert result["decision_autonomy"] == 0.5
    assert result["score"] == 67.5
    assert result["tasks_completed"] == 0
    assert result["human_tasks_created"] == 0


def test_autonomy_mixed_state_exact_score(aios_config: Config):
    """Seed known inputs and verify exact expected autonomy score.

    Inputs:
      - 4 cycle_start + 1 cycle_idle → total=5, productive=4, ratio=0.8
      - 2 done tasks assigned to agent; 1 self-initiated, 1 created by human
      - 0 human tasks created by agent → escalation_rate = 0/2 = 0
      - 1 agent decision, 0 human decisions → decision_autonomy = 1.0

    Expected score = 0.8*30 + (1-0)*25 + 0.5*20 + 1.0*25
                   = 24 + 25 + 10 + 25 = 84.0
    """
    agent = "agent-001-maker"
    today = _today(aios_config)
    _register(aios_config, agent)

    ts = datetime.now(UTC).isoformat()
    _write_log(
        aios_config,
        agent,
        today,
        [
            {"action": "cycle_start", "timestamp": ts},
            {"action": "cycle_start", "timestamp": ts},
            {"action": "cycle_start", "timestamp": ts},
            {"action": "cycle_start", "timestamp": ts},
            {"action": "cycle_idle", "timestamp": ts},
        ],
    )

    _write_task(aios_config.tasks_done, "task-2026-0419-001", assigned_to=agent, created_by=agent)
    _write_task(aios_config.tasks_done, "task-2026-0419-002", assigned_to=agent, created_by="human")

    aios_config.decisions_dir.mkdir(parents=True, exist_ok=True)
    (aios_config.decisions_dir / "decision-2026-0419-001.md").write_text(
        f"---\nid: decision-2026-0419-001\ndecided_by: {agent}\ndate: {today}\n---\n"
    )

    result = metrics.compute_autonomy(agent, days=7, config=aios_config)
    assert result["productive_cycles"] == 4
    assert result["total_cycles"] == 5
    assert result["tasks_completed"] == 2
    assert result["self_initiated_tasks"] == 1
    assert result["human_tasks_created"] == 0
    assert result["productive_cycle_ratio"] == 0.8
    assert result["escalation_rate"] == 0.0
    assert result["self_initiated_ratio"] == 0.5
    assert result["decision_autonomy"] == 1.0
    assert result["score"] == 84.0


# --------------------------------------------------------------------------
# B. Effectiveness — numerical correctness
# --------------------------------------------------------------------------


def test_effectiveness_exact_score(aios_config: Config):
    """Seed 2 done + 1 failed + 1 task cost with 10-min duration.

    - completion_rate = 2 / (2+1) = 0.6667
    - throughput = 2 / 7 ≈ 0.2857
    - throughput_score = min(0.2857/3, 1) ≈ 0.0952
    - mean_duration_ms = 600000 (10 minutes)
    - duration_score = 1 - (600000 / 1_800_000) = 0.6667
    - score = 0.6667*40 + 0.0952*30 + 0.6667*30
            = 26.667 + 2.857 + 20.0 = 49.524 → 49.5
    """
    agent = "agent-001-maker"
    today = _today(aios_config)
    _register(aios_config, agent)

    _write_task(aios_config.tasks_done, "task-2026-0419-001", assigned_to=agent)
    _write_task(aios_config.tasks_done, "task-2026-0419-002", assigned_to=agent)
    _write_task(aios_config.tasks_failed, "task-2026-0419-003", assigned_to=agent)

    _write_costs(
        aios_config,
        today,
        [
            {
                "agent": agent,
                "task": "task-2026-0419-001",
                "cost_usd": 1.0,
                "num_turns": 5,
                "duration_ms": 600_000,
            }
        ],
    )

    result = metrics.compute_effectiveness(agent, days=7, config=aios_config)
    assert result["tasks_done"] == 2
    assert result["tasks_failed"] == 1
    assert result["tasks_total"] == 3
    assert result["completion_rate"] == 0.667  # round(2/3, 3)
    assert result["mean_duration_ms"] == 600_000
    assert result["score"] == 49.5


def test_effectiveness_no_failures_is_perfect_completion(aios_config: Config):
    """Zero failed tasks → completion_rate = 1.0 (safe_ratio default)."""
    agent = "agent-001-maker"
    _register(aios_config, agent)
    _write_task(aios_config.tasks_done, "task-001", assigned_to=agent)

    result = metrics.compute_effectiveness(agent, days=7, config=aios_config)
    assert result["completion_rate"] == 1.0
    assert result["tasks_failed"] == 0


# --------------------------------------------------------------------------
# C. Efficiency — numerical correctness
# --------------------------------------------------------------------------


def test_efficiency_exact_score(aios_config: Config):
    """Seed 3 cost entries (2 task + 1 drive) and 2 done tasks.

    - total_cost = 1.0 + 2.0 + 1.0 = 4.0
    - total_turns = 10 + 20 + 10 = 40
    - task_total_cost = 3.0 (only task-* entries)
    - done_by_agent = 2
    - cost_per_task = 3.0 / 2 = 1.5
    - cost_per_turn = 4.0 / 40 = 0.1
    - idle_cost_ratio = 1.0 / 4.0 = 0.25
    - cost_score = 1 - (1.5 / 10) = 0.85
    - idle_score = 1 - 0.25 = 0.75
    - turn_efficiency = 1 - (0.1 / 0.15) = 0.3333
    - score = 0.85*35 + 0.75*35 + 0.3333*30 = 29.75 + 26.25 + 10.0 = 66.0
    """
    agent = "agent-001-maker"
    today = _today(aios_config)
    _register(aios_config, agent)

    _write_task(aios_config.tasks_done, "task-a", assigned_to=agent)
    _write_task(aios_config.tasks_done, "task-b", assigned_to=agent)

    _write_costs(
        aios_config,
        today,
        [
            {"agent": agent, "task": "task-a", "cost_usd": 1.0, "num_turns": 10},
            {"agent": agent, "task": "task-b", "cost_usd": 2.0, "num_turns": 20},
            {"agent": agent, "task": "drive-consultation", "cost_usd": 1.0, "num_turns": 10},
        ],
    )

    result = metrics.compute_efficiency(agent, days=7, config=aios_config)
    assert result["total_cost_usd"] == 4.0
    assert result["total_turns"] == 40
    assert result["task_invocations"] == 2
    assert result["drive_invocations"] == 1
    assert result["standing_order_invocations"] == 0
    assert result["cost_per_task_usd"] == 1.5
    assert result["cost_per_turn_usd"] == 0.1
    assert result["idle_cost_ratio"] == 0.25
    assert result["score"] == 66.0


# --------------------------------------------------------------------------
# D. Governance — numerical correctness
# --------------------------------------------------------------------------


def test_governance_exact_score(aios_config: Config):
    """Seed 1 active proposal, 2 decided, 2 decisions, 2 threads.

    - active_proposals = 1, period_decided = 2
    - proposal_throughput = 2 / (1+2) = 0.6667
    - decisions_in_period = 2, decision_score = min(2 / (7/7), 1) = 1.0
    - threads: 1 resolved + 1 active; resolution_rate = 0.5
    - response_times = [2.0 hours] (one thread has 2h between msgs)
    - mean_response_hours = 2.0; response_score = 1 - (2/24) = 0.9167
    - score = 0.6667*25 + 0.5*30 + 0.9167*25 + 1.0*20
            = 16.6667 + 15.0 + 22.9167 + 20.0 = 74.5833 → 74.6
    """
    today = _today(aios_config)

    aios_config.proposals_active.mkdir(parents=True, exist_ok=True)
    (aios_config.proposals_active / "proposal-a.md").write_text(
        f"---\nid: proposal-a\nstatus: active\ndate: {today}\n---\n"
    )
    aios_config.proposals_decided.mkdir(parents=True, exist_ok=True)
    for pid in ("proposal-b", "proposal-c"):
        (aios_config.proposals_decided / f"{pid}.md").write_text(
            f"---\nid: {pid}\nstatus: decided\ndate: {today}\n---\n"
        )

    aios_config.decisions_dir.mkdir(parents=True, exist_ok=True)
    for did in ("decision-a", "decision-b"):
        (aios_config.decisions_dir / f"{did}.md").write_text(f"---\nid: {did}\ndate: {today}\n---\n")

    aios_config.threads_dir.mkdir(parents=True, exist_ok=True)
    (aios_config.threads_dir / "thread-resolved.md").write_text(
        "---\nid: thread-resolved\nstatus: resolved\n---\n"
    )
    (aios_config.threads_dir / "thread-active.md").write_text(
        "---\nid: thread-active\nstatus: active\n---\n\n"
        "## agent-001-maker — 2026-04-19T10:00:00+00:00\n\nfirst.\n\n---\n\n"
        "## agent-001-maker — 2026-04-19T12:00:00+00:00\n\nsecond.\n"
    )

    result = metrics.compute_governance(days=7, config=aios_config)
    assert result["active_proposals"] == 1
    assert result["decided_proposals_in_period"] == 2
    assert result["decisions_in_period"] == 2
    assert result["total_threads"] == 2
    assert result["resolved_threads"] == 1
    assert result["active_threads"] == 1
    assert result["resolution_rate"] == 0.5
    assert result["proposal_throughput"] == 0.667
    assert result["mean_response_hours"] == 2.0
    assert result["score"] == 74.6


# --------------------------------------------------------------------------
# E. System health — numerical correctness
# --------------------------------------------------------------------------


def test_system_health_clean_logs_no_errors(aios_config: Config):
    """5 non-error entries on one day → error_rate=0, adherence=1/7, perfect recovery.

    - error_rate = 0 → error_score = 1.0
    - active_days = 1, expected = 7 → schedule_adherence = 0.1429
    - no errors → recovery_score = 1.0
    - score = 1.0*40 + 0.1429*35 + 1.0*25 = 40 + 5.0 + 25 = 70.0
    """
    agent = "agent-001-maker"
    today = _today(aios_config)
    _register(aios_config, agent)

    ts = datetime.now(UTC).isoformat()
    _write_log(
        aios_config,
        agent,
        today,
        [{"action": "cycle_start", "timestamp": ts} for _ in range(5)],
    )

    result = metrics.compute_system_health(agent, days=7, config=aios_config)
    assert result["error_count"] == 0
    assert result["error_rate"] == 0.0
    assert result["active_days"] == 1
    assert result["schedule_adherence"] == 0.143
    assert result["mean_recovery_minutes"] == 0.0
    assert result["score"] == 70.0


# --------------------------------------------------------------------------
# Aliasing — old IDs must roll up under new IDs through the aggregation path
# --------------------------------------------------------------------------


def test_aliasing_normalize_direct():
    assert metrics.AGENT_ALIASES["agent-001-builder"] == "agent-001-maker"
    assert metrics._normalize_agent("agent-001-builder") == "agent-001-maker"
    assert metrics._normalize_agent("agent-001-maker") == "agent-001-maker"
    assert metrics._normalize_agent("unknown") == "unknown"


def test_aliasing_costs_roll_up_through_efficiency(aios_config: Config):
    """A cost entry logged under the OLD id ('agent-001-builder') must roll up
    under the NEW id ('agent-001-maker') when computing efficiency."""
    agent_new = "agent-001-maker"
    agent_old = "agent-001-builder"
    today = _today(aios_config)
    _register(aios_config, agent_new)

    _write_costs(
        aios_config,
        today,
        [
            {"agent": agent_old, "task": "task-legacy", "cost_usd": 0.5, "num_turns": 4},
            {"agent": agent_new, "task": "task-new", "cost_usd": 0.3, "num_turns": 2},
        ],
    )

    result = metrics.compute_efficiency(agent_new, days=7, config=aios_config)
    assert result["total_cost_usd"] == 0.8
    assert result["task_invocations"] == 2
    assert result["total_turns"] == 6


def test_aliasing_tasks_roll_up_through_autonomy(aios_config: Config):
    """A done task assigned_to=<old id> must count toward the new agent's completions."""
    agent_new = "agent-001-maker"
    agent_old = "agent-001-builder"
    _register(aios_config, agent_new)

    _write_task(aios_config.tasks_done, "task-legacy", assigned_to=agent_old, created_by=agent_old)

    result = metrics.compute_autonomy(agent_new, days=7, config=aios_config)
    assert result["tasks_completed"] == 1
    assert result["self_initiated_tasks"] == 1


# --------------------------------------------------------------------------
# Parity — dashboard shim must stay wired to agent_os.metrics
# --------------------------------------------------------------------------


def test_dashboard_shim_reexports_same_callables(monkeypatch):
    """The dashboard's metrics.py is a shim; its exports must be identity-equal
    to the platform module so both import paths call the same code."""
    if "agent_os.dashboard.metrics" in sys.modules:
        del sys.modules["agent_os.dashboard.metrics"]
    shim = pytest.importorskip("agent_os.dashboard.metrics")
    for name in (
        "compute_agent_health",
        "compute_all_health",
        "compute_autonomy",
        "compute_effectiveness",
        "compute_efficiency",
        "compute_governance",
        "compute_health_with_trends",
        "compute_system_health",
    ):
        assert getattr(shim, name) is getattr(metrics, name), f"{name} diverged"
    assert shim.AGENT_ALIASES is metrics.AGENT_ALIASES


def test_shim_and_direct_produce_identical_output(aios_config: Config):
    """Defense in depth: even if the shim diverged silently, seeded output
    through both paths must match. Catches any accidental re-implementation."""
    if "agent_os.dashboard.metrics" in sys.modules:
        del sys.modules["agent_os.dashboard.metrics"]
    shim = pytest.importorskip("agent_os.dashboard.metrics")

    agent = "agent-001-maker"
    today = _today(aios_config)
    _register(aios_config, agent)
    _write_task(aios_config.tasks_done, "task-a", assigned_to=agent, created_by=agent)
    _write_costs(
        aios_config,
        today,
        [{"agent": agent, "task": "task-a", "cost_usd": 0.7, "num_turns": 5, "duration_ms": 120_000}],
    )

    direct = metrics.compute_agent_health(agent, days=7, config=aios_config)
    via_shim = shim.compute_agent_health(agent, days=7, config=aios_config)
    assert direct == via_shim


# --------------------------------------------------------------------------
# compute_all_health + trends — integration across agents
# --------------------------------------------------------------------------


def test_compute_all_health_discovers_agents_from_registry(aios_config: Config):
    """Registry entries drive which agents get scored."""
    _register(aios_config, "agent-001-maker")
    _register(aios_config, "agent-002-writer")

    result = metrics.compute_all_health(days=7, config=aios_config)
    assert set(result["agents"].keys()) == {"agent-001-maker", "agent-002-writer"}


def test_compute_health_with_trends_detects_direction(aios_config: Config):
    """Sanity: trend direction should be one of improving/stable/declining."""
    _register(aios_config, "agent-001-maker")
    result = metrics.compute_health_with_trends(config=aios_config)
    for agent_trend in result["trends"]["agents"].values():
        assert agent_trend["direction"] in {"improving", "stable", "declining"}
