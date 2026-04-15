"""Tests for agent_os.notifications — notification dispatch and channels."""

import json
from unittest.mock import patch

from agent_os.config import Config
from agent_os.notifications import (
    NotificationEvent,
    _meets_severity,
    notify_file,
    send_notification,
)


def _make_event(**kwargs):
    defaults = {
        "event_type": "test_event",
        "severity": "warning",
        "title": "Test notification",
        "detail": "Something happened",
        "agent_id": "agent-001",
    }
    defaults.update(kwargs)
    return NotificationEvent(**defaults)


class TestSeverityFilter:
    def test_critical_meets_warning(self):
        assert _meets_severity("critical", "warning") is True

    def test_warning_meets_warning(self):
        assert _meets_severity("warning", "warning") is True

    def test_info_does_not_meet_warning(self):
        assert _meets_severity("info", "warning") is False

    def test_info_meets_info(self):
        assert _meets_severity("info", "info") is True


class TestNotifyFile:
    def test_writes_notification_file(self, aios_config):
        event = _make_event()
        result = notify_file(event, config=aios_config)

        assert result.success is True
        assert result.channel == "file"

        notif_dir = aios_config.operations_dir / "notifications"
        assert notif_dir.exists()
        files = list(notif_dir.glob("*.md"))
        assert len(files) == 1

        content = files[0].read_text()
        assert "Test notification" in content
        assert "test_event" in content

    def test_creates_directory_if_missing(self, aios_config):
        event = _make_event()
        result = notify_file(event, config=aios_config)
        assert result.success is True

    def test_handles_write_error(self, aios_config):
        import os

        notif_dir = aios_config.operations_dir / "notifications"
        notif_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(notif_dir, 0o444)

        event = _make_event()
        result = notify_file(event, config=aios_config)
        assert result.success is False
        assert result.error

        # Restore permissions for cleanup
        os.chmod(notif_dir, 0o755)


class TestSendNotification:
    def test_dispatches_to_file_by_default(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_enabled=True,
            notifications_file=True,
            notifications_desktop=False,
            notifications_min_severity="info",
        )
        event = _make_event(severity="warning")
        results = send_notification(event, config=cfg)

        assert len(results) == 1
        assert results[0].channel == "file"
        assert results[0].success is True

    def test_disabled_notifications(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_enabled=False,
        )
        event = _make_event()
        results = send_notification(event, config=cfg)
        assert results == []

    def test_severity_filtering(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_enabled=True,
            notifications_min_severity="critical",
        )
        event = _make_event(severity="warning")
        results = send_notification(event, config=cfg)
        assert results == []

    def test_logs_notification(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_enabled=True,
            notifications_file=True,
            notifications_desktop=False,
            notifications_min_severity="info",
            log_also_print=False,
        )
        event = _make_event(severity="warning")
        send_notification(event, config=cfg)

        # Check system log was written — use cfg.tz to match the logger's
        # timezone (otherwise this flakes across midnight boundaries when
        # local time and cfg.tz disagree on the date).
        from datetime import datetime

        today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
        log_file = cfg.logs_dir / "system" / f"{today}.jsonl"
        assert log_file.exists()
        lines = log_file.read_text().strip().splitlines()
        last_entry = json.loads(lines[-1])
        assert last_entry["action"] == "notification_sent"

    def test_webhook_channel(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            notifications_enabled=True,
            notifications_file=False,
            notifications_desktop=False,
            notifications_webhook_url="https://hooks.example.com/test",
            notifications_min_severity="info",
            log_also_print=False,
        )
        event = _make_event()

        with patch("agent_os.notifications.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            results = send_notification(event, config=cfg)

        webhook_results = [r for r in results if r.channel == "webhook"]
        assert len(webhook_results) == 1
        assert webhook_results[0].success is True

    def test_script_channel(self, aios_config):
        # Create a dummy script
        script = aios_config.company_root / "notify.sh"
        script.write_text("#!/bin/bash\nexit 0\n")
        script.chmod(0o755)

        cfg = Config(
            company_root=aios_config.company_root,
            notifications_enabled=True,
            notifications_file=False,
            notifications_desktop=False,
            notifications_script="notify.sh",
            notifications_min_severity="info",
            log_also_print=False,
        )
        event = _make_event()
        results = send_notification(event, config=cfg)

        script_results = [r for r in results if r.channel == "script"]
        assert len(script_results) == 1
        assert script_results[0].success is True
