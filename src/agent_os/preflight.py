"""agent-os pre-flight health gate — validate agent can operate before starting.

Runs quick checks before each agent cycle to catch problems that would cause
silent repeated failures (e.g., permission errors from root-owned files).

Uses real write probes (create + delete temp file) instead of os.access()
because the latter lies with NFS, ACLs, and SELinux.

Scope: preflight runs every cycle, so it must be *capability* checks only
(can I actually perform the operations I need?). Heuristic checks like
"do files have the expected owner" belong in ``agent-os doctor``, where a
human can evaluate the result — preflight blocking on a heuristic false
positive produces the same silent-loop failure mode it's meant to prevent.

Usage:
    from agent_os.preflight import run_preflight

    result = run_preflight("agent-001-builder", config=cfg)
    if not result.passed:
        for check in result.failed_checks:
            print(f"FAILED: {check.name} — {check.detail}")
            print(f"  Fix: {check.fix_suggestion}")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, get_config


@dataclass
class PreflightCheck:
    """Result of a single pre-flight check."""

    name: str
    passed: bool
    detail: str = ""
    fix_suggestion: str = ""


@dataclass
class PreflightResult:
    """Aggregated result of all pre-flight checks."""

    checks: list[PreflightCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed_checks(self) -> list[PreflightCheck]:
        return [c for c in self.checks if not c.passed]

    @property
    def summary(self) -> str:
        """One-line summary of failures for logging."""
        if self.passed:
            return "All pre-flight checks passed"
        return "; ".join(c.detail for c in self.failed_checks)


def _probe_writable(directory: Path) -> PreflightCheck:
    """Test if a directory is writable by creating and deleting a temp file."""
    name = f"write_{directory.name}"
    probe = directory / ".preflight-probe"

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return PreflightCheck(
            name=name,
            passed=False,
            detail=f"Cannot create directory {directory}: {e}",
            fix_suggestion=f"sudo mkdir -p {directory} && sudo chown $(whoami) {directory}",
        )

    try:
        probe.write_text("preflight")
        probe.unlink()
        return PreflightCheck(name=name, passed=True)
    except OSError as e:
        return PreflightCheck(
            name=name,
            passed=False,
            detail=f"Cannot write to {directory}: {e}",
            fix_suggestion=f"sudo chown -R $(whoami) {directory}",
        )


def run_preflight(agent_id: str, *, config: Config | None = None) -> PreflightResult:
    """Run all pre-flight checks for an agent.

    Validates via *capability* probes that the agent can write to its
    operational directories. Heuristic checks (e.g., file ownership) are
    deliberately excluded — they belong in ``agent-os doctor`` where a
    human can evaluate the result. A per-cycle heuristic that misfires
    silently blocks the scheduler, the exact failure mode preflight exists
    to prevent.
    """
    cfg = config or get_config()
    result = PreflightResult()

    # Directories the agent needs to write to
    write_dirs = [
        cfg.tasks_queued,
        cfg.tasks_in_progress,
        cfg.tasks_done,
        cfg.tasks_failed,
        cfg.logs_dir / agent_id,
        cfg.messages_dir / agent_id / "inbox",
        cfg.agents_state_dir / agent_id,
    ]

    for d in write_dirs:
        result.checks.append(_probe_writable(d))

    return result
