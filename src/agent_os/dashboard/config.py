"""Dashboard configuration — re-exports from agent_os.config.

Provides the same interface as the original dashboard config module
(uppercase constants, helper functions) backed by the platform Config.
Routers import from here without needing to change.
"""

from datetime import datetime

from agent_os.config import Config as _Config
from agent_os.config import configure as _configure
from agent_os.config import get_config

# Auto-discover config from TOML when running standalone (e.g. uvicorn).
# This runs at import time, before any router resolves its imports.
_cfg = get_config()
if _cfg.company_name == "My Company":  # still using defaults
    _toml = _Config.discover_toml()
    if _toml:
        _configure(_Config.from_toml(_toml))
    del _toml
del _cfg


# --- Helper functions ---


def company_today() -> str:
    """Return today's date string in the company timezone (YYYY-MM-DD)."""
    return datetime.now(get_config().tz).strftime("%Y-%m-%d")


def company_date():
    """Return the current date object in the company timezone."""
    return datetime.now(get_config().tz).date()


# --- Static data ---

# Old agent ID aliases (agents renamed 2026-02-20)
AGENT_ALIASES = {
    "agent-000-chief-of-staff": "agent-000-steward",
    "agent-001-builder": "agent-001-maker",
    "agent-003-devops": "agent-003-operator",
    "agent-005-content": "agent-005-grower",
    "agent-006-product-manager": "agent-006-strategist",
}


# --- Lazy attribute access ---

_CONFIG_ATTR_MAP = {
    "COMPANY_ROOT": "company_root",
    "AGENTS_DIR": "agents_dir",
    "REGISTRY_DIR": "registry_dir",
    "AGENTS_STATE_DIR": "agents_state_dir",
    "LOGS_DIR": "logs_dir",
    "MESSAGES_DIR": "messages_dir",
    "COSTS_DIR": "costs_dir",
    "TASKS_DIR": "tasks_dir",
    "TASKS_QUEUED": "tasks_queued",
    "TASKS_IN_PROGRESS": "tasks_in_progress",
    "TASKS_IN_REVIEW": "tasks_in_review",
    "TASKS_DONE": "tasks_done",
    "TASKS_FAILED": "tasks_failed",
    "TASKS_DECLINED": "tasks_declined",
    "TASKS_BACKLOG": "tasks_backlog",
    "PROPOSALS_ACTIVE": "proposals_active",
    "PROPOSALS_DECIDED": "proposals_decided",
    "DRIVES_FILE": "drives_file",
    "BROADCAST_DIR": "broadcast_dir",
    "THREADS_DIR": "threads_dir",
    "FEEDBACK_DIR": "feedback_dir",
}


def __getattr__(name: str):
    cfg = get_config()

    # Direct Config property mapping
    attr = _CONFIG_ATTR_MAP.get(name)
    if attr is not None:
        return getattr(cfg, attr)

    # Derived paths not in the mapping
    if name == "DECISIONS_DIR":
        return cfg.decisions_dir
    if name == "STRATEGY_DIR":
        return cfg.strategy_dir
    if name == "HUMAN_INBOX":
        return cfg.human_inbox
    if name == "COMPANY_TZ":
        return cfg.tz
    if name == "CONVERSATIONS_DIR":
        return cfg.conversations_dir_resolved

    # Compound values
    if name == "TASK_STATUS_DIRS":
        return {
            "queued": cfg.tasks_queued,
            "in-progress": cfg.tasks_in_progress,
            "in-review": cfg.tasks_in_review,
            "done": cfg.tasks_done,
            "failed": cfg.tasks_failed,
            "declined": cfg.tasks_declined,
            "backlog": cfg.tasks_backlog,
        }

    if name == "AGENT_IDS":
        if cfg.dashboard_agent_ids:
            return list(cfg.dashboard_agent_ids)
        registry = cfg.registry_dir
        if registry.is_dir():
            return sorted(f.stem for f in registry.iterdir() if f.suffix == ".md")
        return []

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
