"""Pollers — background integrations that sync external state into the artifact store.

Each poller queries an external service for artifact status changes and returns
``PollResult`` objects. Pollers do NOT write to disk; the caller feeds results
into the artifact store (layer 2). This separation is the layer-2/layer-3 seam.

The Operator's health-check bridge (task-2026-0504-002) can use the same
``PollResult`` protocol to feed monitoring events into the artifact store.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PollResult:
    """Result of polling a single artifact.

    Returned by layer-3 pollers.  The caller (CLI ``poll`` command or
    scheduler hook) passes these to ``artifacts.record_transition()``.

    Attributes:
        task_id: the task this artifact belongs to
        new_state: target state, or None if nothing changed
        detail: provider-specific metadata (merge_sha, ci_status, etc.)
        error: non-None when the poll failed for this artifact
    """

    task_id: str
    new_state: str | None = None
    detail: dict = field(default_factory=dict)
    error: str | None = None
