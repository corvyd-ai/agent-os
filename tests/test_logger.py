"""Tests for agent_os.logger — structured JSONL logging."""

import json
from datetime import datetime

from agent_os.config import Config, configure
from agent_os.logger import Logger, get_logger, reset_loggers


def _make_config(tmp_path):
    cfg = Config(company_root=tmp_path, log_level="debug", log_also_print=False)
    configure(cfg)
    return cfg


# ── Logger writes JSONL ──────────────────────────────────────────────


def test_logger_writes_jsonl(tmp_path):
    cfg = _make_config(tmp_path)
    log = Logger("test-agent", config=cfg)
    log.info("test_action", "hello world", {"key": "value"})

    today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
    log_file = tmp_path / "agents" / "logs" / "test-agent" / f"{today}.jsonl"
    assert log_file.exists()

    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 1

    entry = json.loads(lines[0])
    assert entry["agent"] == "test-agent"
    assert entry["level"] == "info"
    assert entry["action"] == "test_action"
    assert entry["detail"] == "hello world"
    assert entry["refs"]["key"] == "value"
    assert "timestamp" in entry


def test_logger_all_levels(tmp_path):
    cfg = _make_config(tmp_path)
    log = Logger("test-agent", config=cfg)

    log.debug("d", "debug msg")
    log.info("i", "info msg")
    log.warn("w", "warn msg")
    log.error("e", "error msg")

    today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
    log_file = tmp_path / "agents" / "logs" / "test-agent" / f"{today}.jsonl"
    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 4

    levels = [json.loads(line)["level"] for line in lines]
    assert levels == ["debug", "info", "warn", "error"]


# ── Level filtering ──────────────────────────────────────────────────


def test_logger_level_filtering(tmp_path):
    cfg = Config(company_root=tmp_path, log_level="warn", log_also_print=False)
    log = Logger("test-agent", config=cfg)

    log.debug("d", "should be filtered")
    log.info("i", "should be filtered")
    log.warn("w", "should appear")
    log.error("e", "should appear")

    today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
    log_file = tmp_path / "agents" / "logs" / "test-agent" / f"{today}.jsonl"
    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 2

    levels = [json.loads(line)["level"] for line in lines]
    assert levels == ["warn", "error"]


def test_logger_error_level_only(tmp_path):
    cfg = Config(company_root=tmp_path, log_level="error", log_also_print=False)
    log = Logger("test-agent", config=cfg)

    log.debug("d", "no")
    log.info("i", "no")
    log.warn("w", "no")
    log.error("e", "yes")

    today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
    log_file = tmp_path / "agents" / "logs" / "test-agent" / f"{today}.jsonl"
    lines = log_file.read_text().strip().split("\n")
    assert len(lines) == 1
    assert json.loads(lines[0])["level"] == "error"


# ── also_print ────────────────────────────────────────────────────────


def test_logger_also_print(tmp_path, capsys):
    cfg = Config(company_root=tmp_path, log_level="info", log_also_print=True)
    log = Logger("agent-001", config=cfg)

    log.info("test", "Hello from agent")
    log.error("err", "Something broke")
    log.warn("wrn", "Watch out")

    captured = capsys.readouterr()
    assert "Hello from agent" in captured.out
    assert "ERROR: Something broke" in captured.out
    assert "WARNING: Watch out" in captured.out


def test_logger_no_print_when_disabled(tmp_path, capsys):
    cfg = Config(company_root=tmp_path, log_level="info", log_also_print=False)
    log = Logger("agent-001", config=cfg)

    log.info("test", "Should not print")
    captured = capsys.readouterr()
    assert captured.out == ""


# ── get_logger caching ────────────────────────────────────────────────


def test_get_logger_caching(tmp_path):
    _make_config(tmp_path)
    reset_loggers()

    log1 = get_logger("agent-001")
    log2 = get_logger("agent-001")
    log3 = get_logger("agent-002")

    assert log1 is log2
    assert log1 is not log3

    reset_loggers()


def test_get_logger_with_config_not_cached(tmp_path):
    cfg = Config(company_root=tmp_path, log_also_print=False)
    reset_loggers()

    log1 = get_logger("agent-001", config=cfg)
    log2 = get_logger("agent-001", config=cfg)

    # Test loggers are NOT cached (fresh each time)
    assert log1 is not log2

    reset_loggers()


# ── System logger ─────────────────────────────────────────────────────


def test_system_logger(tmp_path):
    cfg = _make_config(tmp_path)
    log = Logger("system", config=cfg)
    log.info("tick", "Scheduler tick fired")

    today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
    log_file = tmp_path / "agents" / "logs" / "system" / f"{today}.jsonl"
    assert log_file.exists()

    entry = json.loads(log_file.read_text().strip())
    assert entry["agent"] == "system"
    assert entry["action"] == "tick"


# ── Empty refs ────────────────────────────────────────────────────────


def test_logger_empty_refs(tmp_path):
    cfg = _make_config(tmp_path)
    log = Logger("test-agent", config=cfg)
    log.info("test", "no refs")

    today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
    log_file = tmp_path / "agents" / "logs" / "test-agent" / f"{today}.jsonl"
    entry = json.loads(log_file.read_text().strip())
    assert entry["refs"] == {}
