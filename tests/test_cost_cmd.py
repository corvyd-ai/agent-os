"""TDD tests for `agent-os cost` — spend rollup with plotext bars.

Red-first. Exercises the pure-data aggregation (`aggregate_costs`) separate
from rendering so assertions stay deterministic.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from agent_os.config import Config


def _write_costs(cfg: Config, date_iso: str, entries: list[dict]) -> None:
    cfg.costs_dir.mkdir(parents=True, exist_ok=True)
    (cfg.costs_dir / f"{date_iso}.jsonl").write_text("\n".join(json.dumps(e) for e in entries) + "\n")


# --------------------------------------------------------------------------
# Cycle 1: aggregate_costs returns a structured dict keyed by date
# --------------------------------------------------------------------------


def test_aggregate_costs_rollup_shape(aios_config: Config):
    from agent_os.cost_cmd import aggregate_costs

    today = datetime.now(aios_config.tz).date().isoformat()
    _write_costs(
        aios_config,
        today,
        [
            {"agent": "agent-001-maker", "task": "task-a", "cost_usd": 1.0},
            {"agent": "agent-002-writer", "task": "drive-consultation", "cost_usd": 0.5},
        ],
    )
    result = aggregate_costs(aios_config, days=7)

    assert "daily" in result
    assert "by_agent" in result
    assert "by_task_type" in result
    assert "total_usd" in result
    assert result["total_usd"] == 1.5


def test_aggregate_costs_by_agent(aios_config: Config):
    from agent_os.cost_cmd import aggregate_costs

    today = datetime.now(aios_config.tz).date().isoformat()
    _write_costs(
        aios_config,
        today,
        [
            {"agent": "agent-001-maker", "task": "task-a", "cost_usd": 1.0},
            {"agent": "agent-001-maker", "task": "task-b", "cost_usd": 0.25},
            {"agent": "agent-002-writer", "task": "task-c", "cost_usd": 0.5},
        ],
    )
    result = aggregate_costs(aios_config, days=7)

    assert result["by_agent"]["agent-001-maker"] == 1.25
    assert result["by_agent"]["agent-002-writer"] == 0.5


def test_aggregate_costs_by_task_type(aios_config: Config):
    from agent_os.cost_cmd import aggregate_costs

    today = datetime.now(aios_config.tz).date().isoformat()
    _write_costs(
        aios_config,
        today,
        [
            {"agent": "agent-001-maker", "task": "task-abc-001", "cost_usd": 1.0},
            {"agent": "agent-001-maker", "task": "drive-consultation", "cost_usd": 0.5},
            {"agent": "agent-001-maker", "task": "standing-order-dawn", "cost_usd": 0.25},
        ],
    )
    result = aggregate_costs(aios_config, days=7)

    # task-type classification: task-*, drive-*, standing-order-*, other
    assert result["by_task_type"]["task"] == 1.0
    assert result["by_task_type"]["drive"] == 0.5
    assert result["by_task_type"]["standing-order"] == 0.25


def test_aggregate_costs_empty_is_zero(aios_config: Config):
    from agent_os.cost_cmd import aggregate_costs

    result = aggregate_costs(aios_config, days=7)
    assert result["total_usd"] == 0
    assert result["by_agent"] == {}


# --------------------------------------------------------------------------
# Cycle 2: render_cost produces readable human output
# --------------------------------------------------------------------------


def test_render_cost_shows_total(aios_config: Config):
    from agent_os.cost_cmd import render_cost

    today = datetime.now(aios_config.tz).date().isoformat()
    _write_costs(aios_config, today, [{"agent": "agent-001-maker", "task": "task-a", "cost_usd": 2.75}])

    out = render_cost(aios_config, days=7)
    assert "2.75" in out or "$2.75" in out


def test_render_cost_by_agent_breakdown(aios_config: Config):
    from agent_os.cost_cmd import render_cost

    today = datetime.now(aios_config.tz).date().isoformat()
    _write_costs(
        aios_config,
        today,
        [
            {"agent": "agent-001-maker", "task": "task-a", "cost_usd": 1.0},
            {"agent": "agent-002-writer", "task": "task-b", "cost_usd": 0.5},
        ],
    )

    out = render_cost(aios_config, days=7, by="agent")
    assert "agent-001-maker" in out
    assert "agent-002-writer" in out


# --------------------------------------------------------------------------
# Cycle 3: multiple days are summed correctly
# --------------------------------------------------------------------------


def test_aggregate_costs_sums_multiple_days(aios_config: Config):
    from agent_os.cost_cmd import aggregate_costs

    today = datetime.now(aios_config.tz).date()
    _write_costs(
        aios_config,
        today.isoformat(),
        [{"agent": "agent-001-maker", "task": "task-a", "cost_usd": 1.0}],
    )
    _write_costs(
        aios_config,
        (today - timedelta(days=1)).isoformat(),
        [{"agent": "agent-001-maker", "task": "task-b", "cost_usd": 2.0}],
    )

    result = aggregate_costs(aios_config, days=7)
    assert result["total_usd"] == 3.0
    assert len(result["daily"]) == 2  # two days have entries


# --------------------------------------------------------------------------
# Cycle 4: JSON output is parseable and stable
# --------------------------------------------------------------------------


def test_render_cost_json_is_parseable(aios_config: Config):
    from agent_os.cost_cmd import render_cost_json

    today = datetime.now(aios_config.tz).date().isoformat()
    _write_costs(aios_config, today, [{"agent": "agent-001-maker", "task": "task-a", "cost_usd": 1.5}])

    parsed = json.loads(render_cost_json(aios_config, days=7))
    assert parsed["total_usd"] == 1.5
    assert "by_agent" in parsed


# --------------------------------------------------------------------------
# Cycle 5: CLI wiring
# --------------------------------------------------------------------------


def test_cli_registers_cost_subparser():
    from agent_os.cli import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["cost"])
    assert args.command == "cost"
    assert hasattr(args, "days")
    assert hasattr(args, "by")
    assert hasattr(args, "format")


def test_cli_cost_json_roundtrip(aios_config: Config, capsys):
    from agent_os.cli import cmd_cost
    from agent_os.config import Config as _Cfg
    from agent_os.config import configure

    today = datetime.now(aios_config.tz).date().isoformat()
    _write_costs(aios_config, today, [{"agent": "agent-001-maker", "task": "task-a", "cost_usd": 0.9}])

    # Pass --root so _set_root resolves back to our tmp company rather than cwd.
    args = type(
        "Args",
        (),
        {"format": "json", "days": 7, "by": "agent", "root": str(aios_config.company_root), "config": None},
    )()

    configure(aios_config)
    try:
        cmd_cost(args)
    finally:
        configure(_Cfg())

    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["total_usd"] == 0.9
