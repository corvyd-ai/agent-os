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
    def test_key_present(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        result = _check_api_key()
        assert result.status == "ok"

    def test_key_missing(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = _check_api_key()
        assert result.status == "error"


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
