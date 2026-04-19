"""Tests for agent_os.project — workspace SDLC onboarding."""

import subprocess
from unittest.mock import patch

from agent_os.config import Config
from agent_os.project import (
    ProjectCheck,
    _has_project_section,
    _parse_github_repo,
    ensure_worktrees_gitignored,
    run_project_check,
    ssh_setup_instructions,
    write_project_config,
)


def _project_cfg(aios_config, **overrides) -> Config:
    """Config with [project] enabled + all the overrides we need per test."""
    defaults = dict(
        company_root=aios_config.company_root,
        project_repo_path=".",
        project_default_branch="main",
        project_push=True,
        project_remote="origin",
        project_validate_commands=["true"],
        log_also_print=False,
    )
    defaults.update(overrides)
    return Config(**defaults)


class TestRunProjectCheckNoProjectSection:
    def test_unconfigured_returns_single_warning(self, aios_config):
        result = run_project_check(config=aios_config)
        # Exactly one check when [project] isn't configured — downstream
        # checks would be noise when the feature isn't in use.
        assert len(result.checks) == 1
        assert result.checks[0].status == "warning"
        assert "project init" in result.checks[0].fix


class TestRunProjectCheckMissingRepo:
    def test_reports_missing_git_repo(self, aios_config):
        cfg = _project_cfg(aios_config)
        # aios_config fixture does NOT create a .git directory
        result = run_project_check(config=cfg)
        repo_check = next(c for c in result.checks if c.name == "Repo exists")
        assert repo_check.status == "error"
        assert "No git repo" in repo_check.detail


class TestRunProjectCheckWithRepo:
    def test_reports_missing_remote(self, aios_config, tmp_path):
        """With a git repo but no configured remote, we should see the
        'Remote configured' check fail with a helpful fix."""
        # Initialize a bare git repo in the company root
        subprocess.run(["git", "init", "-q"], cwd=aios_config.company_root, check=True)

        cfg = _project_cfg(aios_config)
        result = run_project_check(config=cfg)
        remote_check = next(c for c in result.checks if "Remote" in c.name and "configured" in c.name)
        assert remote_check.status == "error"
        assert "git remote add" in remote_check.fix

    def test_worktrees_gitignore_check_flags_missing(self, aios_config):
        subprocess.run(["git", "init", "-q"], cwd=aios_config.company_root, check=True)
        cfg = _project_cfg(aios_config)
        result = run_project_check(config=cfg)
        ignore_check = next(c for c in result.checks if "gitignored" in c.name)
        assert ignore_check.status == "warning"

    def test_worktrees_gitignore_check_passes_when_present(self, aios_config):
        subprocess.run(["git", "init", "-q"], cwd=aios_config.company_root, check=True)
        (aios_config.company_root / ".gitignore").write_text(".worktrees/\n")
        cfg = _project_cfg(aios_config)
        result = run_project_check(config=cfg)
        ignore_check = next(c for c in result.checks if "gitignored" in c.name)
        assert ignore_check.status == "ok"


class TestSetupValidateCommandsCheck:
    def test_missing_binary_flagged_as_error(self, aios_config):
        subprocess.run(["git", "init", "-q"], cwd=aios_config.company_root, check=True)
        cfg = _project_cfg(
            aios_config,
            project_setup_commands=["definitely-not-a-real-binary-xyz install"],
        )
        result = run_project_check(config=cfg)
        setup_check = next(c for c in result.checks if "setup" in c.name.lower())
        assert setup_check.status == "error"
        assert "definitely-not-a-real-binary-xyz" in setup_check.detail

    def test_runnable_commands_pass(self, aios_config):
        subprocess.run(["git", "init", "-q"], cwd=aios_config.company_root, check=True)
        cfg = _project_cfg(
            aios_config,
            project_setup_commands=["echo hello"],  # echo is always on PATH
        )
        result = run_project_check(config=cfg)
        setup_check = next(c for c in result.checks if "setup" in c.name.lower())
        assert setup_check.status == "ok"


class TestWriteProjectConfig:
    def test_writes_new_section(self, tmp_path):
        toml = tmp_path / "agent-os.toml"
        toml.write_text('[company]\nname = "Test"\n')

        write_project_config(
            toml,
            default_branch="main",
            setup_commands=["pip install -e ."],
            validate_commands=["pytest", "ruff check ."],
        )

        content = toml.read_text()
        assert "[project]" in content
        assert 'default_branch = "main"' in content
        assert "[project.setup]" in content
        assert '"pip install -e ."' in content
        assert "[project.validate]" in content
        # Existing [company] section preserved
        assert 'name = "Test"' in content

    def test_refuses_to_overwrite_existing(self, tmp_path):
        toml = tmp_path / "agent-os.toml"
        toml.write_text('[company]\nname = "Test"\n\n[project]\ndefault_branch = "main"\n')

        import pytest

        with pytest.raises(ValueError, match="already exists"):
            write_project_config(toml, default_branch="main")

    def test_raises_if_file_missing(self, tmp_path):
        import pytest

        with pytest.raises(FileNotFoundError):
            write_project_config(tmp_path / "nonexistent.toml", default_branch="main")


class TestHasProjectSection:
    def test_detects_bare_section(self):
        assert _has_project_section("[project]\n")

    def test_detects_subsection(self):
        assert _has_project_section("[project.setup]\n")

    def test_ignores_commented_out(self):
        assert not _has_project_section("# [project]\n# default_branch = 'main'\n")

    def test_returns_false_when_absent(self):
        assert not _has_project_section('[company]\nname = "Test"\n[runtime]\nmodel = "x"\n')


class TestEnsureWorktreesGitignored:
    def test_creates_gitignore_when_missing(self, aios_config):
        cfg = _project_cfg(aios_config)
        # aios_config fixture doesn't create a .gitignore
        (aios_config.company_root / ".gitignore").unlink(missing_ok=True)

        modified = ensure_worktrees_gitignored(cfg)
        assert modified
        content = (aios_config.company_root / ".gitignore").read_text()
        assert ".worktrees/" in content

    def test_appends_when_entry_missing(self, aios_config):
        cfg = _project_cfg(aios_config)
        (aios_config.company_root / ".gitignore").write_text("*.pyc\n")

        modified = ensure_worktrees_gitignored(cfg)
        assert modified
        content = (aios_config.company_root / ".gitignore").read_text()
        assert ".worktrees/" in content
        assert "*.pyc" in content  # existing content preserved

    def test_noop_when_already_present(self, aios_config):
        cfg = _project_cfg(aios_config)
        (aios_config.company_root / ".gitignore").write_text(".worktrees/\n")

        modified = ensure_worktrees_gitignored(cfg)
        assert not modified


class TestSshSetupInstructions:
    def test_includes_github_deploy_key_flow(self, aios_config):
        cfg = _project_cfg(aios_config)
        text = ssh_setup_instructions(cfg)
        assert "deploy key" in text.lower()
        assert "Allow write access" in text
        assert "ssh-keygen" in text

    def test_links_to_specific_repo_when_url_parseable(self, aios_config):
        cfg = _project_cfg(aios_config)
        text = ssh_setup_instructions(cfg, remote_url="git@github.com:corvyd-ai/agent-os.git")
        assert "corvyd-ai/agent-os" in text

    def test_gracefully_handles_unparseable_url(self, aios_config):
        cfg = _project_cfg(aios_config)
        text = ssh_setup_instructions(cfg, remote_url="ssh://user@example.com/path.git")
        # Still produces useful output, just without the repo-specific link
        assert "deploy key" in text.lower()


class TestParseGithubRepo:
    def test_ssh_url(self):
        assert _parse_github_repo("git@github.com:corvyd-ai/agent-os.git") == "corvyd-ai/agent-os"

    def test_https_url(self):
        assert _parse_github_repo("https://github.com/corvyd-ai/agent-os.git") == "corvyd-ai/agent-os"

    def test_url_without_git_suffix(self):
        assert _parse_github_repo("https://github.com/corvyd-ai/agent-os") == "corvyd-ai/agent-os"

    def test_non_github_url_returns_empty(self):
        assert _parse_github_repo("git@gitlab.com:org/repo.git") == ""


class TestRemoteReachabilityCheck:
    """The remote-reachable check runs real `git ls-remote` — we can't hit
    a real remote in tests, but we can verify it distinguishes auth failures
    from other errors (the distinction drives the SSH-help fix suggestion)."""

    def test_auth_failure_suggests_ssh_help(self, aios_config, tmp_path):
        subprocess.run(["git", "init", "-q"], cwd=aios_config.company_root, check=True)
        # Add a remote that will fail auth — a github.com SSH URL with no key
        # configured would normally fail this way, but we mock to avoid network.
        cfg = _project_cfg(aios_config)

        with patch("agent_os.project._run_git") as mock_git:

            def side_effect(args, **kwargs):
                # Make remote-get-url succeed, ls-remote fail with auth error
                if "get-url" in args:
                    return subprocess.CompletedProcess(args, 0, "git@github.com:x/y.git", "")
                if "ls-remote" in args:
                    return subprocess.CompletedProcess(args, 128, "", "Permission denied (publickey).")
                return subprocess.CompletedProcess(args, 0, "", "")

            mock_git.side_effect = side_effect
            result = run_project_check(config=cfg)

        reach_check = next(c for c in result.checks if c.name == "Remote reachable")
        assert reach_check.status == "error"
        assert "ssh-help" in reach_check.fix

    def test_non_auth_failure_suggests_url_check(self, aios_config):
        subprocess.run(["git", "init", "-q"], cwd=aios_config.company_root, check=True)
        cfg = _project_cfg(aios_config)

        with patch("agent_os.project._run_git") as mock_git:

            def side_effect(args, **kwargs):
                if "get-url" in args:
                    return subprocess.CompletedProcess(args, 0, "https://bad-host.example.com/x/y.git", "")
                if "ls-remote" in args:
                    return subprocess.CompletedProcess(args, 128, "", "Could not resolve host: bad-host.example.com")
                return subprocess.CompletedProcess(args, 0, "", "")

            mock_git.side_effect = side_effect
            result = run_project_check(config=cfg)

        reach_check = next(c for c in result.checks if c.name == "Remote reachable")
        assert reach_check.status == "error"
        assert "ssh-help" not in reach_check.fix


class TestProjectCheckResult:
    def test_ready_false_on_any_error(self):
        from agent_os.project import ProjectCheckResult

        r = ProjectCheckResult(checks=[ProjectCheck(name="x", status="error")])
        assert not r.ready

    def test_ready_true_when_no_errors(self):
        from agent_os.project import ProjectCheckResult

        r = ProjectCheckResult(
            checks=[
                ProjectCheck(name="x", status="ok"),
                ProjectCheck(name="y", status="warning"),  # warnings don't block
            ]
        )
        assert r.ready
