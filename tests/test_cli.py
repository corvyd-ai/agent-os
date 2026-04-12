"""Tests for CLI commands: init, agent-not-found handling."""

import subprocess
import sys

from agent_os.cli import INIT_DIRS, cmd_init
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
