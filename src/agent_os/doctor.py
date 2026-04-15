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
import pwd
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

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


def _resolve_runtime_user(cfg: Config, override: str | None = None) -> tuple[str, int | None, str]:
    """Resolve the runtime user to a (name, uid, source) triple.

    Resolution order:
      1. ``override`` argument (e.g., from --runtime-user flag)
      2. ``cfg.runtime_user`` (from TOML)
      3. The invoking user (``os.getuid()``)

    ``uid`` may be None if a username was configured but doesn't resolve
    on this host — in that case the caller should degrade gracefully.
    The ``source`` string indicates where the value came from, for display.
    """
    if override:
        try:
            return override, pwd.getpwnam(override).pw_uid, "--runtime-user"
        except KeyError:
            return override, None, "--runtime-user"
    if cfg.runtime_user:
        try:
            return cfg.runtime_user, pwd.getpwnam(cfg.runtime_user).pw_uid, "config runtime_user"
        except KeyError:
            return cfg.runtime_user, None, "config runtime_user"
    uid = os.getuid()
    try:
        name = pwd.getpwuid(uid).pw_name
    except KeyError:
        name = str(uid)
    return name, uid, "invoking user"


def _check_file_permissions(cfg: Config, runtime_user_override: str | None = None) -> DiagnosticCheck:
    """Check ownership consistency across agent directories.

    Uses the configured runtime user when set (the account the scheduler
    runs as in production), falling back to the invoking user only if
    nothing is configured. This avoids the foot-gun where ``agent-os doctor``
    run by a human as root on a systemd deployment reports every
    service-owned file as "wrong" and recommends chowning everything to
    root — which would immediately re-break the scheduler.
    """
    user_name, user_uid, source = _resolve_runtime_user(cfg, runtime_user_override)

    if user_uid is None:
        return DiagnosticCheck(
            name="File permissions",
            status="warning",
            detail=f"Runtime user {user_name!r} ({source}) does not exist on this host — skipping ownership check",
            fix='Set [runtime] user = "<actual-service-account>" in agent-os.toml',
        )

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
                    if st.st_uid != user_uid:
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
            detail=f"{len(mismatched)} files not owned by runtime user {user_name!r} (uid {user_uid}, from {source}): {', '.join(examples)}{extra}",
            fix=f"sudo chown -R {user_name} {cfg.company_root}",
        )
    return DiagnosticCheck(
        name="File permissions",
        status="ok",
        detail=f"All files owned by runtime user {user_name!r} (uid {user_uid}, from {source})",
    )


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


def _env_file_has_key(path: Path, key: str) -> bool:
    """Check if a KEY=... or KEY="..." line exists in an env-style file."""
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            # Handle `KEY=...`, `KEY =...`, and systemd's `Environment="KEY=..."` forms
            if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
                return True
            if line.startswith(f'Environment="{key}=') or line.startswith(f"Environment='{key}="):
                return True
            if line.startswith(f"Environment={key}="):
                return True
    except OSError:
        pass
    return False


def _check_api_key(cfg: Config) -> DiagnosticCheck:
    """Check that ANTHROPIC_API_KEY is configured somewhere the scheduler will see it.

    Checks, in order:
      1. os.environ (the invoking shell)
      2. cfg.runtime_env_file if set (e.g., a systemd EnvironmentFile)
      3. <company_root>/.env

    A human SSHing in as root won't have the systemd env loaded, so
    falling back to .env / the configured env_file avoids a false positive.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        return DiagnosticCheck(name="API key", status="ok", detail="ANTHROPIC_API_KEY set in environment")

    candidates: list[Path] = []
    if cfg.runtime_env_file:
        env_path = Path(cfg.runtime_env_file)
        if not env_path.is_absolute():
            env_path = cfg.company_root / env_path
        candidates.append(env_path)
    candidates.append(cfg.company_root / ".env")

    for candidate in candidates:
        if candidate.exists() and _env_file_has_key(candidate, "ANTHROPIC_API_KEY"):
            return DiagnosticCheck(
                name="API key",
                status="ok",
                detail=f"ANTHROPIC_API_KEY found in {candidate}",
            )

    return DiagnosticCheck(
        name="API key",
        status="error",
        detail="ANTHROPIC_API_KEY not found in environment, runtime_env_file, or .env",
        fix="export ANTHROPIC_API_KEY=sk-ant-... (or add to .env, or set [runtime] env_file)",
    )


def _check_scheduler(cfg: Config) -> DiagnosticCheck:
    """Check if the agent-os scheduler is installed (crontab or systemd timer).

    Deployments may use either crontab (``agent-os cron install``) or a
    systemd timer (common for service-account deployments). We consider
    the check OK if either is present.
    """
    # Try crontab first
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and "agent-os" in result.stdout:
            return DiagnosticCheck(name="Scheduler", status="ok", detail="agent-os found in crontab")
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    # Try systemd timers (user and system)
    for systemctl_args in (["systemctl", "--user", "list-timers", "--all"], ["systemctl", "list-timers", "--all"]):
        try:
            result = subprocess.run(systemctl_args, capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and "agent-os" in result.stdout.lower():
                scope = "user" if "--user" in systemctl_args else "system"
                return DiagnosticCheck(
                    name="Scheduler",
                    status="ok",
                    detail=f"agent-os found in systemd timers ({scope} scope)",
                )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue

    # Neither found — this is just a warning, not an error: the user may
    # be driving the scheduler manually or via another mechanism.
    return DiagnosticCheck(
        name="Scheduler",
        status="warning",
        detail="agent-os not found in crontab or systemd timers",
        fix="agent-os cron install  (or configure a systemd timer)",
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


def run_doctor(
    *,
    config: Config | None = None,
    verbose: bool = False,
    runtime_user: str | None = None,
) -> DoctorResult:
    """Run all diagnostic checks and return the aggregated result.

    ``runtime_user`` (optional) overrides ``cfg.runtime_user`` — passed in
    from the CLI's ``--runtime-user`` flag. Used by the ownership check to
    compare files against the correct account on systemd deployments.
    """
    cfg = config or get_config()
    result = DoctorResult()

    result.checks.append(_check_directory_structure(cfg))
    result.checks.append(_check_file_permissions(cfg, runtime_user))
    result.checks.append(_check_write_probes(cfg))
    result.checks.append(_check_config(cfg))
    result.checks.append(_check_agent_registry(cfg))
    result.checks.append(_check_task_consistency(cfg))
    result.checks.append(_check_circuit_breakers(cfg))
    result.checks.append(_check_api_key(cfg))
    result.checks.append(_check_scheduler(cfg))
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
