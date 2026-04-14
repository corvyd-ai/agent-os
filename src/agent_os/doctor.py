"""agent-os doctor — comprehensive diagnostic health checks.

On-demand command for humans to run when something seems wrong. Validates
file permissions, directory structure, agent state, and configuration.

Usage:
    agent-os doctor           # Run all checks
    agent-os doctor --verbose # Show passing checks too

Programmatic:
    from agent_os.doctor import run_doctor, format_doctor_output

    result = run_doctor(config=cfg)
    if result.errors:
        print(format_doctor_output(result))
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime

from .config import Config, get_config


@dataclass
class DiagnosticCheck:
    """Result of a single diagnostic check."""

    name: str
    status: str  # "ok", "warning", "error"
    detail: str = ""
    fix: str = ""  # actionable fix command


@dataclass
class DoctorResult:
    """Aggregated results of all diagnostic checks."""

    checks: list[DiagnosticCheck] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for c in self.checks if c.status == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for c in self.checks if c.status == "warning")

    @property
    def ok_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "ok")


# --- Individual checks ---

EXPECTED_DIRS = [
    "agents/registry",
    "agents/state",
    "agents/tasks/queued",
    "agents/tasks/in-progress",
    "agents/tasks/in-review",
    "agents/tasks/done",
    "agents/tasks/failed",
    "agents/tasks/declined",
    "agents/tasks/backlog",
    "agents/messages/broadcast",
    "agents/messages/threads",
    "agents/logs",
    "strategy/decisions",
    "strategy/proposals/active",
    "strategy/proposals/decided",
    "identity",
    "finance/costs",
    "operations/scripts",
]


def _check_directory_structure(cfg: Config) -> DiagnosticCheck:
    """Verify all expected directories exist."""
    missing = []
    for d in EXPECTED_DIRS:
        path = cfg.company_root / d
        if not path.is_dir():
            missing.append(d)

    if missing:
        dirs_str = ", ".join(missing[:5])
        extra = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
        mkdir_cmds = " && ".join(f"mkdir -p {cfg.company_root / d}" for d in missing[:3])
        return DiagnosticCheck(
            name="Directory structure",
            status="error",
            detail=f"Missing directories: {dirs_str}{extra}",
            fix=mkdir_cmds,
        )
    return DiagnosticCheck(
        name="Directory structure", status="ok", detail=f"All {len(EXPECTED_DIRS)} directories present"
    )


def _check_file_permissions(cfg: Config) -> DiagnosticCheck:
    """Check ownership consistency across agent directories."""
    current_uid = os.getuid()
    mismatched: list[tuple[str, int]] = []

    dirs_to_check = [
        cfg.tasks_queued,
        cfg.tasks_in_progress,
        cfg.tasks_done,
        cfg.tasks_failed,
        cfg.tasks_backlog,
        cfg.agents_state_dir,
        cfg.logs_dir,
    ]

    for d in dirs_to_check:
        if not d.exists():
            continue
        try:
            for item in d.rglob("*"):
                try:
                    st = item.stat()
                    if st.st_uid != current_uid:
                        rel = item.relative_to(cfg.company_root)
                        mismatched.append((str(rel), st.st_uid))
                except OSError:
                    continue
        except OSError:
            continue

    if mismatched:
        examples = [f"{path} (uid {uid})" for path, uid in mismatched[:5]]
        extra = f" (+{len(mismatched) - 5} more)" if len(mismatched) > 5 else ""
        return DiagnosticCheck(
            name="File permissions",
            status="error",
            detail=f"{len(mismatched)} files with wrong ownership: {', '.join(examples)}{extra}",
            fix=f"sudo chown -R {current_uid} {cfg.company_root}",
        )
    return DiagnosticCheck(name="File permissions", status="ok", detail="All files owned by current user")


def _check_write_probes(cfg: Config) -> DiagnosticCheck:
    """Test that critical directories are writable."""
    from .preflight import _probe_writable

    dirs = [
        cfg.tasks_queued,
        cfg.tasks_in_progress,
        cfg.logs_dir,
    ]

    failures = []
    for d in dirs:
        probe = _probe_writable(d)
        if not probe.passed:
            failures.append(probe.detail)

    if failures:
        return DiagnosticCheck(
            name="Write permissions",
            status="error",
            detail="; ".join(failures),
            fix=f"sudo chown -R $(whoami) {cfg.company_root}",
        )
    return DiagnosticCheck(name="Write permissions", status="ok", detail="All critical directories writable")


def _check_agent_registry(cfg: Config) -> DiagnosticCheck:
    """Check registry consistency: each agent should have state/log/inbox dirs."""
    from .registry import list_agents

    agents = list_agents(config=cfg)
    if not agents:
        return DiagnosticCheck(name="Agent registry", status="warning", detail="No agents registered")

    issues = []
    for agent in agents:
        aid = agent.agent_id
        if not (cfg.agents_state_dir / aid).is_dir():
            issues.append(f"{aid}: missing state directory")
        if not (cfg.logs_dir / aid).is_dir():
            issues.append(f"{aid}: missing log directory")
        if not (cfg.messages_dir / aid / "inbox").is_dir():
            issues.append(f"{aid}: missing inbox directory")

    if issues:
        return DiagnosticCheck(
            name="Agent registry",
            status="warning",
            detail=f"{len(issues)} issue(s): {'; '.join(issues[:3])}",
            fix="Directories will be auto-created on next agent cycle",
        )
    return DiagnosticCheck(
        name="Agent registry",
        status="ok",
        detail=f"{len(agents)} agent(s) registered, all directories present",
    )


def _check_task_consistency(cfg: Config) -> DiagnosticCheck:
    """Check for tasks stuck in in-progress without recent activity."""
    stuck = []
    ip_dir = cfg.tasks_in_progress
    if not ip_dir.exists():
        return DiagnosticCheck(name="Task consistency", status="ok", detail="No in-progress tasks")

    for task_file in ip_dir.glob("*.md"):
        # Check if the task file hasn't been modified in 6 hours
        try:
            mtime = task_file.stat().st_mtime
            age_hours = (datetime.now().timestamp() - mtime) / 3600
            if age_hours > 6:
                stuck.append(f"{task_file.stem} ({age_hours:.0f}h old)")
        except OSError:
            continue

    if stuck:
        tasks_str = ", ".join(stuck[:3])
        extra = f" (+{len(stuck) - 3} more)" if len(stuck) > 3 else ""
        return DiagnosticCheck(
            name="Task consistency",
            status="warning",
            detail=f"{len(stuck)} task(s) stuck in in-progress: {tasks_str}{extra}",
            fix=f"mv {ip_dir}/<task>.md {cfg.tasks_failed}/",
        )
    return DiagnosticCheck(name="Task consistency", status="ok", detail="No stuck tasks")


def _check_circuit_breakers(cfg: Config) -> DiagnosticCheck:
    """Check for tripped failure circuit breakers."""
    from .circuit_breaker import check_breaker
    from .registry import list_agents

    agents = list_agents(config=cfg)
    tripped = []
    for agent in agents:
        state = check_breaker(agent.agent_id, config=cfg)
        if state.tripped:
            tripped.append(f"{agent.agent_id}: {state.reason}")

    if tripped:
        return DiagnosticCheck(
            name="Circuit breakers",
            status="error",
            detail=f"{len(tripped)} breaker(s) tripped: {'; '.join(tripped)}",
            fix="agent-os breaker reset <agent_id>  (or fix the underlying issue and wait for auto-reset)",
        )
    return DiagnosticCheck(name="Circuit breakers", status="ok", detail="No breakers tripped")


def _check_api_key() -> DiagnosticCheck:
    """Check that ANTHROPIC_API_KEY is configured."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return DiagnosticCheck(name="API key", status="ok", detail="ANTHROPIC_API_KEY is set")
    return DiagnosticCheck(
        name="API key",
        status="error",
        detail="ANTHROPIC_API_KEY not set",
        fix="export ANTHROPIC_API_KEY=sk-ant-... (or add to .env file)",
    )


def _check_cron(cfg: Config) -> DiagnosticCheck:
    """Check if agent-os tick is in the crontab."""
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and "agent-os" in result.stdout:
            return DiagnosticCheck(name="Cron", status="ok", detail="agent-os found in crontab")
        return DiagnosticCheck(
            name="Cron",
            status="warning",
            detail="agent-os not found in crontab",
            fix="agent-os cron install",
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return DiagnosticCheck(
            name="Cron",
            status="warning",
            detail="Could not check crontab",
        )


def _check_log_health(cfg: Config) -> DiagnosticCheck:
    """Check that logs are being written and aren't too large."""
    if not cfg.logs_dir.exists():
        return DiagnosticCheck(name="Log health", status="warning", detail="Log directory doesn't exist")

    today = datetime.now(cfg.tz).strftime("%Y-%m-%d")
    issues = []

    agent_dirs = [d for d in cfg.logs_dir.iterdir() if d.is_dir() and d.name != "system"]

    for agent_dir in agent_dirs:
        # Check today's log exists
        log_file = agent_dir / f"{today}.jsonl"
        if not log_file.exists():
            issues.append(f"{agent_dir.name}: no log for today")
            continue

        # Check file size
        try:
            size_mb = log_file.stat().st_size / (1024 * 1024)
            if size_mb > 50:
                issues.append(f"{agent_dir.name}: log is {size_mb:.0f}MB (>50MB)")
        except OSError:
            continue

    if issues:
        return DiagnosticCheck(
            name="Log health",
            status="warning",
            detail="; ".join(issues[:3]),
        )
    if not agent_dirs:
        return DiagnosticCheck(name="Log health", status="ok", detail="No agent log directories yet")
    return DiagnosticCheck(name="Log health", status="ok", detail=f"{len(agent_dirs)} agent(s) have logs")


def _check_config(cfg: Config) -> DiagnosticCheck:
    """Validate config sanity."""
    issues = []

    if cfg.daily_budget_cap_usd <= 0:
        issues.append("daily_budget_cap_usd <= 0")
    if cfg.weekly_budget_cap_usd <= 0:
        issues.append("weekly_budget_cap_usd <= 0")
    if not cfg.default_model:
        issues.append("default_model is empty")
    if cfg.schedule_cycles_interval_minutes < 1:
        issues.append("schedule cycle interval < 1 minute")

    if issues:
        return DiagnosticCheck(
            name="Config validation",
            status="warning",
            detail=f"Config issues: {'; '.join(issues)}",
        )
    return DiagnosticCheck(name="Config validation", status="ok", detail="Config looks valid")


# --- Main entry point ---


def run_doctor(*, config: Config | None = None, verbose: bool = False) -> DoctorResult:
    """Run all diagnostic checks and return the aggregated result."""
    cfg = config or get_config()
    result = DoctorResult()

    result.checks.append(_check_directory_structure(cfg))
    result.checks.append(_check_file_permissions(cfg))
    result.checks.append(_check_write_probes(cfg))
    result.checks.append(_check_config(cfg))
    result.checks.append(_check_agent_registry(cfg))
    result.checks.append(_check_task_consistency(cfg))
    result.checks.append(_check_circuit_breakers(cfg))
    result.checks.append(_check_api_key())
    result.checks.append(_check_cron(cfg))
    result.checks.append(_check_log_health(cfg))

    return result


def format_doctor_output(result: DoctorResult, *, no_color: bool = False, verbose: bool = False) -> str:
    """Format doctor results for terminal display."""
    use_color = not no_color and sys.stdout.isatty() and not os.environ.get("NO_COLOR")

    def _green(text: str) -> str:
        return f"\033[32m{text}\033[0m" if use_color else text

    def _yellow(text: str) -> str:
        return f"\033[33m{text}\033[0m" if use_color else text

    def _red(text: str) -> str:
        return f"\033[31m{text}\033[0m" if use_color else text

    lines = ["", "agent-os doctor", "=" * 40, ""]

    status_icons = {
        "ok": _green("[OK]     "),
        "warning": _yellow("[WARNING]"),
        "error": _red("[ERROR]  "),
    }

    for check in result.checks:
        if check.status == "ok" and not verbose:
            continue

        icon = status_icons.get(check.status, "[???]    ")
        lines.append(f"  {icon}  {check.name}")
        if check.detail:
            lines.append(f"             {check.detail}")
        if check.fix:
            lines.append(f"             Fix: {check.fix}")
        lines.append("")

    # Always show passing count
    if not verbose:
        lines.append(
            f"  {_green(f'{result.ok_count} checks passed')}",
        )

    lines.append(f"  {result.ok_count} passed, {result.warnings} warning(s), {result.errors} error(s)")
    lines.append("")

    return "\n".join(lines)
