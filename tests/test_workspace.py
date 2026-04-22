"""Tests for agent_os.workspace — git worktree lifecycle for the agentic SDLC."""

import subprocess
from pathlib import Path

import pytest

from agent_os.config import Config
from agent_os.workspace import (
    _is_github_remote,
    archive_workspace,
    cleanup_workspace,
    commit_workspace,
    create_workspace,
    get_workspace,
    has_uncommitted_changes,
    open_pull_request,
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


# ── Workspace hardening (Apr 2026): archive, per-attempt, PR creation ──


class TestCleanupWorkspaceReturnShape:
    """cleanup_workspace now returns (success, steps, error) so the runner
    can log + notify when cleanup falls through last-resort steps."""

    def test_returns_success_tuple_on_happy_path(self, project_config):
        ws = create_workspace("task-rs-001", config=project_config)
        result = cleanup_workspace(ws, delete_branch=True, config=project_config)
        assert isinstance(result, tuple) and len(result) == 3
        success, steps, err = result
        assert success is True
        assert "worktree_remove_force" in steps
        assert err is None

    def test_succeeds_when_path_already_gone(self, project_config):
        ws = create_workspace("task-rs-002", config=project_config)
        import shutil as _sh

        _sh.rmtree(ws.worktree_path)
        success, _steps, _err = cleanup_workspace(ws, delete_branch=True, config=project_config)
        assert success is True


class TestArchiveWorkspace:
    def test_moves_worktree_to_archive_dir(self, project_config):
        ws = create_workspace("task-ar-001", config=project_config)
        (ws.worktree_path / "artifact.txt").write_text("work product\n")

        archive_path, events = archive_workspace(ws, "completed", config=project_config)
        assert archive_path is not None
        assert archive_path.parent == project_config.worktrees_archive_root
        assert archive_path.name.startswith("task-ar-001__completed__")
        assert not ws.worktree_path.exists()
        assert (archive_path / "artifact.txt").read_text() == "work product\n"
        # Archive events on a happy path with no pruning should be empty.
        assert all(e.kind != "archive_move_failed" for e in events)

    def test_prunes_old_archives_to_keep_last(self, git_repo, tmp_path):
        cfg = Config(
            company_root=git_repo,
            project_repo_path=".",
            project_default_branch="main",
            project_push=False,
            project_validate_commands=["true"],
            project_worktrees_dir=str(tmp_path / "worktrees"),
            project_archive_enabled=True,
            project_archive_keep_last=2,
        )
        # Create + archive 4 workspaces. Only the 2 most recent should remain.
        archive_paths = []
        for i in range(4):
            ws = create_workspace(f"task-pr-{i:03d}", config=cfg)
            (ws.worktree_path / "x.txt").write_text(str(i))
            path, _events = archive_workspace(ws, "completed", config=cfg)
            archive_paths.append(path)
            # Ensure timestamp ordering is well-defined even on fast filesystems.
            import time as _t

            _t.sleep(0.01)

        remaining = sorted(cfg.worktrees_archive_root.iterdir())
        assert len(remaining) == 2
        # The two most recent archives should be the ones kept.
        assert archive_paths[-1] in remaining
        assert archive_paths[-2] in remaining
        assert archive_paths[0] not in remaining
        assert archive_paths[1] not in remaining

    def test_falls_through_to_cleanup_when_disabled(self, git_repo, tmp_path):
        cfg = Config(
            company_root=git_repo,
            project_repo_path=".",
            project_default_branch="main",
            project_push=False,
            project_validate_commands=["true"],
            project_worktrees_dir=str(tmp_path / "worktrees"),
            project_archive_enabled=False,
        )
        ws = create_workspace("task-ar-off-001", config=cfg)
        archive_path, _events = archive_workspace(ws, "completed", config=cfg)
        assert archive_path is None
        assert not ws.worktree_path.exists()
        # Archive root should NOT have been created.
        assert not cfg.worktrees_archive_root.exists() or not list(cfg.worktrees_archive_root.iterdir())

    def test_handles_missing_worktree_gracefully(self, project_config):
        ws = create_workspace("task-ar-miss-001", config=project_config)
        import shutil as _sh

        _sh.rmtree(ws.worktree_path)
        archive_path, events = archive_workspace(ws, "completed", config=project_config)
        assert archive_path is None
        # No error events — nothing to do was the correct outcome.
        assert all(e.kind != "archive_move_failed" for e in events)


class TestCreateWorkspaceHardening:
    def test_archives_leftover_worktree_on_retry(self, project_config):
        # First run leaves a worktree behind (simulate interrupted cleanup).
        ws1 = create_workspace("task-hd-001", config=project_config)
        (ws1.worktree_path / "partial.txt").write_text("from attempt 1")

        # Second create with the same task-id should archive the leftover,
        # emit an event, and get the primary path back.
        ws2 = create_workspace("task-hd-001", config=project_config)
        assert ws2.worktree_path == ws1.worktree_path  # primary path reused
        assert ws2.attempt == 1
        archive_kinds = [e.kind for e in ws2.events]
        assert "existing_worktree_archived" in archive_kinds
        # The partial work should now be sitting in the archive.
        archives = list(project_config.worktrees_archive_root.iterdir())
        assert any((a / "partial.txt").exists() for a in archives)
        cleanup_workspace(ws2, delete_branch=True, config=project_config)

    def test_falls_back_to_per_attempt_when_primary_cannot_be_freed(self, project_config, monkeypatch):
        """If both archive-move AND force-cleanup fail, create_workspace
        must fall back to a per-attempt path rather than blocking the task."""
        ws1 = create_workspace("task-hd-002", config=project_config)
        # Write some content so the primary path definitely exists.
        (ws1.worktree_path / "x.txt").write_text("x")

        # Sabotage both archive move and force-cleanup by making the path
        # un-removable. We do it by monkeypatching shutil.move AND the
        # internal _force_cleanup_worktree to pretend they failed.
        import agent_os.workspace as wm

        def _fake_move(src, dst):
            raise OSError("simulated archive failure")

        def _fake_force(path, branch, *, repo):
            return False, ["worktree_remove_force_failed"], "simulated cleanup failure"

        monkeypatch.setattr(wm.shutil, "move", _fake_move)
        monkeypatch.setattr(wm, "_force_cleanup_worktree", _fake_force)

        ws2 = create_workspace("task-hd-002", config=project_config)
        assert ws2.attempt >= 2
        assert ws2.branch.startswith("agent/task-hd-002--attempt-")
        kinds = [e.kind for e in ws2.events]
        assert "per_attempt_path_used" in kinds
        # Cleanup only ws2 — ws1 is "stuck" by the monkeypatch, but the test
        # sandbox is torn down by tmp_path so it doesn't matter.
        monkeypatch.undo()
        cleanup_workspace(ws2, delete_branch=True, config=project_config)


class TestOpenPullRequest:
    def test_skipped_when_pr_disabled(self, project_config):
        cfg = Config(
            company_root=project_config.company_root,
            project_repo_path=project_config.project_repo_path,
            project_default_branch=project_config.project_default_branch,
            project_push=True,
            project_validate_commands=["true"],
            project_worktrees_dir=str(project_config.worktrees_root),
            project_pull_request_enabled=False,
        )
        ws = create_workspace("task-pr-001", config=cfg)
        ok, url, msg = open_pull_request(ws, {"id": "task-pr-001", "title": "t"}, "agent-001", config=cfg)
        assert ok is True
        assert url is None
        assert "disabled" in msg.lower()
        cleanup_workspace(ws, delete_branch=True, config=cfg)

    def test_skipped_when_push_disabled(self, project_config):
        # project_config has project_push=False by default.
        ws = create_workspace("task-pr-002", config=project_config)
        ok, url, msg = open_pull_request(ws, {"id": "task-pr-002", "title": "t"}, "agent-001", config=project_config)
        assert ok is True
        assert url is None
        assert "push" in msg.lower()
        cleanup_workspace(ws, delete_branch=True, config=project_config)

    def test_skipped_when_no_remote(self, git_repo, tmp_path):
        cfg = Config(
            company_root=git_repo,
            project_repo_path=".",
            project_default_branch="main",
            project_push=True,
            project_validate_commands=["true"],
            project_worktrees_dir=str(tmp_path / "worktrees"),
        )
        ws = create_workspace("task-pr-003", config=cfg)
        ok, url, msg = open_pull_request(ws, {"id": "task-pr-003", "title": "t"}, "agent-001", config=cfg)
        assert ok is True
        assert url is None
        assert "not configured" in msg.lower()
        cleanup_workspace(ws, delete_branch=True, config=cfg)

    def test_skipped_when_remote_is_not_github(self, git_repo, tmp_path):
        # Add a non-GitHub remote.
        subprocess.run(
            ["git", "remote", "add", "origin", "https://gitlab.com/fake/repo.git"],
            cwd=str(git_repo),
            capture_output=True,
            check=True,
        )
        cfg = Config(
            company_root=git_repo,
            project_repo_path=".",
            project_default_branch="main",
            project_push=True,
            project_validate_commands=["true"],
            project_worktrees_dir=str(tmp_path / "worktrees"),
        )
        ws = create_workspace("task-pr-004", config=cfg)
        ok, url, msg = open_pull_request(ws, {"id": "task-pr-004", "title": "t"}, "agent-001", config=cfg)
        assert ok is True
        assert url is None
        assert "not a github" in msg.lower()
        cleanup_workspace(ws, delete_branch=True, config=cfg)

    def test_pr_config_parsed_from_toml(self, tmp_path):
        toml = tmp_path / "agent-os.toml"
        toml.write_text(
            """
[company]
name = "Test"

[project.pull_request]
enabled = false
draft = true
base_branch = "develop"

[project.archive]
enabled = false
keep_last = 5
"""
        )
        cfg = Config.from_toml(toml)
        assert cfg.project_pull_request_enabled is False
        assert cfg.project_pull_request_draft is True
        assert cfg.project_pull_request_base_branch == "develop"
        assert cfg.project_archive_enabled is False
        assert cfg.project_archive_keep_last == 5


class TestFastForwardLocalDefaultBranch:
    """create_workspace must keep the base clone's local default branch in
    sync with origin so long-running deployments don't accumulate drift."""

    def _setup_remote_and_clone(self, tmp_path):
        """Build a bare remote + a clone that tracks it. Returns (clone, bare)."""
        bare = tmp_path / "bare.git"
        subprocess.run(
            ["git", "init", "--bare", "--initial-branch=main", str(bare)],
            capture_output=True,
            check=True,
        )
        clone = tmp_path / "clone"
        subprocess.run(
            ["git", "clone", str(bare), str(clone)],
            capture_output=True,
            check=True,
        )
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(clone), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(clone), capture_output=True, check=True)
        (clone / "README.md").write_text("# init\n")
        subprocess.run(["git", "add", "-A"], cwd=str(clone), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=str(clone), capture_output=True, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(clone), capture_output=True, check=True)
        return clone, bare

    def _advance_remote(self, tmp_path, bare):
        """Push a second commit to the bare remote via a throwaway clone."""
        tmp_clone = tmp_path / "tmp_clone"
        subprocess.run(
            ["git", "clone", str(bare), str(tmp_clone)],
            capture_output=True,
            check=True,
        )
        subprocess.run(["git", "config", "user.email", "t2@t"], cwd=str(tmp_clone), capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "T2"], cwd=str(tmp_clone), capture_output=True, check=True)
        (tmp_clone / "CHANGELOG.md").write_text("# new\n")
        subprocess.run(["git", "add", "-A"], cwd=str(tmp_clone), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "advance"], cwd=str(tmp_clone), capture_output=True, check=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=str(tmp_clone), capture_output=True, check=True)
        # Capture the new remote HEAD for assertions.
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(tmp_clone),
            capture_output=True,
            text=True,
            check=True,
        )
        return head.stdout.strip()

    def _tree(self, company_root):
        for sub in ("queued", "in-progress", "done", "failed", "backlog", "declined", "in-review"):
            (company_root / "agents" / "tasks" / sub).mkdir(parents=True, exist_ok=True)

    def test_fast_forwards_local_when_remote_is_ahead(self, tmp_path):
        clone, bare = self._setup_remote_and_clone(tmp_path)
        new_head = self._advance_remote(tmp_path, bare)
        self._tree(clone)

        cfg = Config(
            company_root=clone,
            project_repo_path=".",
            project_default_branch="main",
            project_push=True,
            project_remote="origin",
            project_validate_commands=["true"],
            project_worktrees_dir=str(tmp_path / "worktrees"),
        )

        # Precondition: clone's local main is behind remote.
        before = subprocess.run(
            ["git", "rev-parse", "main"],
            cwd=str(clone),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert before != new_head

        ws = create_workspace("task-ff-001", config=cfg)

        after = subprocess.run(
            ["git", "rev-parse", "main"],
            cwd=str(clone),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert after == new_head, "local main should be fast-forwarded to origin/main"
        # No divergence event should have been recorded.
        assert all(e.kind != "local_default_diverged" for e in ws.events)
        cleanup_workspace(ws, delete_branch=True, config=cfg)

    def test_records_divergence_when_local_has_own_commits(self, tmp_path):
        clone, bare = self._setup_remote_and_clone(tmp_path)
        # Advance both local AND remote independently so they diverge.
        self._advance_remote(tmp_path, bare)
        (clone / "LOCAL_ONLY.md").write_text("local\n")
        subprocess.run(["git", "add", "-A"], cwd=str(clone), capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "local-only"], cwd=str(clone), capture_output=True, check=True)
        self._tree(clone)

        cfg = Config(
            company_root=clone,
            project_repo_path=".",
            project_default_branch="main",
            project_push=True,
            project_remote="origin",
            project_validate_commands=["true"],
            project_worktrees_dir=str(tmp_path / "worktrees"),
        )

        local_head_before = subprocess.run(
            ["git", "rev-parse", "main"], cwd=str(clone), capture_output=True, text=True, check=True
        ).stdout.strip()

        ws = create_workspace("task-ff-002", config=cfg)

        local_head_after = subprocess.run(
            ["git", "rev-parse", "main"], cwd=str(clone), capture_output=True, text=True, check=True
        ).stdout.strip()
        # Local must not have been touched — we preserved the divergent commit.
        assert local_head_after == local_head_before
        # But the event should have been recorded.
        assert any(e.kind == "local_default_diverged" for e in ws.events)
        cleanup_workspace(ws, delete_branch=True, config=cfg)


class TestIsGithubRemote:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://github.com/owner/repo.git", True),
            ("git@github.com:owner/repo.git", True),
            ("ssh://git@github.com/owner/repo", True),
            ("https://gitlab.com/owner/repo.git", False),
            ("https://bitbucket.org/owner/repo.git", False),
            ("https://git.example.com/owner/repo.git", False),
            ("", False),
        ],
    )
    def test_github_detection(self, url, expected):
        assert _is_github_remote(url) is expected
