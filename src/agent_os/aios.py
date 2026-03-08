"""Backward-compatibility shim — imports from agent_os.core.

This module existed as aios.py in the original runtime. All functionality
has moved to agent_os.core. This re-export ensures existing code that does
``from agent_os import aios`` or ``from agent_os.aios import ...`` keeps working.

Migration: replace ``agent_os.aios`` with ``agent_os.core`` in your imports.
"""

from .core import *  # noqa: F403
from .core import (  # noqa: F401 — re-export private names used by tests/internals
    _deps_satisfied,
    _find_next_task,
    _move_task,
    _now_iso,
    _parse_frontmatter,
    _today,
    _write_frontmatter,
    create_task,
    get_autonomy_level,
    get_last_cadence,
    list_backlog,
    promote_task,
    reject_task,
)
