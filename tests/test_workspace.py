"""Tests for agent_os.workspace — git worktree lifecycle for the agentic SDLC."""

import subprocess
from pathlib import Path

import pytest

from agent_os.config import Config
from agent_os.workspace import (
    cleanup_workspace,
    commit_workspace,
    create_workspace,
    get_workspace,
    has_uncommitted_changes,
    push_workspace,
    salvage_commit,
    setup_workspace,
    validate_workspace,
)


@pytest.fixture
def git_repo(tmp_path):
    """Create a minimal git repo with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "checkout", "-b", "main"], cwd=str(repo), capture_output=True, check=True)
    # Configure git identity for commits
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), capture_output=True, check=True)
    # Initial commit (git worktree requires at least one commit)
    (repo / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(repo), capture_output=True, check=True)
    return repo


@pytest.fixture
def project_config(git_repo, tmp_path):
    """Config with project enabled, pointing at the git_repo."""
    company_root = git_repo  # Company root IS the repo
    # Build the agent-os directory tree
    (company_root / "agents" / "tasks" / "queued").mkdir(parents=True)
    (company_root / "agents" / "tasks" / "in-progress").mkdir(parents=True)
    (company_root / "agents" / "tasks" / "done").mkdir(parents=True)
    (company_root / "agents" / "tasks" / "failed").mkdir(parents=True)
    (company_root / "agents" / "tasks" / "backlog").mkdir(parents=True)
    (company_root / "agents" / "tasks" / "declined").mkdir(parents=True)
    (company_root / "agents" / "tasks" / "in-review").mkdir(parents=True)
    return Config(
        company_root=company_root,
        project_repo_path=".",
        project_default_branch="main",
        project_push=False,  # No remote in tests
        project_validate_commands=["true"],  # Always passes
        project_worktrees_dir=str(tmp_path / "worktrees"),
    )


# ── create_workspace ─────────────────────────────────────────────────


class TestCreateWorkspace:
    def test_creates_worktree_and_branch(self, project_config):
        ws = create_workspace("task-2026-0412-001", config=project_config)
        assert ws.worktree_path.exists()
        assert ws.branch == "agent/task-2026-0412-001"
        # Verify git branch exists
        result = subprocess.run(
            ["git", "branch", "--list", ws.branch],
            cwd=str(project_config.repo_root),
            capture_output=True,
            text=True,
        )
        assert "agent/task-2026-0412-001" in result.stdout
        cleanup_workspace(ws, delete_branch=True, config=project_config)

    def test_worktree_has_repo_contents(self, project_config):
        ws = create_workspace("task-2026-0412-002", config=project_config)
        assert (ws.worktree_path / "README.md").exists()
        cleanup_workspace(ws, delete_branch=True, config=project_config)

    def test_code_dir_matches_worktree_when_dot(self, project_config):
        ws = create_workspace("task-2026-0412-003", config=project_config)
        assert ws.code_dir == ws.worktree_path
        cleanup_workspace(ws, delete_branch=True, config=project_config)

    def test_code_dir_with_subdir(self, git_repo, tmp_path):
        # Create a subdirectory in the repo
        (git_repo / "products" / "myapp").mkdir(parents=True)
        (git_repo / "products" / "myapp" / "index.js").write_text("console.log('hello')")
        subprocess.run(["git", "add", "-A"], cwd=str(git_repo), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "Add myapp"], cwd=str(git_repo), capture_output=True, check=True)

        cfg = Config(
            company_root=git_repo,
            project_code_dir="products/myapp",
            project_validate_commands=["true"],
            project_worktrees_dir=str(tmp_path / "worktrees"),
        )
        ws = create_workspace("task-sub-001", config=cfg)
        assert ws.code_dir == ws.worktree_path / "products" / "myapp"
        assert (ws.code_dir / "index.js").exists()
        cleanup_workspace(ws, delete_branch=True, config=cfg)

    def test_cleans_up_stale_worktree(self, project_config):
        # Create first workspace
        ws1 = create_workspace("task-stale-001", config=project_config)
        assert ws1.worktree_path.exists()
        # Create again with same ID — should clean up and recreate
        ws2 = create_workspace("task-stale-001", config=project_config)
        assert ws2.worktree_path.exists()
        cleanup_workspace(ws2, delete_branch=True, config=project_config)


# ── setup_workspace ──────────────────────────────────────────────────


class TestSetupWorkspace:
    def test_runs_commands_successfully(self, git_repo, tmp_path):
        cfg = Config(
            company_root=git_repo,
            project_setup_commands=["echo hello", "echo world"],
            project_validate_commands=["true"],
            project_worktrees_dir=str(tmp_path / "worktrees"),
        )
        ws = create_workspace("task-setup-001", config=cfg)
        ok, output = setup_workspace(ws, config=cfg)
        assert ok is True
        assert "hello" in output
        assert "world" in output
        cleanup_workspace(ws, delete_branch=True, config=cfg)

    def test_fails_on_bad_command(self, git_repo, tmp_path):
        cfg = Config(
            company_root=git_repo,
            project_setup_commands=["true", "false", "echo unreachable"],
            project_validate_commands=["true"],
            project_worktrees_dir=str(tmp_path / "worktrees"),
        )
        ws = create_workspace("task-setup-002", config=cfg)
        ok, output = setup_workspace(ws, config=cfg)
        assert ok is False
        assert "unreachable" not in output  # Stops after failure
        cleanup_workspace(ws, delete_branch=True, config=cfg)

    def test_no_setup_commands_is_ok(self, project_config):
        cfg = Config(
            company_root=project_config.company_root,
            project_setup_commands=[],
            project_validate_commands=["true"],
            project_worktrees_dir=str(project_config.worktrees_root),
        )
        ws = create_workspace("task-setup-003", config=cfg)
        ok, output = setup_workspace(ws, config=cfg)
        assert ok is True
        assert output == ""
        cleanup_workspace(ws, delete_branch=True, config=cfg)


# ── validate_workspace ───────────────────────────────────────────────


class TestValidateWorkspace:
    def test_passes_when_all_commands_succeed(self, project_config):
        ws = create_workspace("task-val-001", config=project_config)
        ok, _output = validate_workspace(ws, config=project_config)
        assert ok is True
        cleanup_workspace(ws, delete_branch=True, config=project_config)

    def test_fails_when_command_fails(self, git_repo, tmp_path):
        cfg = Config(
            company_root=git_repo,
            project_validate_commands=["true", "false"],
            project_worktrees_dir=str(tmp_path / "worktrees"),
        )
        ws = create_workspace("task-val-002", config=cfg)
        ok, _output = validate_workspace(ws, config=cfg)
        assert ok is False
        cleanup_workspace(ws, delete_branch=True, config=cfg)

    def test_no_validate_commands_is_ok(self, git_repo, tmp_path):
        cfg = Config(
            company_root=git_repo,
            project_validate_commands=[],
            project_setup_commands=["true"],  # Need something for project_enabled
            project_worktrees_dir=str(tmp_path / "worktrees"),
        )
        ws = create_workspace("task-val-003", config=cfg)
        ok, output = validate_workspace(ws, config=cfg)
        assert ok is True
        assert output == ""
        cleanup_workspace(ws, delete_branch=True, config=cfg)


# ── commit_workspace ─────────────────────────────────────────────────


class TestCommitWorkspace:
    def test_commits_changes(self, project_config):
        ws = create_workspace("task-commit-001", config=project_config)
        # Make a change in the worktree
        (ws.worktree_path / "new_file.py").write_text("print('hello')\n")

        meta = {"id": "task-commit-001", "title": "Add hello script", "priority": "high"}
        sha = commit_workspace(ws, meta, "agent-001-builder", config=project_config)

        assert sha is not None
        assert len(sha) == 40  # Full SHA

        # Verify commit message
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=str(ws.worktree_path),
            capture_output=True,
            text=True,
        )
        assert "[task-commit-001] Add hello script" in result.stdout
        cleanup_workspace(ws, delete_branch=True, config=project_config)

    def test_returns_none_when_no_changes(self, project_config):
        ws = create_workspace("task-commit-002", config=project_config)
        meta = {"id": "task-commit-002", "title": "No-op task"}
        sha = commit_workspace(ws, meta, "agent-001", config=project_config)
        assert sha is None
        cleanup_workspace(ws, delete_branch=True, config=project_config)

    def test_commit_message_includes_metadata(self, project_config):
        ws = create_workspace("task-commit-003", config=project_config)
        (ws.worktree_path / "file.txt").write_text("content")

        meta = {"id": "task-commit-003", "title": "Build feature", "priority": "critical"}
        commit_workspace(ws, meta, "agent-002-builder", config=project_config)

        result = subprocess.run(
            ["git", "log", "-1", "--format=%B"],
            cwd=str(ws.worktree_path),
            capture_output=True,
            text=True,
        )
        body = result.stdout
        assert "Agent: agent-002-builder" in body
        assert "Priority: critical" in body
        cleanup_workspace(ws, delete_branch=True, config=project_config)


# ── commit identity injection (bug 1: Corvyd Apr 19 incident) ────────


@pytest.fixture
def unidentified_git_repo(tmp_path, monkeypatch):
    """A git repo with NO user.email / user.name anywhere (global, system, or
    local). Simulates a fresh runtime (e.g. the Hetzner `corvyd` account)
    where `git commit` would fail with 'Author identity unknown' unless the
    workspace provides inline `-c user.email=... -c user.name=...`.
    """
    # Isolate git from the host's global config for the duration of the test.
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    monkeypatch.setenv("HOME", str(isolated_home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(isolated_home / "nonexistent-gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(isolated_home / "nonexistent-systemconfig"))
    # Also clear any env-var identity the parent shell may have had set.
    for var in ("GIT_AUTHOR_EMAIL", "GIT_AUTHOR_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_NAME"):
        monkeypatch.delenv(var, raising=False)

    repo = tmp_path / "repo"
    repo.mkdir()
    # Bootstrap with a temporary local identity so the initial commit exists,
    # then scrub it — subsequent commits should fail without our inline fix.
    subprocess.run(["git", "init", "-b", "main"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "init@test"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Init"], cwd=str(repo), capture_output=True, check=True)
    (repo / "README.md").write_text("# Test\n")
    subprocess.run(["git", "add", "-A"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "Initial"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "config", "--unset", "user.email"], cwd=str(repo), capture_output=True, check=True)
    subprocess.run(["git", "config", "--unset", "user.name"], cwd=str(repo), capture_output=True, check=True)
    return repo


def _tree(company_root):
    for sub in ("queued", "in-progress", "done", "failed", "backlog", "declined", "in-review"):
        (company_root / "agents" / "tasks" / sub).mkdir(parents=True, exist_ok=True)


def test_commit_fails_without_identity_config(unidentified_git_repo, tmp_path):
    """Baseline: when nothing sets a git identity, commit_workspace still
    fails. This pins the failure mode from the incident so a regression in
    the fallback path is visible."""
    from agent_os.workspace import WorkspaceError

    _tree(unidentified_git_repo)
    cfg = Config(
        company_root=unidentified_git_repo,
        project_repo_path=".",
        project_default_branch="main",
        project_push=False,
        project_validate_commands=["true"],
        project_worktrees_dir=str(tmp_path / "worktrees"),
    )
    ws = create_workspace("task-identity-001", config=cfg)
    (ws.worktree_path / "x.txt").write_text("hi")

    with pytest.raises(WorkspaceError, match=r"identity|author"):
        commit_workspace(ws, {"id": "task-identity-001", "title": "t"}, "agent-001", config=cfg)
    cleanup_workspace(ws, delete_branch=True, config=cfg)


def test_commit_succeeds_with_project_level_identity(unidentified_git_repo, tmp_path):
    """commit_workspace must succeed on a runtime with no git identity set,
    as long as agent-os.toml provides one. Regression for the Corvyd
    Apr 19 incident."""
    _tree(unidentified_git_repo)
    cfg = Config(
        company_root=unidentified_git_repo,
        project_repo_path=".",
        project_default_branch="main",
        project_push=False,
        project_validate_commands=["true"],
        project_worktrees_dir=str(tmp_path / "worktrees"),
        project_commit_author_email="agent-os@example.com",
        project_commit_author_name="Agent OS",
    )
    ws = create_workspace("task-identity-002", config=cfg)
    (ws.worktree_path / "x.txt").write_text("hi")

    sha = commit_workspace(ws, {"id": "task-identity-002", "title": "t"}, "agent-001", config=cfg)
    assert sha is not None

    result = subprocess.run(
        ["git", "log", "-1", "--format=%an <%ae>"],
        cwd=str(ws.worktree_path),
        capture_output=True,
        text=True,
    )
    assert "Agent OS <agent-os@example.com>" in result.stdout
    cleanup_workspace(ws, delete_branch=True, config=cfg)


def test_per_agent_identity_override_wins(unidentified_git_repo, tmp_path):
    """Per-agent override lets commit history attribute work to the specific
    agent even when a project-wide default exists."""
    _tree(unidentified_git_repo)
    cfg = Config(
        company_root=unidentified_git_repo,
        project_repo_path=".",
        project_default_branch="main",
        project_push=False,
        project_validate_commands=["true"],
        project_worktrees_dir=str(tmp_path / "worktrees"),
        project_commit_author_email="default@example.com",
        project_commit_author_name="Default",
        project_agent_commit_authors={
            "agent-002-maker": {"email": "maker@example.com", "name": "The Maker"},
        },
    )
    ws = create_workspace("task-identity-003", config=cfg)
    (ws.worktree_path / "x.txt").write_text("hi")

    commit_workspace(ws, {"id": "task-identity-003", "title": "t"}, "agent-002-maker", config=cfg)

    result = subprocess.run(
        ["git", "log", "-1", "--format=%an <%ae>"],
        cwd=str(ws.worktree_path),
        capture_output=True,
        text=True,
    )
    assert "The Maker <maker@example.com>" in result.stdout
    cleanup_workspace(ws, delete_branch=True, config=cfg)


def test_identity_config_parsed_from_toml(tmp_path):
    """[project.commit] section in agent-os.toml populates the Config fields."""
    toml = tmp_path / "agent-os.toml"
    toml.write_text(
        """
[company]
name = "Test"

[project.commit]
author_email = "bot@example.com"
author_name = "Bot"

[project.commit.agent_authors.agent-001-maker]
email = "maker@example.com"
name = "Maker"
"""
    )
    cfg = Config.from_toml(toml)
    assert cfg.project_commit_author_email == "bot@example.com"
    assert cfg.project_commit_author_name == "Bot"
    assert cfg.project_agent_commit_authors == {
        "agent-001-maker": {"email": "maker@example.com", "name": "Maker"},
    }


# ── has_uncommitted_changes ──────────────────────────────────────────


class TestHasUncommittedChanges:
    def test_false_on_clean_worktree(self, project_config):
        ws = create_workspace("task-hu-001", config=project_config)
        assert has_uncommitted_changes(ws) is False
        cleanup_workspace(ws, delete_branch=True, config=project_config)

    def test_true_for_new_file(self, project_config):
        ws = create_workspace("task-hu-002", config=project_config)
        (ws.worktree_path / "new.txt").write_text("hello")
        assert has_uncommitted_changes(ws) is True
        cleanup_workspace(ws, delete_branch=True, config=project_config)

    def test_true_for_modified_file(self, project_config):
        ws = create_workspace("task-hu-003", config=project_config)
        (ws.worktree_path / "README.md").write_text("# Modified\n")
        assert has_uncommitted_changes(ws) is True
        cleanup_workspace(ws, delete_branch=True, config=project_config)

    def test_false_after_commit(self, project_config):
        ws = create_workspace("task-hu-004", config=project_config)
        (ws.worktree_path / "x.txt").write_text("x")
        commit_workspace(ws, {"id": "task-hu-004", "title": "t"}, "agent-001", config=project_config)
        assert has_uncommitted_changes(ws) is False
        cleanup_workspace(ws, delete_branch=True, config=project_config)


# ── salvage_commit ───────────────────────────────────────────────────


class TestSalvageCommit:
    def test_returns_none_on_clean_worktree(self, project_config):
        ws = create_workspace("task-sc-001", config=project_config)
        sha = salvage_commit(
            ws,
            {"id": "task-sc-001", "title": "Nothing to save"},
            "agent-001",
            "validation failed",
            config=project_config,
        )
        assert sha is None
        cleanup_workspace(ws, delete_branch=True, config=project_config)

    def test_commits_uncommitted_changes(self, project_config):
        ws = create_workspace("task-sc-002", config=project_config)
        (ws.worktree_path / "partial.py").write_text("def half_done():\n    pass\n")

        sha = salvage_commit(
            ws,
            {"id": "task-sc-002", "title": "Half-finished feature"},
            "agent-007-builder",
            "SDK timeout after 8 min",
            config=project_config,
        )
        assert sha is not None
        assert len(sha) == 40

        # Verify message is flagged as salvage and includes the reason.
        log_result = subprocess.run(
            ["git", "log", "-1", "--format=%B"],
            cwd=str(ws.worktree_path),
            capture_output=True,
            text=True,
        )
        body = log_result.stdout
        assert "SALVAGE" in body
        assert "task-sc-002" in body
        assert "SDK timeout after 8 min" in body
        assert "agent-007-builder" in body

        # And no uncommitted changes remain.
        assert has_uncommitted_changes(ws) is False
        cleanup_workspace(ws, delete_branch=True, config=project_config)

    def test_includes_untracked_files(self, project_config):
        """Salvage must stage untracked files too — agents often produce
        brand-new files, not just edits, and losing them is the whole thing
        we're trying to prevent."""
        ws = create_workspace("task-sc-003", config=project_config)
        (ws.worktree_path / "new_module.py").write_text("# new\n")

        sha = salvage_commit(
            ws,
            {"id": "task-sc-003", "title": "Add module"},
            "agent-001",
            "agent error",
            config=project_config,
        )
        assert sha is not None

        ls_result = subprocess.run(
            ["git", "ls-files"],
            cwd=str(ws.worktree_path),
            capture_output=True,
            text=True,
        )
        assert "new_module.py" in ls_result.stdout
        cleanup_workspace(ws, delete_branch=True, config=project_config)

    def test_returns_none_when_identity_missing(self, unidentified_git_repo, tmp_path):
        """Salvage swallows commit failures so exception handlers can decide
        how to preserve work instead of double-failing on a missing git
        identity. The runner then falls back to leaving the worktree on
        disk."""
        _tree(unidentified_git_repo)
        cfg = Config(
            company_root=unidentified_git_repo,
            project_repo_path=".",
            project_default_branch="main",
            project_push=False,
            project_validate_commands=["true"],
            project_worktrees_dir=str(tmp_path / "worktrees"),
        )
        ws = create_workspace("task-sc-004", config=cfg)
        (ws.worktree_path / "x.txt").write_text("x")

        sha = salvage_commit(
            ws,
            {"id": "task-sc-004", "title": "t"},
            "agent-001",
            "SDK error",
            config=cfg,
        )
        assert sha is None
        # Work should still be present in the worktree (not deleted).
        assert (ws.worktree_path / "x.txt").exists()
        cleanup_workspace(ws, delete_branch=True, config=cfg)

    def test_uses_configured_identity(self, unidentified_git_repo, tmp_path):
        """Salvage applies the same per-project identity as normal commits."""
        _tree(unidentified_git_repo)
        cfg = Config(
            company_root=unidentified_git_repo,
            project_repo_path=".",
            project_default_branch="main",
            project_push=False,
            project_validate_commands=["true"],
            project_worktrees_dir=str(tmp_path / "worktrees"),
            project_commit_author_email="bot@agent-os",
            project_commit_author_name="agent-os bot",
        )
        ws = create_workspace("task-sc-005", config=cfg)
        (ws.worktree_path / "x.txt").write_text("x")

        sha = salvage_commit(
            ws,
            {"id": "task-sc-005", "title": "t"},
            "agent-001",
            "max_turns",
            config=cfg,
        )
        assert sha is not None

        log_result = subprocess.run(
            ["git", "log", "-1", "--format=%an <%ae>"],
            cwd=str(ws.worktree_path),
            capture_output=True,
            text=True,
        )
        assert "agent-os bot <bot@agent-os>" in log_result.stdout
        cleanup_workspace(ws, delete_branch=True, config=cfg)


# ── push_workspace ───────────────────────────────────────────────────


class TestPushWorkspace:
    def test_skips_when_push_disabled(self, project_config):
        ws = create_workspace("task-push-001", config=project_config)
        ok, msg = push_workspace(ws, config=project_config)
        assert ok is True
        assert "disabled" in msg.lower() or "no remote" in msg.lower()
        cleanup_workspace(ws, delete_branch=True, config=project_config)

    def test_skips_when_no_remote(self, git_repo, tmp_path):
        cfg = Config(
            company_root=git_repo,
            project_push=True,
            project_validate_commands=["true"],
            project_worktrees_dir=str(tmp_path / "worktrees"),
        )
        ws = create_workspace("task-push-002", config=cfg)
        ok, msg = push_workspace(ws, config=cfg)
        assert ok is True
        assert "no remote" in msg.lower()
        cleanup_workspace(ws, delete_branch=True, config=cfg)


# ── cleanup_workspace ────────────────────────────────────────────────


class TestCleanupWorkspace:
    def test_removes_worktree(self, project_config):
        ws = create_workspace("task-clean-001", config=project_config)
        assert ws.worktree_path.exists()
        cleanup_workspace(ws, config=project_config)
        assert not ws.worktree_path.exists()

    def test_deletes_branch_when_requested(self, project_config):
        ws = create_workspace("task-clean-002", config=project_config)
        cleanup_workspace(ws, delete_branch=True, config=project_config)
        result = subprocess.run(
            ["git", "branch", "--list", ws.branch],
            cwd=str(project_config.repo_root),
            capture_output=True,
            text=True,
        )
        assert ws.branch not in result.stdout

    def test_keeps_branch_by_default(self, project_config):
        ws = create_workspace("task-clean-003", config=project_config)
        cleanup_workspace(ws, config=project_config)
        result = subprocess.run(
            ["git", "branch", "--list", ws.branch],
            cwd=str(project_config.repo_root),
            capture_output=True,
            text=True,
        )
        assert "agent/task-clean-003" in result.stdout
        # Clean up the branch manually
        subprocess.run(
            ["git", "branch", "-D", ws.branch],
            cwd=str(project_config.repo_root),
            capture_output=True,
        )


# ── get_workspace ────────────────────────────────────────────────────


class TestGetWorkspace:
    def test_finds_existing_workspace(self, project_config):
        ws = create_workspace("task-get-001", config=project_config)
        found = get_workspace("task-get-001", config=project_config)
        assert found is not None
        assert found.task_id == "task-get-001"
        assert found.worktree_path == ws.worktree_path
        cleanup_workspace(ws, delete_branch=True, config=project_config)

    def test_returns_none_for_missing(self, project_config):
        found = get_workspace("task-nonexistent", config=project_config)
        assert found is None


# ── Config integration ───────────────────────────────────────────────


class TestProjectConfig:
    def test_project_enabled_with_validate(self):
        cfg = Config(project_validate_commands=["pytest"])
        assert cfg.project_enabled is True

    def test_project_enabled_with_setup(self):
        cfg = Config(project_setup_commands=["npm install"])
        assert cfg.project_enabled is True

    def test_project_disabled_by_default(self):
        cfg = Config()
        assert cfg.project_enabled is False

    def test_repo_root_relative(self, tmp_path):
        cfg = Config(company_root=tmp_path, project_repo_path=".")
        assert cfg.repo_root == tmp_path

    def test_repo_root_absolute(self, tmp_path):
        cfg = Config(company_root=tmp_path, project_repo_path="/some/absolute/path")
        assert cfg.repo_root == Path("/some/absolute/path")

    def test_worktrees_root_relative(self, tmp_path):
        cfg = Config(company_root=tmp_path, project_worktrees_dir=".worktrees")
        assert cfg.worktrees_root == tmp_path / ".worktrees"

    def test_from_toml_parses_project(self, tmp_path):
        toml_content = """\
[company]
name = "test"
root = "."

[project]
repo_path = "."
default_branch = "develop"
push = false
remote = "upstream"
code_dir = "src"
worktrees_dir = ".wt"

[project.setup]
commands = ["npm install", "pip install -e ."]
timeout = 120

[project.validate]
commands = ["pytest", "ruff check ."]
timeout = 300
on_failure = "fail"
max_retries = 1
"""
        toml_path = tmp_path / "agent-os.toml"
        toml_path.write_text(toml_content)
        cfg = Config.from_toml(toml_path)

        assert cfg.project_default_branch == "develop"
        assert cfg.project_push is False
        assert cfg.project_remote == "upstream"
        assert cfg.project_code_dir == "src"
        assert cfg.project_worktrees_dir == ".wt"
        assert cfg.project_setup_commands == ["npm install", "pip install -e ."]
        assert cfg.project_setup_timeout == 120
        assert cfg.project_validate_commands == ["pytest", "ruff check ."]
        assert cfg.project_validate_timeout == 300
        assert cfg.project_validate_on_failure == "fail"
        assert cfg.project_validate_max_retries == 1
        assert cfg.project_enabled is True
