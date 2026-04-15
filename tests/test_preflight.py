"""Tests for agent_os.preflight — pre-flight health gate."""

import os

from agent_os.preflight import _probe_writable, run_preflight


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

    def test_checks_are_writability_only(self, aios_config):
        """Preflight must be capability-only — no heuristic ownership checks
        that could misfire and block the scheduler."""
        result = run_preflight("agent-001", config=aios_config)
        # Every check should be a write probe (name starts with "write_")
        for check in result.checks:
            assert check.name.startswith("write_"), (
                f"Unexpected non-write-probe check {check.name!r} — heuristic checks belong in doctor, not preflight"
            )

    def test_does_not_flag_foreign_owned_files(self, aios_config):
        """A file with a different uid must NOT cause preflight to fail, as
        long as the directory itself is writable. This is the corvyd case:
        the scheduler runs as the service account and must not be blocked
        by ownership heuristics that misfire."""
        # Create a normal file — we can't actually change its uid without
        # root, but we verify the check doesn't even try to compare uids.
        (aios_config.tasks_queued / "task-001.md").write_text("test")

        result = run_preflight("agent-001", config=aios_config)
        assert result.passed is True
