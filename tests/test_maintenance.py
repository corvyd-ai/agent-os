"""Tests for agent_os.maintenance — archive, manifest, watchdog."""

import json
import time
from datetime import UTC, datetime, timedelta

from agent_os.config import Config
from agent_os.maintenance import run_archive, run_log_archive, run_manifest, run_watchdog


class TestRunArchive:
    def test_archive_old_broadcasts(self, aios_config):
        broadcast_dir = aios_config.broadcast_dir
        broadcast_dir.mkdir(parents=True, exist_ok=True)

        # Create an old broadcast (10 days old)
        old_file = broadcast_dir / "broadcast-old.md"
        old_file.write_text("old broadcast")
        import os

        old_time = time.time() - (10 * 86400)
        os.utime(old_file, (old_time, old_time))

        # Create a recent broadcast
        new_file = broadcast_dir / "broadcast-new.md"
        new_file.write_text("new broadcast")

        result = run_archive(broadcast_max_age_days=7, config=aios_config)
        assert result.broadcasts_archived == 1
        assert not old_file.exists()
        assert (broadcast_dir / "_archive" / "broadcast-old.md").exists()
        assert new_file.exists()

    def test_archive_old_done_tasks(self, aios_config):
        done_dir = aios_config.tasks_done
        done_dir.mkdir(parents=True, exist_ok=True)

        old_file = done_dir / "task-old.md"
        old_file.write_text("old task")
        import os

        old_time = time.time() - (20 * 86400)
        os.utime(old_file, (old_time, old_time))

        result = run_archive(task_max_age_days=14, config=aios_config)
        assert result.tasks_archived == 1
        assert not old_file.exists()

    def test_nothing_to_archive(self, aios_config):
        result = run_archive(config=aios_config)
        assert result.total_archived == 0

    def test_skips_directories(self, aios_config):
        broadcast_dir = aios_config.broadcast_dir
        broadcast_dir.mkdir(parents=True, exist_ok=True)
        (broadcast_dir / "subdir").mkdir()

        result = run_archive(config=aios_config)
        assert result.broadcasts_archived == 0


class TestRunManifest:
    def test_empty_knowledge_dir(self, aios_config):
        path = run_manifest(config=aios_config)
        assert path.exists()
        content = path.read_text()
        assert "Knowledge Manifest" in content
        assert "No knowledge files found" in content

    def test_indexes_files(self, aios_config):
        knowledge_dir = aios_config.company_root / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "test-doc.md").write_text("# Test Document\n\nSome content")
        (knowledge_dir / "another.md").write_text("# Another Doc\n\nMore content")

        path = run_manifest(config=aios_config)
        content = path.read_text()
        assert "Test Document" in content
        assert "Another Doc" in content
        assert "2 files indexed" in content

    def test_skips_manifest_itself(self, aios_config):
        knowledge_dir = aios_config.company_root / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        (knowledge_dir / "test.md").write_text("# Test\n")

        path = run_manifest(config=aios_config)
        content = path.read_text()
        assert "1 files indexed" in content


class TestRunWatchdog:
    def test_no_logs(self, aios_config):
        result = run_watchdog(config=aios_config)
        assert result.agents_checked == 0
        assert result.alerts == []

    def test_healthy_agent(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            schedule_watchdog_alert_threshold_minutes=45,
        )
        agent_dir = cfg.logs_dir / "agent-001"
        agent_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        log_file = agent_dir / f"{today}.jsonl"
        entry = {"timestamp": datetime.now(UTC).isoformat(), "action": "test"}
        log_file.write_text(json.dumps(entry) + "\n")

        result = run_watchdog(config=cfg)
        assert result.agents_checked == 1
        assert result.agents_healthy == 1
        assert result.alerts == []

    def test_stale_agent(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            schedule_watchdog_alert_threshold_minutes=45,
        )
        agent_dir = cfg.logs_dir / "agent-001"
        agent_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        log_file = agent_dir / f"{today}.jsonl"
        # Entry from 2 hours ago
        old_ts = datetime.now(UTC) - timedelta(hours=2)
        entry = {"timestamp": old_ts.isoformat(), "action": "test"}
        log_file.write_text(json.dumps(entry) + "\n")

        result = run_watchdog(config=cfg)
        assert result.agents_checked == 1
        assert result.agents_stale == 1
        assert len(result.alerts) == 1

    def test_skips_system_dir(self, aios_config):
        system_dir = aios_config.logs_dir / "system"
        system_dir.mkdir(parents=True, exist_ok=True)

        result = run_watchdog(config=aios_config)
        assert result.agents_checked == 0


class TestLogArchive:
    def test_archives_old_logs(self, aios_config):
        import os

        cfg = Config(company_root=aios_config.company_root, log_retention_days=7)
        agent_dir = cfg.logs_dir / "agent-001"
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Old log file (10 days ago)
        old_file = agent_dir / "2026-02-20.jsonl"
        old_file.write_text('{"action": "old"}\n')
        old_time = time.time() - (10 * 86400)
        os.utime(old_file, (old_time, old_time))

        # Recent log file
        new_file = agent_dir / "2026-03-08.jsonl"
        new_file.write_text('{"action": "new"}\n')

        result = run_log_archive(config=cfg)
        assert result.files_archived == 1
        assert not old_file.exists()
        assert new_file.exists()
        assert (agent_dir / "_archive" / "2026-02-20.jsonl.gz").exists()

    def test_deletes_very_old_archives(self, aios_config):
        import os

        cfg = Config(company_root=aios_config.company_root, log_retention_days=7)
        agent_dir = cfg.logs_dir / "agent-001"
        archive_dir = agent_dir / "_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        # Very old archive (3 months ago — well beyond 2x retention)
        old_gz = archive_dir / "2025-12-01.jsonl.gz"
        old_gz.write_bytes(b"fake gz data")
        old_time = time.time() - (90 * 86400)
        os.utime(old_gz, (old_time, old_time))

        result = run_log_archive(config=cfg)
        assert result.files_deleted == 1
        assert not old_gz.exists()

    def test_nothing_to_archive(self, aios_config):
        cfg = Config(company_root=aios_config.company_root, log_retention_days=30)
        # No logs dir at all
        result = run_log_archive(config=cfg)
        assert result.files_archived == 0
        assert result.files_deleted == 0

    def test_archives_compressed_correctly(self, aios_config):
        import gzip
        import os

        cfg = Config(company_root=aios_config.company_root, log_retention_days=7)
        agent_dir = cfg.logs_dir / "agent-001"
        agent_dir.mkdir(parents=True, exist_ok=True)

        content = '{"action": "test", "level": "info"}\n' * 10
        old_file = agent_dir / "2026-01-15.jsonl"
        old_file.write_text(content)
        old_time = time.time() - (60 * 86400)
        os.utime(old_file, (old_time, old_time))

        run_log_archive(config=cfg)

        gz_path = agent_dir / "_archive" / "2026-01-15.jsonl.gz"
        assert gz_path.exists()
        with gzip.open(gz_path, "rt") as f:
            decompressed = f.read()
        assert decompressed == content
