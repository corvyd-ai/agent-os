"""Backward-compatibility shim — imports from agent_os.registry.

This module existed as agents.py in the original runtime. All functionality
has moved to agent_os.registry. This re-export ensures existing code that does
``from agent_os.agents import ...`` keeps working.

Migration: replace ``agent_os.agents`` with ``agent_os.registry`` in your imports.
"""

from .registry import *  # noqa: F403
from .registry import _find_registry_file, _parse_frontmatter  # noqa: F401
