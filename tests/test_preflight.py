"""Tests for agent_os.preflight — pre-flight health gate."""

import os

from agent_os.preflight import _check_ownership, _probe_writable, run_preflight


class TestProbeWritable:
    def test_writable_directory(self, aios_config):
        result = _probe_writable(aios_config.tasks_queued)
        assert result.passed is True

    def test_read_only_directory(self, aios_config):
        d = aios_config.tasks_queued
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o444)

        result = _probe_writable(d)
        assert result.passed is False
        assert "Cannot write" in result.detail
        assert result.fix_suggestion

        # Restore for cleanup
        os.chmod(d, 0o755)

    def test_nonexistent_parent_created(self, aios_config):
        d = aios_config.company_root / "new" / "nested" / "dir"
        result = _probe_writable(d)
        assert result.passed is True
        assert d.is_dir()


class TestCheckOwnership:
    def test_all_owned_by_current_user(self, aios_config):
        d = aios_config.tasks_queued
        d.mkdir(parents=True, exist_ok=True)
        (d / "test-task.md").write_text("test")

        result = _check_ownership(d, "tasks_queued")
        assert result.passed is True

    def test_empty_directory(self, aios_config):
        d = aios_config.tasks_queued
        d.mkdir(parents=True, exist_ok=True)

        result = _check_ownership(d, "tasks_queued")
        assert result.passed is True

    def test_nonexistent_directory(self, aios_config):
        d = aios_config.company_root / "does_not_exist"
        result = _check_ownership(d, "nonexistent")
        assert result.passed is True


class TestRunPreflight:
    def test_healthy_system(self, aios_config):
        result = run_preflight("agent-001", config=aios_config)
        assert result.passed is True
        assert len(result.failed_checks) == 0

    def test_read_only_tasks_dir(self, aios_config):
        d = aios_config.tasks_queued
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o444)

        result = run_preflight("agent-001", config=aios_config)
        assert result.passed is False
        assert any("queued" in c.detail for c in result.failed_checks)

        # Restore
        os.chmod(d, 0o755)

    def test_summary_message(self, aios_config):
        result = run_preflight("agent-001", config=aios_config)
        assert result.summary == "All pre-flight checks passed"

    def test_failed_summary(self, aios_config):
        d = aios_config.tasks_queued
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o444)

        result = run_preflight("agent-001", config=aios_config)
        assert "Cannot write" in result.summary

        os.chmod(d, 0o755)

    def test_checks_multiple_directories(self, aios_config):
        result = run_preflight("agent-001", config=aios_config)
        # Should check write probes + ownership checks
        assert len(result.checks) >= 7  # 7 write probes + 3 ownership checks
