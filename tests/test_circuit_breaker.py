"""Tests for agent_os.circuit_breaker — failure circuit breaker."""

import json
from datetime import datetime, timedelta

from agent_os.circuit_breaker import (
    _count_consecutive_errors,
    auto_check_reset,
    check_breaker,
    evaluate_breaker,
    reset_breaker,
    trip_breaker,
)
from agent_os.config import Config


def _write_log_entries(cfg, agent_id, entries):
    """Write log entries to the agent's JSONL file."""
    log_dir = cfg.logs_dir / agent_id
    log_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
    log_file = log_dir / f"{today}.jsonl"
    with open(log_file, "a") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


class TestCountConsecutiveErrors:
    def test_no_log_file(self, aios_config):
        count, _cat, _detail = _count_consecutive_errors("agent-001", config=aios_config)
        assert count == 0

    def test_no_errors(self, aios_config):
        _write_log_entries(
            aios_config,
            "agent-001",
            [
                {"level": "info", "action": "cycle_start", "detail": "ok", "refs": {}},
                {"level": "info", "action": "cycle_idle", "detail": "ok", "refs": {}},
            ],
        )
        count, _cat, _detail = _count_consecutive_errors("agent-001", config=aios_config)
        assert count == 0

    def test_consecutive_errors(self, aios_config):
        _write_log_entries(
            aios_config,
            "agent-001",
            [
                {"level": "info", "action": "cycle_start", "detail": "ok", "refs": {}},
                {
                    "level": "error",
                    "action": "sdk_error",
                    "detail": "Permission denied",
                    "refs": {"error_category": "permanent"},
                },
                {
                    "level": "error",
                    "action": "sdk_error",
                    "detail": "Permission denied",
                    "refs": {"error_category": "permanent"},
                },
                {
                    "level": "error",
                    "action": "sdk_error",
                    "detail": "Permission denied",
                    "refs": {"error_category": "permanent"},
                },
            ],
        )
        count, cat, detail = _count_consecutive_errors("agent-001", config=aios_config)
        assert count == 3
        assert cat == "permanent"
        assert "Permission denied" in detail

    def test_error_streak_broken_by_info(self, aios_config):
        _write_log_entries(
            aios_config,
            "agent-001",
            [
                {"level": "error", "action": "old_error", "detail": "old", "refs": {}},
                {"level": "info", "action": "cycle_start", "detail": "ok", "refs": {}},
                {"level": "error", "action": "new_error", "detail": "new", "refs": {}},
            ],
        )
        count, _cat, _detail = _count_consecutive_errors("agent-001", config=aios_config)
        assert count == 1


class TestCheckBreaker:
    def test_not_tripped_by_default(self, aios_config):
        state = check_breaker("agent-001", config=aios_config)
        assert state.tripped is False
        assert state.consecutive_failures == 0

    def test_disabled_breaker(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            circuit_breaker_enabled=False,
        )
        state = check_breaker("agent-001", config=cfg)
        assert state.tripped is False

    def test_reads_persisted_state(self, aios_config):
        # Write a breaker file directly
        state_dir = aios_config.agents_state_dir / "agent-001"
        state_dir.mkdir(parents=True, exist_ok=True)
        breaker_file = state_dir / ".circuit-breaker.json"
        breaker_file.write_text(
            json.dumps(
                {
                    "tripped": True,
                    "tripped_at": "2026-04-13T10:00:00+00:00",
                    "reason": "5 consecutive failures",
                    "last_error_category": "permanent",
                    "last_error_detail": "Permission denied",
                    "consecutive_failures": 5,
                }
            )
        )

        state = check_breaker("agent-001", config=aios_config)
        assert state.tripped is True
        assert state.reason == "5 consecutive failures"
        assert state.consecutive_failures == 5


class TestTripBreaker:
    def test_writes_state_file(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            log_also_print=False,
            notifications_desktop=False,
        )
        state = trip_breaker("agent-001", "test reason", config=cfg)

        assert state.tripped is True
        assert state.reason == "test reason"

        # Verify file was written
        breaker_file = cfg.agents_state_dir / "agent-001" / ".circuit-breaker.json"
        assert breaker_file.exists()
        data = json.loads(breaker_file.read_text())
        assert data["tripped"] is True
        assert data["reason"] == "test reason"


class TestResetBreaker:
    def test_removes_state_file(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            log_also_print=False,
        )
        # Create a breaker file
        state_dir = cfg.agents_state_dir / "agent-001"
        state_dir.mkdir(parents=True, exist_ok=True)
        breaker_file = state_dir / ".circuit-breaker.json"
        breaker_file.write_text('{"tripped": true}')

        reset_breaker("agent-001", config=cfg)
        assert not breaker_file.exists()

    def test_reset_nonexistent(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            log_also_print=False,
        )
        # Should not raise
        reset_breaker("agent-001", config=cfg)


class TestEvaluateBreaker:
    def test_does_not_trip_below_threshold(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            circuit_breaker_max_failures=5,
            log_also_print=False,
            notifications_desktop=False,
        )
        _write_log_entries(
            cfg,
            "agent-001",
            [
                {"level": "error", "action": "sdk_error", "detail": "err", "refs": {}},
                {"level": "error", "action": "sdk_error", "detail": "err", "refs": {}},
            ],
        )

        state = evaluate_breaker("agent-001", config=cfg)
        assert state.tripped is False
        assert state.consecutive_failures == 2

    def test_trips_at_threshold(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            circuit_breaker_max_failures=3,
            log_also_print=False,
            notifications_desktop=False,
        )
        _write_log_entries(
            cfg,
            "agent-001",
            [
                {"level": "error", "action": "sdk_error", "detail": "err", "refs": {"error_category": "permanent"}},
                {"level": "error", "action": "sdk_error", "detail": "err", "refs": {"error_category": "permanent"}},
                {"level": "error", "action": "sdk_error", "detail": "err", "refs": {"error_category": "permanent"}},
            ],
        )

        state = evaluate_breaker("agent-001", config=cfg)
        assert state.tripped is True

    def test_disabled_breaker(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            circuit_breaker_enabled=False,
        )
        state = evaluate_breaker("agent-001", config=cfg)
        assert state.tripped is False


class TestAutoCheckReset:
    def test_no_reset_before_cooldown(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            circuit_breaker_cooldown_minutes=60,
        )
        state_dir = cfg.agents_state_dir / "agent-001"
        state_dir.mkdir(parents=True, exist_ok=True)
        breaker_file = state_dir / ".circuit-breaker.json"
        breaker_file.write_text(
            json.dumps(
                {
                    "tripped": True,
                    "tripped_at": datetime.now(cfg.tz).isoformat(),
                    "reason": "test",
                }
            )
        )

        assert auto_check_reset("agent-001", config=cfg) is False
        # Breaker file should still exist
        assert breaker_file.exists()

    def test_resets_after_cooldown_if_healthy(self, aios_config):
        cfg = Config(
            company_root=aios_config.company_root,
            circuit_breaker_cooldown_minutes=60,
            log_also_print=False,
        )
        state_dir = cfg.agents_state_dir / "agent-001"
        state_dir.mkdir(parents=True, exist_ok=True)
        breaker_file = state_dir / ".circuit-breaker.json"

        # Tripped 2 hours ago
        old_time = (datetime.now(cfg.tz) - timedelta(hours=2)).isoformat()
        breaker_file.write_text(
            json.dumps(
                {
                    "tripped": True,
                    "tripped_at": old_time,
                    "reason": "test",
                }
            )
        )

        result = auto_check_reset("agent-001", config=cfg)
        assert result is True
        assert not breaker_file.exists()
