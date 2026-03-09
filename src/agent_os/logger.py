"""agent-os structured logger — JSONL-based logging for all platform output.

Every log entry is a JSON line written to per-agent or system log files.
This replaces print()-based logging with structured, queryable output.

Usage:
    from agent_os.logger import get_logger

    log = get_logger("agent-001-maker")
    log.info("cycle_start", "Starting cycle", {"task_count": 3})
    log.warn("prompt_large", "System prompt is 120KB")
    log.error("sdk_error", "Connection refused", {"retries": 2})

System-level events (scheduler, maintenance):
    log = get_logger("system")
    log.info("tick", "Dispatching cycle for agent-001")
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import Config, get_config


class Logger:
    """Structured JSONL logger for a single agent or system component.

    Writes to ``logs/{agent_id}/YYYY-MM-DD.jsonl`` (per-agent) or
    ``logs/system/YYYY-MM-DD.jsonl`` (system-level).

    Each line is a JSON object with: timestamp, agent, level, action, detail, refs.
    """

    LEVELS = ("debug", "info", "warn", "error")
    _LEVEL_ORDER = {level: i for i, level in enumerate(LEVELS)}

    def __init__(self, agent_id: str, *, config: Config | None = None):
        self.agent_id = agent_id
        self._config = config

    @property
    def _cfg(self) -> Config:
        return self._config or get_config()

    @property
    def _min_level(self) -> int:
        return self._LEVEL_ORDER.get(self._cfg.log_level, 1)  # default: info

    def _should_log(self, level: str) -> bool:
        return self._LEVEL_ORDER.get(level, 1) >= self._min_level

    def _log_dir(self) -> Path:
        return self._cfg.logs_dir / self.agent_id

    def _write(self, level: str, action: str, detail: str, refs: dict | None = None) -> None:
        """Write a single JSONL entry."""
        if not self._should_log(level):
            return

        cfg = self._cfg
        log_dir = self._log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)

        today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
        log_file = log_dir / f"{today}.jsonl"

        entry = {
            "timestamp": datetime.now(cfg.tz).isoformat(),
            "agent": self.agent_id,
            "level": level,
            "action": action,
            "detail": detail,
            "refs": refs or {},
        }

        with open(log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")

        # Also print if configured (for cron log capture / interactive debugging)
        if cfg.log_also_print:
            tag = f"[agent-os][{self.agent_id}]"
            if level == "error":
                print(f"{tag} ERROR: {detail}", flush=True)
            elif level == "warn":
                print(f"{tag} WARNING: {detail}", flush=True)
            elif level == "debug":
                print(f"{tag} {detail}", flush=True)
            else:
                print(f"{tag} {detail}", flush=True)

    def debug(self, action: str, detail: str, refs: dict | None = None) -> None:
        self._write("debug", action, detail, refs)

    def info(self, action: str, detail: str, refs: dict | None = None) -> None:
        self._write("info", action, detail, refs)

    def warn(self, action: str, detail: str, refs: dict | None = None) -> None:
        self._write("warn", action, detail, refs)

    def error(self, action: str, detail: str, refs: dict | None = None) -> None:
        self._write("error", action, detail, refs)


# --- Module-level cache ---

_loggers: dict[str, Logger] = {}


def get_logger(agent_id: str, *, config: Config | None = None) -> Logger:
    """Get or create a Logger for the given agent/component ID.

    Loggers are cached per agent_id. Pass config= to override (tests).
    """
    if config is not None:
        # Don't cache test loggers
        return Logger(agent_id, config=config)

    if agent_id not in _loggers:
        _loggers[agent_id] = Logger(agent_id)
    return _loggers[agent_id]


def reset_loggers() -> None:
    """Clear the logger cache. Used in tests."""
    _loggers.clear()
