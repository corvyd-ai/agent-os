"""Tests for agent_os.maintenance.run_daily_digest — daily health digest."""

import json
from datetime import UTC, datetime

from agent_os.config import Config
from agent_os.maintenance import DigestResult, run_daily_digest


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

    def test_counts_completed_tasks(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        # Create a done task with today's date in the name
        today = datetime.now(cfg.tz).strftime("%Y-%m%d")
        done_dir = cfg.tasks_dir / "done"
        done_dir.mkdir(parents=True, exist_ok=True)
        (done_dir / f"task-{today}-001.md").write_text("---\nstatus: done\n---\n")

        result = run_daily_digest(config=cfg)
        assert result.tasks_completed == 1

    def test_detects_anomalies(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        # Write 5+ errors for an agent
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

        result = run_daily_digest(config=cfg)
        assert len(result.anomalies) >= 1
        assert any("sdk_error" in a for a in result.anomalies)

    def test_digest_includes_anomalies_section(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        # Write errors to trigger anomaly detection
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

        result = run_daily_digest(config=cfg)
        from pathlib import Path

        content = Path(result.digest_path).read_text()
        assert "## Anomalies" in content
