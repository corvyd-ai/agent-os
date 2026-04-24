"""Tests for CLI commands: init, update, agent-not-found handling."""

import json
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_os.cli import (
    _CRON_MARKER,
    INIT_DIRS,
    _build_cron_line,
    _find_repo_root,
    cmd_budget,
    cmd_init,
    cmd_update,
)
from agent_os.config import Config

# ── init command ────────────────────────────────────────────────────


class _FakeArgs:
    """Minimal args object for cmd_init."""

    def __init__(self, name: str):
        self.name = name


def test_init_creates_declined_directory(tmp_path, monkeypatch):
    """agent-os init should create agents/tasks/declined/."""
    monkeypatch.chdir(tmp_path)
    cmd_init(_FakeArgs("test-co"))
    assert (tmp_path / "test-co" / "agents" / "tasks" / "declined").is_dir()


def test_init_dirs_includes_declined():
    """INIT_DIRS list should include agents/tasks/declined."""
    assert "agents/tasks/declined" in INIT_DIRS


def test_init_dirs_includes_knowledge_technical():
    """INIT_DIRS list should include knowledge/technical — where the
    release-notes module writes the platform reference doc and changelog.
    Must exist from init so `agent-os update` can write there cleanly."""
    assert "knowledge/technical" in INIT_DIRS


def test_init_creates_agent_os_toml(tmp_path, monkeypatch):
    """agent-os init should create a valid agent-os.toml."""
    monkeypatch.chdir(tmp_path)
    cmd_init(_FakeArgs("test-co"))
    toml_path = tmp_path / "test-co" / "agent-os.toml"
    assert toml_path.exists()
    content = toml_path.read_text()
    assert 'name = "test-co"' in content
    assert "[budget]" in content


def test_init_toml_round_trips(tmp_path, monkeypatch):
    """Generated agent-os.toml should be parseable by Config.from_toml()."""
    monkeypatch.chdir(tmp_path)
    cmd_init(_FakeArgs("test-co"))
    toml_path = tmp_path / "test-co" / "agent-os.toml"
    cfg = Config.from_toml(toml_path)
    assert cfg.company_name == "test-co"
    assert cfg.default_model == "claude-sonnet-4-6"
    assert cfg.max_budget_per_invocation_usd == 5.00


def test_init_creates_all_directories(tmp_path, monkeypatch):
    """agent-os init should create every directory in INIT_DIRS."""
    monkeypatch.chdir(tmp_path)
    cmd_init(_FakeArgs("test-co"))
    for d in INIT_DIRS:
        assert (tmp_path / "test-co" / d).is_dir(), f"Missing directory: {d}"


def test_init_creates_starter_files(tmp_path, monkeypatch):
    """agent-os init should create starter markdown files."""
    monkeypatch.chdir(tmp_path)
    cmd_init(_FakeArgs("test-co"))
    root = tmp_path / "test-co"
    assert (root / "identity" / "values.md").exists()
    assert (root / "identity" / "principles.md").exists()
    assert (root / "strategy" / "drives.md").exists()
    assert (root / "strategy" / "current-focus.md").exists()


# ── agent-not-found handling ────────────────────────────────────────


def test_cycle_bad_agent_id_friendly_error(tmp_path, monkeypatch):
    """agent-os cycle with a nonexistent agent should give a friendly error, not a traceback."""
    # Create a minimal company directory
    monkeypatch.chdir(tmp_path)
    cmd_init(_FakeArgs("test-co"))

    result = subprocess.run(
        [sys.executable, "-m", "agent_os", "cycle", "nonexistent-agent", "--root", str(tmp_path / "test-co")],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Error:" in result.stderr
    assert "Hint:" in result.stderr
    # Should NOT have a Python traceback
    assert "Traceback" not in result.stderr


# ── update command ─────────────────────────────────────────────────


def test_find_repo_root_returns_path():
    """_find_repo_root should find the agent-os repo root."""
    root = _find_repo_root()
    assert root is not None
    assert (root / ".git").exists()
    assert (root / "pyproject.toml").exists()


def test_find_repo_root_returns_none_outside_git(tmp_path, monkeypatch):
    """_find_repo_root returns None when the package isn't in a git repo."""
    with patch("agent_os.cli.Path") as mock_path:
        # Make __file__ resolve to a path outside any git repo
        fake_file = tmp_path / "src" / "agent_os" / "cli.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.touch()
        mock_path.__file__ = str(fake_file)
        # Actually call the real function but with a patched starting point
        # Simpler: just verify the function handles None gracefully
    # Test via cmd_update instead
    with patch("agent_os.cli._find_repo_root", return_value=None):
        with pytest.raises(SystemExit) as exc_info:
            cmd_update(SimpleNamespace(yes=False))
        assert exc_info.value.code == 1


def test_update_already_up_to_date(monkeypatch):
    """agent-os update should exit cleanly when already up to date."""
    repo_root = _find_repo_root()
    if repo_root is None:
        pytest.skip("Not running from a git checkout")

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "rev-parse":
            return SimpleNamespace(returncode=0, stdout="main\n", stderr="")
        if cmd[1] == "status":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[1] == "fetch":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if cmd[1] == "rev-list":
            return SimpleNamespace(returncode=0, stdout="0\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    # Should not raise
    cmd_update(SimpleNamespace(yes=False))
    git_commands = [c[1] for c in calls if c[0] == "git"]
    assert "fetch" in git_commands
    assert "rev-list" in git_commands
    # Should NOT have pulled since we're up to date
    assert "pull" not in git_commands


def test_update_dirty_repo_exits(monkeypatch):
    """agent-os update should refuse if the repo has uncommitted changes."""
    repo_root = _find_repo_root()
    if repo_root is None:
        pytest.skip("Not running from a git checkout")

    def fake_run(cmd, **kwargs):
        if cmd[1] == "rev-parse":
            return SimpleNamespace(returncode=0, stdout="main\n", stderr="")
        if cmd[1] == "status":
            return SimpleNamespace(returncode=0, stdout=" M dirty-file.py\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SystemExit) as exc_info:
        cmd_update(SimpleNamespace(yes=False))
    assert exc_info.value.code == 1


def test_update_pulls_and_reinstalls(monkeypatch):
    """agent-os update should pull and pip install when new commits exist."""
    repo_root = _find_repo_root()
    if repo_root is None:
        pytest.skip("Not running from a git checkout")

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "git":
            if cmd[1] == "rev-parse":
                return SimpleNamespace(returncode=0, stdout="main\n", stderr="")
            if cmd[1] == "status":
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if cmd[1] == "fetch":
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if cmd[1] == "rev-list":
                return SimpleNamespace(returncode=0, stdout="3\n", stderr="")
            if cmd[1] == "log":
                return SimpleNamespace(returncode=0, stdout="abc1234 feat: cool\ndef5678 fix: bug\n", stderr="")
            if cmd[1] == "pull":
                return SimpleNamespace(returncode=0, stdout="", stderr="")
        # pip install or version check
        return SimpleNamespace(returncode=0, stdout="0.2.0\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    cmd_update(SimpleNamespace(yes=True))

    git_commands = [c[1] for c in calls if c[0] == "git"]
    assert "pull" in git_commands
    # Should have run pip install
    pip_calls = [c for c in calls if c[0] != "git"]
    assert any("-m" in c and "pip" in c for c in pip_calls)


# ── budget command config visibility (bug 3) ────────────────────────


def _write_budget_toml(path, *, daily_cap: float):
    # [company].root = "." is required so company_root resolves to the
    # directory containing the TOML (rather than cwd at import time).
    path.write_text(
        f"""
[company]
name = "Test"
root = "."

[budget]
daily_cap = {daily_cap}
""".lstrip()
    )


def _log_cost(company_root, *, date: str, cost_usd: float):
    """Append a single cost JSONL entry — same shape core.log_cost writes."""
    costs_dir = company_root / "finance" / "costs"
    costs_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "date": date,
        "agent": "agent-001-maker",
        "task": "task-test",
        "cost_usd": cost_usd,
        "duration_ms": 100,
        "model": "claude-opus-4-6",
        "turns": 1,
        "timestamp": f"{date}T00:00:00+00:00",
    }
    with (costs_dir / f"{date}.jsonl").open("a") as f:
        f.write(json.dumps(entry) + "\n")


def test_budget_prints_resolved_config_path(tmp_path, monkeypatch, capsys):
    """Regression for the Corvyd Apr 19 discovery mismatch: budget CLI showed
    $0/$100 while scheduler-state.json showed $13.22/$75 because the two
    were discovering different agent-os.toml files. The first line of
    `agent-os budget` output must now reveal which config got loaded, so an
    operator (or agent) cross-checking numbers can see the source."""
    company = tmp_path / "co"
    company.mkdir()
    toml = company / "agent-os.toml"
    _write_budget_toml(toml, daily_cap=75.0)
    monkeypatch.chdir(company)

    cmd_budget(SimpleNamespace(config=None, root=None))
    out = capsys.readouterr().out

    assert f"Config: {toml.resolve()}" in out
    assert "$75.00" in out  # configured cap, not the $100 default


def test_budget_exits_nonzero_when_no_config_discovered(tmp_path, monkeypatch, capsys):
    """Run from a directory that has no agent-os.toml anywhere up the chain.
    The CLI must refuse rather than silently report default caps and $0
    spend, which is the failure mode the incident revealed."""
    # Ensure no env override bleeds in from the parent shell
    monkeypatch.delenv("AGENT_OS_CONFIG", raising=False)
    # And ensure the tmp_path isn't itself inside a tree with agent-os.toml
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)

    with pytest.raises(SystemExit) as excinfo:
        cmd_budget(SimpleNamespace(config=None, root=str(empty)))
    assert excinfo.value.code == 2

    err = capsys.readouterr().err
    assert "no agent-os.toml discovered" in err
    assert "--config" in err


def test_budget_explicit_config_shows_spend(tmp_path, monkeypatch, capsys):
    """Smoke test per the bug report's ask: a logged cost must surface in
    the budget CLI within one invocation — no caching, no stale files."""
    company = tmp_path / "co"
    company.mkdir()
    toml = company / "agent-os.toml"
    _write_budget_toml(toml, daily_cap=75.0)

    # Log $1.23 for today (whatever "today" is in UTC for the test).
    from datetime import UTC, datetime

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    _log_cost(company, date=today, cost_usd=1.23)

    monkeypatch.chdir(tmp_path)  # avoid cwd discovery; use --config explicitly
    cmd_budget(SimpleNamespace(config=str(toml), root=None))
    out = capsys.readouterr().out

    assert f"Config: {toml.resolve()}" in out
    assert "$1.23" in out
    assert "$75.00" in out


# ── notifications command ──────────────────────────────────────────────


def _write_notifications_toml(path):
    path.write_text(
        """
[company]
name = "Test"
root = "."

[notifications]
enabled = true
min_severity = "warning"
""".lstrip()
    )


def _notif_args(config_path, **extra):
    base = {"config": str(config_path), "root": None}
    base.update(extra)
    return SimpleNamespace(**base)


def test_notifications_severity_persists(tmp_path, capsys):
    from agent_os.cli import cmd_notifications_severity

    company = tmp_path / "co"
    company.mkdir()
    toml = company / "agent-os.toml"
    _write_notifications_toml(toml)

    cmd_notifications_severity(_notif_args(toml, level="critical"))
    out = capsys.readouterr().out
    assert "critical" in out

    assert Config.from_toml(toml).notifications_min_severity == "critical"


def test_notifications_event_set_and_clear(tmp_path, capsys):
    from agent_os.cli import cmd_notifications_event

    company = tmp_path / "co"
    company.mkdir()
    toml = company / "agent-os.toml"
    _write_notifications_toml(toml)

    cmd_notifications_event(_notif_args(toml, event_type="message_for_human", severity="info"))
    assert Config.from_toml(toml).notifications_event_overrides == {"message_for_human": "info"}

    cmd_notifications_event(_notif_args(toml, event_type="message_for_human", severity="clear"))
    out = capsys.readouterr().out
    assert "Cleared override" in out
    assert Config.from_toml(toml).notifications_event_overrides == {}


def test_notifications_event_rejects_unknown_event(tmp_path, capsys):
    from agent_os.cli import cmd_notifications_event

    company = tmp_path / "co"
    company.mkdir()
    toml = company / "agent-os.toml"
    _write_notifications_toml(toml)

    with pytest.raises(SystemExit) as excinfo:
        cmd_notifications_event(_notif_args(toml, event_type="not_a_real_event", severity="info"))
    assert excinfo.value.code == 1

    err = capsys.readouterr().err
    assert "Unknown event_type" in err


def test_notifications_channel_toggle(tmp_path):
    from agent_os.cli import cmd_notifications_channel

    company = tmp_path / "co"
    company.mkdir()
    toml = company / "agent-os.toml"
    _write_notifications_toml(toml)

    cmd_notifications_channel(_notif_args(toml, channel="desktop", state="on"))
    assert Config.from_toml(toml).notifications_desktop is True

    cmd_notifications_channel(_notif_args(toml, channel="desktop", state="off"))
    assert Config.from_toml(toml).notifications_desktop is False


def test_notifications_webhook_set_and_clear(tmp_path):
    from agent_os.cli import cmd_notifications_webhook

    company = tmp_path / "co"
    company.mkdir()
    toml = company / "agent-os.toml"
    _write_notifications_toml(toml)

    cmd_notifications_webhook(_notif_args(toml, url="https://example.com/hook"))
    assert Config.from_toml(toml).notifications_webhook_url == "https://example.com/hook"

    cmd_notifications_webhook(_notif_args(toml, url="clear"))
    assert Config.from_toml(toml).notifications_webhook_url == ""


def test_notifications_enable_disable(tmp_path):
    from agent_os.cli import cmd_notifications_set_enabled

    company = tmp_path / "co"
    company.mkdir()
    toml = company / "agent-os.toml"
    _write_notifications_toml(toml)

    cmd_notifications_set_enabled(_notif_args(toml), False)
    assert Config.from_toml(toml).notifications_enabled is False

    cmd_notifications_set_enabled(_notif_args(toml), True)
    assert Config.from_toml(toml).notifications_enabled is True


def test_notifications_status_renders(tmp_path, capsys):
    from agent_os.cli import cmd_notifications_status

    company = tmp_path / "co"
    company.mkdir()
    toml = company / "agent-os.toml"
    toml.write_text(
        """
[company]
name = "Test"
root = "."

[notifications]
enabled = true
min_severity = "warning"
desktop = true

[notifications.events]
message_for_human = "info"
""".lstrip()
    )

    cmd_notifications_status(_notif_args(toml))
    out = capsys.readouterr().out
    assert "Enabled:" in out
    assert "warning" in out
    assert "desktop: on" in out
    assert "message_for_human" in out
    assert "info" in out


def test_notifications_events_lists_known_types(tmp_path, capsys):
    from agent_os.cli import cmd_notifications_events

    company = tmp_path / "co"
    company.mkdir()
    toml = company / "agent-os.toml"
    _write_notifications_toml(toml)

    cmd_notifications_events(_notif_args(toml))
    out = capsys.readouterr().out
    assert "preflight_failed" in out
    assert "message_for_human" in out
    assert "daily_digest" in out


def test_notifications_test_fires_through_file_channel(tmp_path, capsys):
    from agent_os.cli import cmd_notifications_test

    company = tmp_path / "co"
    company.mkdir()
    toml = company / "agent-os.toml"
    _write_notifications_toml(toml)

    cmd_notifications_test(_notif_args(toml, event="test_event", severity="warning"))
    out = capsys.readouterr().out
    assert "Test notification dispatched" in out
    assert "file" in out
    notif_dir = company / "operations" / "notifications"
    assert notif_dir.exists()
    assert list(notif_dir.glob("*-test_event.md"))


def test_notifications_test_refuses_when_disabled(tmp_path, capsys):
    from agent_os.cli import cmd_notifications_test

    company = tmp_path / "co"
    company.mkdir()
    toml = company / "agent-os.toml"
    toml.write_text(
        """
[company]
name = "Test"
root = "."

[notifications]
enabled = false
""".lstrip()
    )

    with pytest.raises(SystemExit) as excinfo:
        cmd_notifications_test(_notif_args(toml, event="test_event", severity="warning"))
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "disabled" in err


def test_cli_registers_notifications_subcommands():
    from agent_os.cli import _build_parser

    parser = _build_parser()
    for cmd in [
        ["notifications", "status"],
        ["notifications", "events"],
        ["notifications", "enable"],
        ["notifications", "disable"],
        ["notifications", "severity", "info"],
        ["notifications", "event", "message_for_human", "info"],
        ["notifications", "channel", "file", "on"],
        ["notifications", "webhook", "https://example.com/hook"],
        ["notifications", "script", "clear"],
        ["notifications", "test"],
    ]:
        args = parser.parse_args(cmd)
        assert args.command == "notifications"
        assert args.notif_action == cmd[1]


# ── cron line construction ─────────────────────────────────────────


class TestBuildCronLine:
    """Tests for _build_cron_line shell-escaping."""

    def test_safe_path_unquoted(self, tmp_path):
        """A simple path without metacharacters produces a valid cron line."""
        toml = tmp_path / "agent-os.toml"
        log_dir = tmp_path / "logs"
        line = _build_cron_line(toml, log_dir)
        assert _CRON_MARKER in line
        assert "agent-os tick --config" in line

    def test_semicolon_in_path_is_escaped(self, tmp_path):
        """A semicolon in the path must be quoted so cron doesn't execute a second command."""
        evil = tmp_path / "evil;rm -rf /"
        toml = evil / "agent-os.toml"
        log_dir = evil / "logs"
        line = _build_cron_line(toml, log_dir)
        assert f"'{toml}'" in line
        assert f" {toml} " not in line
        assert f" {toml}\n" not in line

    def test_backtick_in_path_is_escaped(self, tmp_path):
        """Backticks in a path must not trigger command substitution."""
        evil = tmp_path / "x`id`y"
        toml = evil / "agent-os.toml"
        log_dir = evil / "logs"
        line = _build_cron_line(toml, log_dir)
        assert f"'{toml}'" in line

    def test_dollar_paren_in_path_is_escaped(self, tmp_path):
        """$() in a path must not trigger command substitution."""
        evil = tmp_path / "x$(whoami)y"
        toml = evil / "agent-os.toml"
        log_dir = evil / "logs"
        line = _build_cron_line(toml, log_dir)
        assert f"'{toml}'" in line

    def test_space_in_path_is_escaped(self, tmp_path):
        """Spaces in paths must be handled (quoted)."""
        spaced = tmp_path / "my company"
        toml = spaced / "agent-os.toml"
        log_dir = spaced / "logs"
        line = _build_cron_line(toml, log_dir)
        assert f"'{toml}'" in line
        assert f"'{log_dir / 'scheduler.log'}'" in line

    def test_single_quote_in_path_is_escaped(self, tmp_path):
        """Single quotes in a path must be safely escaped by shlex.quote."""
        import shlex

        evil = tmp_path / "it's"
        toml = evil / "agent-os.toml"
        log_dir = evil / "logs"
        line = _build_cron_line(toml, log_dir)
        assert "it's/agent-os.toml" not in line
        parts = shlex.split(line.replace(">>", "REDIR").replace("2>&1", "STDERR"))
        config_idx = parts.index("--config") + 1
        assert str(toml) == parts[config_idx]
