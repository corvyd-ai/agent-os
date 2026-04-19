"""TDD tests for the write commands:
  - agent-os schedule toggle <kind> [on|off]
  - agent-os budget set [--daily N] [--weekly M] [--monthly K]
  - agent-os autonomy <agent> <low|medium|high>

All of these mutate `agent-os.toml` via tomlkit, so the tests assert the
new value actually persists and the file remains parseable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_os.config import Config


@pytest.fixture
def toml_company(tmp_path, monkeypatch) -> tuple[Config, Path]:
    """Create a company with a realistic agent-os.toml on disk + Config.

    Returns (config, toml_path). Tests can mutate the TOML and then reload
    to verify persistence.
    """
    root = tmp_path / "company"
    root.mkdir()
    toml = root / "agent-os.toml"
    toml.write_text(
        """
[company]
name = "Test"
root = "."

[budget]
daily_cap = 10.0
weekly_cap = 50.0
monthly_cap = 200.0

[schedule]
enabled = true

[schedule.cycles]
enabled = true

[autonomy]
default = "medium"
""".strip()
        + "\n"
    )
    cfg = Config.from_toml(toml)
    return cfg, toml


# --------------------------------------------------------------------------
# budget set
# --------------------------------------------------------------------------


def test_set_budget_caps_updates_daily(toml_company):
    from agent_os.write_cmds import set_budget_caps

    cfg, toml = toml_company
    set_budget_caps(toml, daily=25.0)

    reloaded = Config.from_toml(toml)
    assert reloaded.daily_budget_cap_usd == 25.0
    # Weekly and monthly untouched.
    assert reloaded.weekly_budget_cap_usd == 50.0


def test_set_budget_caps_updates_all_three(toml_company):
    from agent_os.write_cmds import set_budget_caps

    _, toml = toml_company
    set_budget_caps(toml, daily=30.0, weekly=150.0, monthly=500.0)

    reloaded = Config.from_toml(toml)
    assert reloaded.daily_budget_cap_usd == 30.0
    assert reloaded.weekly_budget_cap_usd == 150.0
    assert reloaded.monthly_budget_cap_usd == 500.0


def test_set_budget_caps_preserves_comments(tmp_path):
    """tomlkit round-trip must preserve top-of-file comments."""
    from agent_os.write_cmds import set_budget_caps

    toml = tmp_path / "agent-os.toml"
    toml.write_text(
        "# Our company config\n\n"
        '[company]\nname = "X"\nroot = "."\n\n'
        "[budget]\ndaily_cap = 5.0\n"
    )
    set_budget_caps(toml, daily=12.0)
    text = toml.read_text()
    assert "Our company config" in text
    assert "daily_cap = 12.0" in text


# --------------------------------------------------------------------------
# autonomy set
# --------------------------------------------------------------------------


def test_set_agent_autonomy_persists(toml_company):
    from agent_os.write_cmds import set_agent_autonomy

    _, toml = toml_company
    set_agent_autonomy(toml, "agent-001-maker", "high")

    reloaded = Config.from_toml(toml)
    assert reloaded.autonomy_agents.get("agent-001-maker") == "high"


def test_set_agent_autonomy_rejects_invalid_level(toml_company):
    from agent_os.write_cmds import set_agent_autonomy

    _, toml = toml_company
    with pytest.raises(ValueError, match="autonomy level"):
        set_agent_autonomy(toml, "agent-001-maker", "bogus")


# --------------------------------------------------------------------------
# schedule toggle
# --------------------------------------------------------------------------


def test_toggle_scheduler_off(toml_company):
    from agent_os.write_cmds import toggle_schedule

    _, toml = toml_company
    toggle_schedule(toml, "scheduler", False)

    reloaded = Config.from_toml(toml)
    assert reloaded.schedule_enabled is False


def test_toggle_scheduler_cycles(toml_company):
    from agent_os.write_cmds import toggle_schedule

    _, toml = toml_company
    toggle_schedule(toml, "cycles", False)

    reloaded = Config.from_toml(toml)
    assert reloaded.schedule_cycles_enabled is False


def test_toggle_schedule_rejects_unknown_kind(toml_company):
    from agent_os.write_cmds import toggle_schedule

    _, toml = toml_company
    with pytest.raises(ValueError, match="kind"):
        toggle_schedule(toml, "bogus-kind", True)


# --------------------------------------------------------------------------
# CLI wiring
# --------------------------------------------------------------------------


def test_cli_registers_budget_set():
    from agent_os.cli import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["budget-set", "--daily", "25"])
    assert args.command == "budget-set"
    assert args.daily == 25.0


def test_cli_registers_autonomy():
    from agent_os.cli import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["autonomy", "agent-001-maker", "high"])
    assert args.command == "autonomy"
    assert args.level == "high"


def test_cli_registers_schedule_toggle():
    from agent_os.cli import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["schedule-toggle", "cycles", "off"])
    assert args.command == "schedule-toggle"
    assert args.kind == "cycles"
    assert args.state == "off"
