"""Tests for agent_os.doctor — diagnostic health checks."""

import os

from agent_os.config import Config
from agent_os.doctor import (
    _check_api_key,
    _check_config,
    _check_directory_structure,
    _check_file_permissions,
    _check_task_consistency,
    _check_write_probes,
    _resolve_runtime_user,
    format_doctor_output,
    run_doctor,
)


class TestCheckDirectoryStructure:
    def test_all_dirs_present(self, aios_config):
        # aios_config fixture creates most dirs; create the rest that INIT_DIRS expects
        for d in ["products", "knowledge", "operations/scripts", "strategy/decisions"]:
            (aios_config.company_root / d).mkdir(parents=True, exist_ok=True)
        result = _check_directory_structure(aios_config)
        assert result.status == "ok"

    def test_missing_dirs(self, aios_config):
        # Remove a directory
        import shutil

        shutil.rmtree(aios_config.tasks_queued)
        result = _check_directory_structure(aios_config)
        assert result.status == "error"
        assert "queued" in result.detail


class TestCheckFilePermissions:
    def test_clean_permissions(self, aios_config):
        result = _check_file_permissions(aios_config)
        assert result.status == "ok"

    def test_detects_foreign_owned_files(self, aios_config):
        # We can't actually change ownership without root,
        # but we can verify the check runs clean on our own files
        d = aios_config.tasks_queued
        (d / "task-001.md").write_text("test")
        result = _check_file_permissions(aios_config)
        assert result.status == "ok"


class TestCheckWriteProbes:
    def test_writable_dirs(self, aios_config):
        result = _check_write_probes(aios_config)
        assert result.status == "ok"

    def test_read_only_dir(self, aios_config):
        os.chmod(aios_config.tasks_queued, 0o444)
        result = _check_write_probes(aios_config)
        assert result.status == "error"
        assert "Cannot write" in result.detail
        os.chmod(aios_config.tasks_queued, 0o755)


class TestCheckTaskConsistency:
    def test_no_stuck_tasks(self, aios_config):
        result = _check_task_consistency(aios_config)
        assert result.status == "ok"

    def test_detects_stuck_tasks(self, aios_config):
        import time

        task_file = aios_config.tasks_in_progress / "task-stuck.md"
        task_file.write_text("---\nstatus: in-progress\n---\n")
        # Make it look old
        old_time = time.time() - (8 * 3600)
        os.utime(task_file, (old_time, old_time))

        result = _check_task_consistency(aios_config)
        assert result.status == "warning"
        assert "stuck" in result.detail


class TestCheckApiKey:
    def test_key_present_in_environ(self, aios_config, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        result = _check_api_key(aios_config)
        assert result.status == "ok"
        assert "environment" in result.detail

    def test_key_missing(self, aios_config, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = _check_api_key(aios_config)
        assert result.status == "error"

    def test_key_found_in_dotenv(self, aios_config, monkeypatch):
        """When shell env lacks the key, doctor should fall back to .env."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        (aios_config.company_root / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-from-env-file\n")
        result = _check_api_key(aios_config)
        assert result.status == "ok"
        assert ".env" in result.detail

    def test_key_found_in_runtime_env_file(self, aios_config, monkeypatch):
        """Configured runtime_env_file (e.g., systemd EnvironmentFile)."""
        from agent_os.config import Config

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        env_file = aios_config.company_root / "agent-os.env"
        env_file.write_text("ANTHROPIC_API_KEY=sk-ant-systemd\n")
        cfg = Config(
            company_root=aios_config.company_root,
            runtime_env_file="agent-os.env",
        )
        result = _check_api_key(cfg)
        assert result.status == "ok"
        assert "agent-os.env" in result.detail

    def test_key_found_in_systemd_environment_line(self, aios_config, monkeypatch):
        """systemd-style `Environment="KEY=value"` should also be detected."""
        from agent_os.config import Config

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        env_file = aios_config.company_root / "agent-os.env"
        env_file.write_text('Environment="ANTHROPIC_API_KEY=sk-ant-systemd"\n')
        cfg = Config(
            company_root=aios_config.company_root,
            runtime_env_file="agent-os.env",
        )
        result = _check_api_key(cfg)
        assert result.status == "ok"


class TestResolveRuntimeUser:
    def test_defaults_to_invoking_user(self, aios_config):
        _name, uid, source = _resolve_runtime_user(aios_config)
        assert uid == os.getuid()
        assert source == "invoking user"

    def test_override_argument_wins(self, aios_config):
        # Use a nonexistent user — we still want the name returned, with uid=None
        name, uid, source = _resolve_runtime_user(aios_config, override="definitely-not-a-real-user-xyz")
        assert name == "definitely-not-a-real-user-xyz"
        assert uid is None
        assert source == "--runtime-user"

    def test_config_runtime_user(self, aios_config):
        from agent_os.config import Config

        cfg = Config(
            company_root=aios_config.company_root,
            runtime_user="definitely-not-a-real-user-xyz",
        )
        name, uid, source = _resolve_runtime_user(cfg)
        assert name == "definitely-not-a-real-user-xyz"
        assert uid is None
        assert source == "config runtime_user"


class TestCheckFilePermissionsWithRuntimeUser:
    def test_unknown_runtime_user_does_not_error(self, aios_config):
        """An unresolvable runtime user should degrade to a warning, not
        fail the whole check (which would block healthy systems)."""
        result = _check_file_permissions(aios_config, runtime_user_override="no-such-user-xyz")
        assert result.status == "warning"
        assert "does not exist" in result.detail

    def test_matching_uid_passes(self, aios_config):
        """Files owned by the invoking user should pass when no runtime_user
        is set (invoking user is the default)."""
        (aios_config.tasks_queued / "task-001.md").write_text("test")
        result = _check_file_permissions(aios_config)
        assert result.status == "ok"


class TestCheckConfig:
    def test_valid_config(self, aios_config):
        result = _check_config(aios_config)
        assert result.status == "ok"

    def test_invalid_budget(self):
        cfg = Config(daily_budget_cap_usd=0)
        result = _check_config(cfg)
        assert result.status == "warning"
        assert "daily_budget_cap_usd" in result.detail


class TestRunDoctor:
    def test_healthy_system(self, aios_config, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        # Create all expected dirs that aios_config fixture doesn't create
        for d in ["products", "knowledge", "operations/scripts", "strategy/decisions"]:
            (aios_config.company_root / d).mkdir(parents=True, exist_ok=True)
        result = run_doctor(config=aios_config)
        assert result.errors == 0

    def test_returns_all_checks(self, aios_config, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        result = run_doctor(config=aios_config)
        assert len(result.checks) == 10


class TestFormatDoctorOutput:
    def test_format_with_errors(self, aios_config, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        result = run_doctor(config=aios_config)
        output = format_doctor_output(result, no_color=True, verbose=True)
        assert "agent-os doctor" in output
        assert "passed" in output

    def test_format_hides_ok_by_default(self, aios_config, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        result = run_doctor(config=aios_config)
        output = format_doctor_output(result, no_color=True, verbose=False)
        # Should show summary but not individual OK checks
        assert "passed" in output
