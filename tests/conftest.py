"""Shared fixtures for AIOS runtime tests.

Two fixture approaches:
1. aios_fs — legacy monkeypatch approach (patches module attributes)
2. aios_config — Config-based approach (explicit Config with tmp_path root)

Both create the same directory tree. New tests should prefer aios_config.
"""

from pathlib import Path

import pytest

from agent_os import agents, aios, config
from agent_os.config import Config, configure

# Every config path constant that needs to be redirected into the temp tree.
_CONFIG_PATH_NAMES = [
    "COMPANY_ROOT",
    "AGENTS_DIR",
    "REGISTRY_DIR",
    "TASKS_DIR",
    "MESSAGES_DIR",
    "LOGS_DIR",
    "COSTS_DIR",
    "TASKS_QUEUED",
    "TASKS_IN_PROGRESS",
    "TASKS_IN_REVIEW",
    "TASKS_DONE",
    "TASKS_FAILED",
    "TASKS_DECLINED",
    "AGENTS_STATE_DIR",
    "PROPOSALS_ACTIVE",
    "PROPOSALS_DECIDED",
    "DRIVES_FILE",
    "VALUES_FILE",
    "BROADCAST_DIR",
    "THREADS_DIR",
]


def _build_dir_tree(root: Path) -> dict[str, Path]:
    """Build the AIOS directory tree under root and return a path map."""
    paths = {
        "COMPANY_ROOT": root,
        "AGENTS_DIR": root / "agents",
        "REGISTRY_DIR": root / "agents" / "registry",
        "TASKS_DIR": root / "agents" / "tasks",
        "MESSAGES_DIR": root / "agents" / "messages",
        "LOGS_DIR": root / "agents" / "logs",
        "COSTS_DIR": root / "finance" / "costs",
        "TASKS_QUEUED": root / "agents" / "tasks" / "queued",
        "TASKS_IN_PROGRESS": root / "agents" / "tasks" / "in-progress",
        "TASKS_IN_REVIEW": root / "agents" / "tasks" / "in-review",
        "TASKS_DONE": root / "agents" / "tasks" / "done",
        "TASKS_FAILED": root / "agents" / "tasks" / "failed",
        "TASKS_DECLINED": root / "agents" / "tasks" / "declined",
        "AGENTS_STATE_DIR": root / "agents" / "state",
        "PROPOSALS_ACTIVE": root / "strategy" / "proposals" / "active",
        "PROPOSALS_DECIDED": root / "strategy" / "proposals" / "decided",
        "DRIVES_FILE": root / "strategy" / "drives.md",
        "VALUES_FILE": root / "identity" / "values.md",
        "BROADCAST_DIR": root / "agents" / "messages" / "broadcast",
        "THREADS_DIR": root / "agents" / "messages" / "threads",
    }

    for name, p in paths.items():
        if name.endswith("_FILE"):
            p.parent.mkdir(parents=True, exist_ok=True)
        else:
            p.mkdir(parents=True, exist_ok=True)

    return paths


@pytest.fixture
def aios_fs(tmp_path, monkeypatch):
    """Create a complete temp AIOS filesystem and patch all path constants.

    Legacy fixture — patches constants in BOTH config.py AND every module that
    does ``from .config import X``. Also installs a Config singleton so
    Config-aware code sees the same tree.
    """
    root = tmp_path / "company"
    paths = _build_dir_tree(root)

    # Install a Config singleton pointing at the temp root
    cfg = Config(company_root=root)
    configure(cfg)

    # Patch in config module AND in every consumer module.
    _consumer_modules = [aios, agents]

    for name in _CONFIG_PATH_NAMES:
        value = paths[name]
        monkeypatch.setattr(config, name, value)
        for mod in _consumer_modules:
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, value)

    yield paths

    # Reset the singleton so other tests aren't affected
    configure(Config())


@pytest.fixture
def aios_config(tmp_path):
    """Create a temp AIOS filesystem and return a Config object.

    Preferred fixture for new tests. Uses explicit Config passing instead
    of monkeypatching. Does NOT modify the global singleton.
    """
    root = tmp_path / "company"
    _build_dir_tree(root)
    return Config(company_root=root)
