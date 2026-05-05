"""Tests for agent_os.maintenance.run_daily_digest — daily health digest."""

import json
import os
import time
from datetime import UTC, datetime, timedelta

from agent_os.config import Config
from agent_os.maintenance import DigestResult, run_daily_digest


def _yesterday_str(cfg):
    """Return yesterday's date string in the configured timezone."""
    return (datetime.now(cfg.tz) - timedelta(days=1)).strftime("%Y-%m-%d")


class TestRunDailyDigest:
    def test_empty_system(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        result = run_daily_digest(config=cfg)

        assert isinstance(result, DigestResult)
        assert result.tasks_completed == 0
        assert result.tasks_failed == 0
        assert result.agents_healthy == 0
        assert result.daily_spend == 0.0

    def test_default_window_is_yesterday(self, aios_config):
        """The default window is 'yesterday' — the cron-driven morning briefing."""
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        result = run_daily_digest(config=cfg)
        assert result.window == "yesterday"
        assert result.report_date == _yesterday_str(cfg)

    def test_today_window(self, aios_config):
        """window='today' reports today since midnight."""
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        result = run_daily_digest(window="today", config=cfg)
        today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
        assert result.window == "today"
        assert result.report_date == today

    def test_invalid_window_raises(self, aios_config):
        """An unknown window value raises ValueError."""
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        import pytest

        with pytest.raises(ValueError, match="Invalid window"):
            run_daily_digest(window="last-week", config=cfg)

    def test_writes_digest_file(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        result = run_daily_digest(config=cfg)

        assert result.digest_path
        from pathlib import Path

        digest = Path(result.digest_path)
        assert digest.exists()
        content = digest.read_text()
        assert "Daily Digest" in content
        assert "## Tasks" in content
        assert "## Agents" in content
        assert "## Budget" in content
        # Window label should be present
        assert "Window:" in content

    def test_digest_file_named_by_report_date(self, aios_config):
        """The digest file is named after the report date, not the run date."""
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        result = run_daily_digest(config=cfg)
        assert result.report_date in result.digest_path

    def test_counts_completed_tasks_today_window(self, aios_config):
        """window='today' counts tasks with today's mtime."""
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        done_dir = cfg.tasks_dir / "done"
        done_dir.mkdir(parents=True, exist_ok=True)
        (done_dir / "task-completed-today.md").write_text("---\nstatus: done\n---\n")

        result = run_daily_digest(window="today", config=cfg)
        assert result.tasks_completed == 1

    def test_yesterday_window_ignores_today_tasks(self, aios_config):
        """window='yesterday' should NOT count a task written just now."""
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        done_dir = cfg.tasks_dir / "done"
        done_dir.mkdir(parents=True, exist_ok=True)
        # This file's mtime is "now" = today, not yesterday
        (done_dir / "task-completed-today.md").write_text("---\nstatus: done\n---\n")

        result = run_daily_digest(window="yesterday", config=cfg)
        assert result.tasks_completed == 0

    def test_yesterday_window_counts_yesterday_tasks(self, aios_config):
        """window='yesterday' counts tasks with yesterday's date in filename."""
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        yesterday = _yesterday_str(cfg)
        done_dir = cfg.tasks_dir / "done"
        done_dir.mkdir(parents=True, exist_ok=True)
        # Filename contains yesterday's date
        (done_dir / f"task-{yesterday}-001.md").write_text("---\nstatus: done\n---\n")

        result = run_daily_digest(window="yesterday", config=cfg)
        assert result.tasks_completed == 1

    def test_yesterday_window_counts_yesterday_mtime(self, aios_config):
        """window='yesterday' counts files whose mtime is yesterday."""
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        done_dir = cfg.tasks_dir / "done"
        done_dir.mkdir(parents=True, exist_ok=True)
        # File with a generic name, but mtime set to yesterday
        f = done_dir / "task-generic.md"
        f.write_text("---\nstatus: done\n---\n")
        yesterday_ts = time.time() - 86400
        os.utime(f, (yesterday_ts, yesterday_ts))

        result = run_daily_digest(window="yesterday", config=cfg)
        assert result.tasks_completed == 1

    def test_yesterday_spend_from_cost_file(self, aios_config):
        """window='yesterday' should read yesterday's cost JSONL, not today's."""
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        yesterday = _yesterday_str(cfg)
        costs_dir = cfg.costs_dir
        costs_dir.mkdir(parents=True, exist_ok=True)

        # Write a cost entry for yesterday
        yesterday_cost_file = costs_dir / f"{yesterday}.jsonl"
        entries = [
            json.dumps({"cost_usd": 5.50, "agent": "agent-001"}),
            json.dumps({"cost_usd": 3.25, "agent": "agent-003"}),
        ]
        yesterday_cost_file.write_text("\n".join(entries) + "\n")

        # Write a cost entry for today (should be ignored by yesterday window)
        today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
        today_cost_file = costs_dir / f"{today}.jsonl"
        today_cost_file.write_text(json.dumps({"cost_usd": 0.50, "agent": "agent-001"}) + "\n")

        result = run_daily_digest(window="yesterday", config=cfg)
        assert abs(result.daily_spend - 8.75) < 0.01

    def test_today_spend_from_cost_file(self, aios_config):
        """window='today' should read today's cost JSONL."""
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
        costs_dir = cfg.costs_dir
        costs_dir.mkdir(parents=True, exist_ok=True)

        today_cost_file = costs_dir / f"{today}.jsonl"
        today_cost_file.write_text(json.dumps({"cost_usd": 2.00, "agent": "agent-001"}) + "\n")

        result = run_daily_digest(window="today", config=cfg)
        assert abs(result.daily_spend - 2.00) < 0.01

    def test_detects_anomalies(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        # Write 5+ errors for an agent on today's log (use today window)
        agent_dir = cfg.logs_dir / "agent-001"
        agent_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
        log_file = agent_dir / f"{today}.jsonl"
        entries = []
        for _i in range(6):
            entries.append(
                json.dumps(
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "level": "error",
                        "action": "sdk_error",
                        "detail": f"Error {_i}",
                        "refs": {},
                    }
                )
            )
        log_file.write_text("\n".join(entries) + "\n")

        result = run_daily_digest(window="today", config=cfg)
        assert len(result.anomalies) >= 1
        assert any("sdk_error" in a for a in result.anomalies)

    def test_yesterday_anomalies_use_yesterday_log(self, aios_config):
        """window='yesterday' checks yesterday's log file for anomalies."""
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        yesterday = _yesterday_str(cfg)
        agent_dir = cfg.logs_dir / "agent-001"
        agent_dir.mkdir(parents=True, exist_ok=True)
        log_file = agent_dir / f"{yesterday}.jsonl"
        entries = []
        for _i in range(6):
            entries.append(
                json.dumps(
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "level": "error",
                        "action": "sdk_error",
                        "detail": f"Error {_i}",
                        "refs": {},
                    }
                )
            )
        log_file.write_text("\n".join(entries) + "\n")

        result = run_daily_digest(window="yesterday", config=cfg)
        assert len(result.anomalies) >= 1
        assert any("sdk_error" in a for a in result.anomalies)

    def test_digest_includes_anomalies_section(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        # Write errors to trigger anomaly detection (use today window)
        agent_dir = cfg.logs_dir / "agent-001"
        agent_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
        log_file = agent_dir / f"{today}.jsonl"
        entries = []
        for _i in range(6):
            entries.append(
                json.dumps(
                    {
                        "timestamp": datetime.now(UTC).isoformat(),
                        "level": "error",
                        "action": "preflight_failed",
                        "detail": "Permission denied",
                        "refs": {},
                    }
                )
            )
        log_file.write_text("\n".join(entries) + "\n")

        result = run_daily_digest(window="today", config=cfg)
        from pathlib import Path

        content = Path(result.digest_path).read_text()
        assert "## Anomalies" in content
