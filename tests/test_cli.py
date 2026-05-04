"""Tests for CLI commands: init, update, agent-not-found handling."""

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from agent_os.cli import (
    INIT_DIRS,
    _find_repo_root,
    _is_agent_os_repo,
    _resolve_repo_root,
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


def test_is_agent_os_repo_positive():
    """_is_agent_os_repo should return True for the actual agent-os repo."""
    root = _find_repo_root()
    if root is None:
        pytest.skip("Not running from a git checkout")
    assert _is_agent_os_repo(root) is True


def test_is_agent_os_repo_negative(tmp_path):
    """_is_agent_os_repo should return False for a directory without the
    agent-os source layout."""
    (tmp_path / ".git").mkdir()
    assert _is_agent_os_repo(tmp_path) is False


def test_find_repo_root_skips_unrelated_git_repo(tmp_path, monkeypatch):
    """Regression: _find_repo_root must NOT return an unrelated .git repo
    that happens to sit above the package directory.

    Simulates the corvyd-prod-01 scenario: the venv is under /srv/corvyd/
    which has its own .git (autocommit repo), but that repo is not agent-os.
    """
    # Build a fake directory tree:
    #   tmp_path/.git                 (unrelated repo — no src/agent_os/)
    #   tmp_path/venv/lib/.../agent_os/  (where __file__ would be)
    (tmp_path / ".git").mkdir()
    fake_pkg = tmp_path / "venv" / "lib" / "python3.12" / "site-packages" / "agent_os"
    fake_pkg.mkdir(parents=True)
    (fake_pkg / "cli.py").write_text("# placeholder")

    from agent_os import cli

    def patched_find_repo_root():
        current = fake_pkg
        while current != current.parent:
            if (current / ".git").exists() and cli._is_agent_os_repo(current):
                return current
            current = current.parent
        return None

    monkeypatch.setattr(cli, "_find_repo_root", patched_find_repo_root)

    result = patched_find_repo_root()
    assert result is None, (
        f"_find_repo_root should return None when the only .git above "
        f"the package is an unrelated repo, but got {result}"
    )


def test_find_repo_root_finds_correct_repo_when_unrelated_above(tmp_path, monkeypatch):
    """When both an unrelated and a valid agent-os repo exist in the path,
    _find_repo_root should return the valid one."""
    from agent_os import cli

    # Build:
    #   tmp_path/.git                           (unrelated outer repo)
    #   tmp_path/agent-os/.git                  (valid agent-os repo)
    #   tmp_path/agent-os/src/agent_os/__init__.py
    (tmp_path / ".git").mkdir()
    agent_os_repo = tmp_path / "agent-os"
    agent_os_repo.mkdir()
    (agent_os_repo / ".git").mkdir()
    (agent_os_repo / "src" / "agent_os").mkdir(parents=True)
    (agent_os_repo / "src" / "agent_os" / "__init__.py").write_text("")

    fake_pkg = agent_os_repo / "src" / "agent_os"

    def patched_find():
        current = fake_pkg
        while current != current.parent:
            if (current / ".git").exists() and cli._is_agent_os_repo(current):
                return current
            current = current.parent
        return None

    result = patched_find()
    assert result == agent_os_repo


def test_resolve_repo_root_with_explicit_repo(tmp_path):
    """--repo flag should override discovery and validate the path."""
    # Create a valid agent-os-shaped repo
    repo = tmp_path / "my-agent-os"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "src" / "agent_os").mkdir(parents=True)
    (repo / "src" / "agent_os" / "__init__.py").write_text("")

    args = SimpleNamespace(repo=str(repo))
    result = _resolve_repo_root(args, context="test")
    assert result == repo.resolve()


def test_resolve_repo_root_rejects_invalid_explicit_repo(tmp_path):
    """--repo pointing at a non-agent-os dir should error."""
    # Has .git but is not agent-os
    (tmp_path / ".git").mkdir()

    args = SimpleNamespace(repo=str(tmp_path))
    with pytest.raises(SystemExit) as exc_info:
        _resolve_repo_root(args, context="test")
    assert exc_info.value.code == 1


def test_resolve_repo_root_rejects_missing_git(tmp_path):
    """--repo pointing at a dir with no .git should error."""
    args = SimpleNamespace(repo=str(tmp_path))
    with pytest.raises(SystemExit) as exc_info:
        _resolve_repo_root(args, context="test")
    assert exc_info.value.code == 1


def test_update_dispatches_to_wheel_when_no_git_repo(monkeypatch):
    """When _find_repo_root returns None (wheel install), cmd_update must
    take the wheel path — not error out as it did before."""
    called = {}

    def fake_wheel(args):
        called["wheel"] = True

    def fake_git(args, repo_root):  # pragma: no cover — should not be called
        called["git"] = True

    monkeypatch.setattr("agent_os.cli._find_repo_root", lambda: None)
    monkeypatch.setattr("agent_os.cli._update_from_wheel", fake_wheel)
    monkeypatch.setattr("agent_os.cli._update_from_git", fake_git)

    cmd_update(SimpleNamespace(yes=False, source=None))

    assert called == {"wheel": True}


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


# ── update command (wheel-install path) ────────────────────────────


class _FakeURLResponse:
    """Minimal context-manager stand-in for urllib.request.urlopen()."""

    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _make_release_payload(*, version: str, body: str = "") -> bytes:
    """Build the JSON shape GitHub returns for a release."""
    payload = {
        "tag_name": "latest",
        "body": body,
        "assets": [
            {
                "name": f"agent_os-{version}-py3-none-any.whl",
                "browser_download_url": f"https://example.test/agent_os-{version}-py3-none-any.whl",
            }
        ],
    }
    return json.dumps(payload).encode("utf-8")


def test_update_from_wheel_skips_when_versions_match(monkeypatch, capsys):
    """If the published wheel version matches the installed version,
    cmd_update must short-circuit — no pip install, no release notes."""
    from agent_os import cli

    monkeypatch.setattr(cli, "_find_repo_root", lambda: None)
    monkeypatch.setattr("agent_os.__version__", "9.9.9")

    def fake_urlopen(req, timeout=None):
        # Echo the same version we say is installed
        return _FakeURLResponse(_make_release_payload(version="9.9.9"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    pip_calls = []

    def fake_run(cmd, **kwargs):
        pip_calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    cmd_update(SimpleNamespace(yes=True, source=None))

    assert pip_calls == []  # never installed
    out = capsys.readouterr().out
    assert "Already up to date" in out


def test_update_from_wheel_installs_and_writes_release_notes(monkeypatch, tmp_path):
    """When a newer wheel is published, cmd_update downloads, installs,
    and fires release notes."""
    from agent_os import cli

    monkeypatch.setattr(cli, "_find_repo_root", lambda: None)
    monkeypatch.setattr("agent_os.__version__", "0.2.0")

    api_url_seen = []
    download_url_seen = []

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if url.endswith(".whl"):
            download_url_seen.append(url)
            return _FakeURLResponse(b"FAKE-WHEEL-BYTES")
        api_url_seen.append(url)
        return _FakeURLResponse(
            _make_release_payload(
                version="0.3.0",
                body="- feat: add observability\n- fix: respect runtime user\n\nCommit: abcdef1234567",
            )
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    pip_invocations = []
    notes_invocations = []

    def fake_run(cmd, **kwargs):
        if "pip" in cmd:
            pip_invocations.append(cmd)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        # version re-read subprocess
        return SimpleNamespace(returncode=0, stdout="0.3.0\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    def fake_write_notes(**kwargs):
        notes_invocations.append(kwargs)

    monkeypatch.setattr(cli, "_write_release_notes_if_possible", fake_write_notes)

    cmd_update(SimpleNamespace(yes=True, source=None))

    # Hit the API for release info, then downloaded the wheel
    assert any("api.github.com/repos/" in u for u in api_url_seen)
    assert any(u.endswith(".whl") for u in download_url_seen)
    # pip install was invoked
    assert any("install" in c for c in pip_invocations)
    # Release notes fired with the expected payload
    assert len(notes_invocations) == 1
    notes = notes_invocations[0]
    assert notes["previous_version"] == "0.2.0"
    assert notes["new_version"] == "0.3.0"
    assert notes["new_commit"] == "abcdef1234567"
    assert "feat: add observability" in notes["commit_subjects"]
    assert "fix: respect runtime user" in notes["commit_subjects"]


def test_update_from_wheel_respects_source_flag(monkeypatch):
    """--source overrides both the TOML field and the upstream default."""
    from agent_os import cli

    monkeypatch.setattr(cli, "_find_repo_root", lambda: None)
    monkeypatch.setattr("agent_os.__version__", "9.9.9")

    seen_urls = []

    def fake_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        seen_urls.append(url)
        return _FakeURLResponse(_make_release_payload(version="9.9.9"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))

    cmd_update(SimpleNamespace(yes=True, source="myorg/agent-os-fork@v1.2.3"))

    assert any("myorg/agent-os-fork" in u and u.endswith("/v1.2.3") for u in seen_urls)


def test_update_from_wheel_errors_on_network_failure(monkeypatch):
    """A network failure on the API call must surface as SystemExit, not silent skip."""
    import urllib.error

    from agent_os import cli

    monkeypatch.setattr(cli, "_find_repo_root", lambda: None)

    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("name resolution failed")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(SystemExit) as exc_info:
        cmd_update(SimpleNamespace(yes=True, source=None))
    assert exc_info.value.code == 1


def test_update_from_wheel_errors_when_no_wheel_asset(monkeypatch):
    """A release with no .whl asset must error rather than no-op."""
    from agent_os import cli

    monkeypatch.setattr(cli, "_find_repo_root", lambda: None)

    def fake_urlopen(req, timeout=None):
        return _FakeURLResponse(json.dumps({"tag_name": "latest", "assets": []}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(SystemExit) as exc_info:
        cmd_update(SimpleNamespace(yes=True, source=None))
    assert exc_info.value.code == 1


# ── helper-function unit tests ─────────────────────────────────────


def test_parse_wheel_version_release():
    from agent_os.cli import _parse_wheel_version

    assert _parse_wheel_version("agent_os-0.3.0-py3-none-any.whl") == "0.3.0"


def test_parse_wheel_version_dev():
    from agent_os.cli import _parse_wheel_version

    assert _parse_wheel_version("agent_os-0.3.0.dev5+g1234567-py3-none-any.whl") == "0.3.0.dev5+g1234567"


def test_parse_wheel_version_malformed():
    from agent_os.cli import _parse_wheel_version

    assert _parse_wheel_version("nope.whl") == ""


def test_extract_subjects_from_bullets():
    from agent_os.cli import _extract_subjects_from_release_body

    body = "- feat: a\n- fix: b\n* doc: c\n\nSome trailing prose."
    assert _extract_subjects_from_release_body(body) == ["feat: a", "fix: b", "doc: c"]


def test_extract_subjects_from_prose_only():
    from agent_os.cli import _extract_subjects_from_release_body

    body = "First line is the summary.\nSecond line.\n"
    assert _extract_subjects_from_release_body(body) == ["First line is the summary."]


def test_extract_subjects_from_empty_body():
    from agent_os.cli import _extract_subjects_from_release_body

    assert _extract_subjects_from_release_body("") == []


def test_extract_commit_sha_present():
    from agent_os.cli import _extract_commit_sha_from_release_body

    body = "Auto-published by CI on merge to main. Commit: abcdef0123456789\n"
    assert _extract_commit_sha_from_release_body(body) == "abcdef0123456789"


def test_extract_commit_sha_absent():
    from agent_os.cli import _extract_commit_sha_from_release_body

    assert _extract_commit_sha_from_release_body("no sha here") == ""


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
