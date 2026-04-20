"""Agent experience (AX) review — make errors clear, exit codes right, and
`--agent` filters actually do something. Tests written red-first as part of
a focused AX pass on the Phase 2 commands.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_os.config import Config


@pytest.fixture
def toml_company(tmp_path) -> tuple[Config, Path]:
    """Company with agent-os.toml on disk + loaded Config."""
    root = tmp_path / "company"
    root.mkdir()
    toml = root / "agent-os.toml"
    toml.write_text(
        '[company]\nname = "Test"\nroot = "."\n\n[budget]\ndaily_cap = 10.0\nweekly_cap = 50.0\nmonthly_cap = 200.0\n'
    )
    cfg = Config.from_toml(toml)
    return cfg, toml


def _register(cfg: Config, agent_id: str) -> None:
    cfg.registry_dir.mkdir(parents=True, exist_ok=True)
    (cfg.registry_dir / f"{agent_id}.md").write_text(f"---\nid: {agent_id}\n---\n")


# --------------------------------------------------------------------------
# Exit codes + error messages — agents must be able to detect failures
# --------------------------------------------------------------------------


def test_agent_show_missing_exits_nonzero(aios_config: Config, capsys):
    """`agent show <unknown>` should exit 1 so callers can detect the failure."""
    from agent_os.cli import cmd_agent
    from agent_os.config import Config as _Cfg
    from agent_os.config import configure

    args = type(
        "Args",
        (),
        {
            "agent_action": "show",
            "agent_id": "agent-does-not-exist",
            "format": "human",
            "root": str(aios_config.company_root),
            "config": None,
        },
    )()

    configure(aios_config)
    try:
        with pytest.raises(SystemExit) as exc_info:
            cmd_agent(args)
        assert exc_info.value.code == 1
    finally:
        configure(_Cfg())

    captured = capsys.readouterr()
    assert "not found" in (captured.out + captured.err).lower()


def test_tasks_show_missing_exits_nonzero_and_hints_plural(aios_config: Config, capsys):
    """`tasks show <unknown>` must exit 1 and hint `tasks list`, not `task list`."""
    from agent_os.cli import cmd_tasks
    from agent_os.config import Config as _Cfg
    from agent_os.config import configure

    args = type(
        "Args",
        (),
        {
            "tasks_action": "show",
            "task_id": "task-does-not-exist",
            "format": "human",
            "status": None,
            "agent": None,
            "root": str(aios_config.company_root),
            "config": None,
        },
    )()

    configure(aios_config)
    try:
        with pytest.raises(SystemExit) as exc_info:
            cmd_tasks(args)
        assert exc_info.value.code == 1
    finally:
        configure(_Cfg())

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    # Hint must point at the correct plural command.
    assert "agent-os tasks list" in combined
    # "agent-os task list" appearing would be the old typo (singular runner command).
    assert "agent-os task list" not in combined


def test_messages_inbox_without_agent_exits_nonzero(aios_config: Config, capsys):
    """`messages inbox` without an agent id must fail cleanly."""
    from agent_os.cli import cmd_messages
    from agent_os.config import Config as _Cfg
    from agent_os.config import configure

    args = type(
        "Args",
        (),
        {
            "channel": "inbox",
            "agent": None,
            "root": str(aios_config.company_root),
            "config": None,
        },
    )()

    configure(aios_config)
    try:
        with pytest.raises(SystemExit) as exc_info:
            cmd_messages(args)
        assert exc_info.value.code == 1
    finally:
        configure(_Cfg())

    captured = capsys.readouterr()
    assert "agent" in (captured.err + captured.out).lower()


def test_budget_set_no_args_errors(toml_company, capsys):
    """`budget-set` with nothing to set should fail, not silently 'succeed'."""
    from agent_os.cli import cmd_budget_set

    _, toml = toml_company
    args = type(
        "Args",
        (),
        {
            "daily": None,
            "weekly": None,
            "monthly": None,
            "root": str(toml.parent),
            "config": None,
        },
    )()

    with pytest.raises(SystemExit) as exc_info:
        cmd_budget_set(args)
    assert exc_info.value.code == 1

    captured = capsys.readouterr()
    assert "--daily" in captured.err or "--daily" in captured.out


def test_health_with_unknown_agent_errors(aios_config: Config, capsys):
    """`health --agent <unknown>` should say the agent isn't registered."""
    from agent_os.cli import cmd_health
    from agent_os.config import Config as _Cfg
    from agent_os.config import configure

    _register(aios_config, "agent-001-maker")

    args = type(
        "Args",
        (),
        {
            "format": "human",
            "agent": "agent-does-not-exist",
            "days": 7,
            "root": str(aios_config.company_root),
            "config": None,
        },
    )()

    configure(aios_config)
    try:
        with pytest.raises(SystemExit) as exc_info:
            cmd_health(args)
        assert exc_info.value.code == 1
    finally:
        configure(_Cfg())

    captured = capsys.readouterr()
    combined = captured.err + captured.out
    assert "not found" in combined.lower() or "not registered" in combined.lower()


# --------------------------------------------------------------------------
# briefing --agent actually filters (currently silently ignored)
# --------------------------------------------------------------------------


def test_briefing_agent_scope_filters_roster(aios_config: Config):
    """When --agent is supplied, only that agent should appear in the roster."""
    from agent_os.briefing import render_briefing

    _register(aios_config, "agent-001-maker")
    _register(aios_config, "agent-002-writer")

    output = render_briefing(aios_config, agent="agent-001-maker")
    assert "agent-001-maker" in output
    # The other agent should NOT appear in the scoped briefing.
    assert "agent-002-writer" not in output


def test_briefing_agent_unknown_errors_clearly(aios_config: Config, capsys):
    """`agent-os briefing --agent <unknown>` should fail with a clear error."""
    from agent_os.cli import cmd_briefing
    from agent_os.config import Config as _Cfg
    from agent_os.config import configure

    _register(aios_config, "agent-001-maker")

    args = type(
        "Args",
        (),
        {
            "depth": "short",
            "agent": "bogus-agent",
            "root": str(aios_config.company_root),
            "config": None,
        },
    )()

    configure(aios_config)
    try:
        with pytest.raises(SystemExit) as exc_info:
            cmd_briefing(args)
        assert exc_info.value.code == 1
    finally:
        configure(_Cfg())

    captured = capsys.readouterr()
    assert "not found" in (captured.err + captured.out).lower()


# --------------------------------------------------------------------------
# Missing TOML error should tell you how to fix it
# --------------------------------------------------------------------------


def test_schedule_toggle_missing_toml_hints_how_to_fix(tmp_path, capsys, monkeypatch):
    """When agent-os.toml can't be found, the error should suggest --root or cwd."""
    from agent_os.cli import cmd_schedule_toggle

    # cd somewhere that has NO agent-os.toml anywhere up the tree.
    monkeypatch.chdir(tmp_path)

    args = type(
        "Args",
        (),
        {"kind": "cycles", "state": "off", "root": None, "config": None},
    )()

    with pytest.raises(SystemExit) as exc_info:
        cmd_schedule_toggle(args)
    assert exc_info.value.code == 1

    err = capsys.readouterr().err + capsys.readouterr().out
    # Must say what went wrong AND hint at the fix.
    assert "agent-os.toml" in err
    assert "--root" in err or "cd " in err.lower()


# --------------------------------------------------------------------------
# Help-text / arg ergonomics — non-agent commands should NOT advertise
# --max-turns / --max-budget (noise that agents will trip on)
# --------------------------------------------------------------------------


def test_briefing_help_does_not_advertise_max_turns():
    """Briefing doesn't run an agent — max-turns/max-budget are irrelevant noise."""
    from agent_os.cli import _build_parser

    parser = _build_parser()
    # Parsing briefing without max-turns should succeed as before.
    parser.parse_args(["briefing"])
    # And passing --max-turns should be rejected (unrecognized option).
    with pytest.raises(SystemExit):
        parser.parse_args(["briefing", "--max-turns", "5"])


def test_cost_help_does_not_advertise_max_turns():
    from agent_os.cli import _build_parser

    parser = _build_parser()
    parser.parse_args(["cost"])
    with pytest.raises(SystemExit):
        parser.parse_args(["cost", "--max-turns", "5"])


def test_tasks_list_help_does_not_advertise_max_turns():
    from agent_os.cli import _build_parser

    parser = _build_parser()
    parser.parse_args(["tasks", "list"])
    with pytest.raises(SystemExit):
        parser.parse_args(["tasks", "list", "--max-turns", "5"])


def test_cycle_still_accepts_max_turns():
    """Agent-running commands MUST still accept max-turns/max-budget."""
    from agent_os.cli import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["cycle", "agent-001", "--max-turns", "5", "--max-budget", "2.5"])
    assert args.max_turns == 5
    assert args.max_budget == 2.5


# --------------------------------------------------------------------------
# Positional help — strategy topic / messages channel should have help=
# --------------------------------------------------------------------------


def test_strategy_topic_help_present(capsys):
    from agent_os.cli import _build_parser

    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["strategy", "--help"])
    out = capsys.readouterr().out
    # Must describe what `topic` is, not just list the choices.
    assert "topic" in out.lower()
    assert "drive" in out.lower() or "decision" in out.lower() or "proposal" in out.lower()


# --------------------------------------------------------------------------
# JSON mode for errors — when --format json and the command errors,
# an agent should still get parseable output where possible
# --------------------------------------------------------------------------


def test_health_json_with_unknown_agent_emits_error_json(aios_config: Config, capsys):
    """`health --format json --agent <unknown>` should still emit a parseable
    JSON error object rather than a free-text error mixed with stdout."""
    from agent_os.cli import cmd_health
    from agent_os.config import Config as _Cfg
    from agent_os.config import configure

    _register(aios_config, "agent-001-maker")

    args = type(
        "Args",
        (),
        {
            "format": "json",
            "agent": "bogus-agent",
            "days": 7,
            "root": str(aios_config.company_root),
            "config": None,
        },
    )()

    configure(aios_config)
    try:
        with pytest.raises(SystemExit):
            cmd_health(args)
    finally:
        configure(_Cfg())

    captured = capsys.readouterr()
    # Error must appear on stderr. stdout should be empty-or-valid-JSON.
    if captured.out.strip():
        # If anything was printed on stdout in JSON mode, it must be valid JSON.
        json.loads(captured.out)
    assert "not found" in captured.err.lower() or "not registered" in captured.err.lower()
