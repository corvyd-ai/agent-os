"""Shim — metrics moved to agent_os.metrics in phase 1 of the CLI-first rework.

This module stays as a thin re-export so existing dashboard routers keep
importing from `..metrics` without change. The dashboard itself is slated
for removal in phase 3; this file disappears with it.
"""

from agent_os.metrics import (
    AGENT_ALIASES,
    compute_agent_health,
    compute_all_health,
    compute_autonomy,
    compute_effectiveness,
    compute_efficiency,
    compute_governance,
    compute_health_with_trends,
    compute_system_health,
)

__all__ = [
    "AGENT_ALIASES",
    "compute_agent_health",
    "compute_all_health",
    "compute_autonomy",
    "compute_effectiveness",
    "compute_efficiency",
    "compute_governance",
    "compute_health_with_trends",
    "compute_system_health",
]
