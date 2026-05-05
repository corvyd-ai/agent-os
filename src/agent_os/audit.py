"""`agent-os audit` — cross-reference filesystem state against primary sources.

Stewardship tool that verifies consistency between task files, GitHub PRs,
cost tracking, dispatch history, agent cognitive state, worktrees, and log
activity. Each check is independent and produces a pass/warn/fail verdict
with specific discrepancies.

Usage:
    agent-os audit --all              # Run everything
    agent-os audit --check-prs        # Just PR verification
    agent-os audit --check-dispatch   # Just dispatch freshness

Programmatic:
    from agent_os.audit import run_audit, format_audit_report

    report = run_audit(config=cfg, checks=["prs", "dispatch"])
    print(format_audit_report(report))
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from .config import Config, get_config
from .registry import list_agents

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class AuditFinding:
    """A single discrepancy or observation within a check."""

    level: str  # "pass", "warn", "fail"
    message: str


@dataclass
class AuditCheck:
    """Result of one audit check (e.g. --check-prs)."""

    name: str
    status: str  # "pass", "warn", "fail"
    findings: list[AuditFinding] = field(default_factory=list)
    summary: str = ""


@dataclass
class AuditReport:
    """Aggregated results from all requested checks."""

    timestamp: str
    checks: list[AuditCheck] = field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "pass")

    @property
    def warn_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "warn")

    @property
    def fail_count(self) -> int:
        return sum(1 for c in self.checks if c.status == "fail")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_CHECKS = ["prs", "budget", "dispatch", "freshness", "worktrees", "stale_tasks"]


def _parse_task_frontmatter(path: Path) -> dict:
    """Extract YAML frontmatter from a task file."""
    try:
        text = path.read_text()
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}


def _worst_status(findings: list[AuditFinding]) -> str:
    """Return the worst level across findings."""
    if any(f.level == "fail" for f in findings):
        return "fail"
    if any(f.level == "warn" for f in findings):
        return "warn"
    return "pass"


def _age_hours(path: Path) -> float:
    """Hours since a file was last modified."""
    try:
        mtime = path.stat().st_mtime
        return (datetime.now().timestamp() - mtime) / 3600
    except OSError:
        return float("inf")


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_prs(config: Config) -> AuditCheck:
    """For workspace SDLC tasks in done/, verify a PR exists on GitHub.

    Uses `gh pr list` to find PRs whose branch matches `agent/{task-id}`.
    Gracefully degrades when `gh` is unavailable or not authenticated.
    """
    findings: list[AuditFinding] = []

    # Fast-exit: if workspace SDLC isn't configured, no PRs to check
    if not config.project_enabled:
        return AuditCheck(
            name="PR verification",
            status="pass",
            findings=[AuditFinding("pass", "No workspace SDLC configured — nothing to check")],
            summary="N/A: workspace SDLC not configured",
        )

    done_dir = config.tasks_done
    if not done_dir.exists():
        return AuditCheck(
            name="PR verification",
            status="pass",
            findings=[AuditFinding("pass", "No done tasks directory")],
            summary="No done tasks",
        )

    # Collect done tasks that look like workspace-SDLC tasks
    workspace_tasks: list[tuple[str, Path]] = []
    for task_file in sorted(done_dir.glob("*.md")):
        meta = _parse_task_frontmatter(task_file)
        task_id = meta.get("id", task_file.stem)
        # Workspace tasks are assigned to builder-role agents
        assigned = meta.get("assigned_to", "")
        if assigned and assigned != "human":
            workspace_tasks.append((task_id, task_file))

    if not workspace_tasks:
        return AuditCheck(
            name="PR verification",
            status="pass",
            findings=[AuditFinding("pass", "No workspace SDLC tasks in done/")],
            summary="No workspace tasks to verify",
        )

    # Check gh CLI availability (only when we actually need it)
    try:
        gh_auth = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if gh_auth.returncode != 0:
            return AuditCheck(
                name="PR verification",
                status="warn",
                findings=[AuditFinding("warn", "GitHub CLI not authenticated — skipping PR check")],
                summary="Skipped: gh auth not configured",
            )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return AuditCheck(
            name="PR verification",
            status="warn",
            findings=[AuditFinding("warn", "GitHub CLI (gh) not available — skipping PR check")],
            summary="Skipped: gh not installed",
        )

    # Batch-query PRs — get all open and merged PRs
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--state", "all", "--limit", "200", "--json", "headRefName,state,url"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return AuditCheck(
                name="PR verification",
                status="warn",
                findings=[AuditFinding("warn", f"gh pr list failed: {result.stderr.strip()}")],
                summary="Skipped: gh pr list failed",
            )
        prs = json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        return AuditCheck(
            name="PR verification",
            status="warn",
            findings=[AuditFinding("warn", f"Failed to query PRs: {e}")],
            summary="Skipped: PR query failed",
        )

    # Build set of branch names that have PRs
    pr_branches = {pr.get("headRefName", "") for pr in prs}

    missing_pr: list[str] = []
    found_pr = 0
    for task_id, _ in workspace_tasks:
        branch = f"agent/{task_id}"
        if branch in pr_branches:
            found_pr += 1
        else:
            missing_pr.append(task_id)

    for task_id in missing_pr:
        findings.append(AuditFinding("warn", f"Task {task_id} in done/ has no PR for branch agent/{task_id}"))

    if found_pr:
        findings.append(AuditFinding("pass", f"{found_pr} task(s) have matching PRs"))

    status = _worst_status(findings) if findings else "pass"
    summary = f"{found_pr} verified, {len(missing_pr)} missing PRs" if workspace_tasks else "No tasks"
    return AuditCheck(name="PR verification", status=status, findings=findings, summary=summary)


def check_budget(config: Config) -> AuditCheck:
    """Compare cost JSONL totals against scheduler-state.json budget snapshot."""
    findings: list[AuditFinding] = []

    # Read scheduler state budget
    state_file = config.scheduler_state_file
    state_budget: dict | None = None
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            state_budget = state.get("budget", {})
        except (json.JSONDecodeError, OSError):
            findings.append(AuditFinding("warn", "Could not parse scheduler-state.json"))

    # Compute actual daily cost from JSONL
    today = datetime.now(config.tz).strftime("%Y-%m-%d")
    cost_file = config.costs_dir / f"{today}.jsonl"
    actual_daily = 0.0
    entry_count = 0
    if cost_file.exists():
        try:
            for line in cost_file.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    actual_daily += entry.get("cost_usd", 0.0)
                    entry_count += 1
                except json.JSONDecodeError:
                    continue
        except OSError:
            findings.append(AuditFinding("warn", f"Could not read cost file: {cost_file.name}"))

    findings.append(AuditFinding("pass", f"Cost JSONL: ${actual_daily:.2f} from {entry_count} entries today"))

    if state_budget:
        state_daily = state_budget.get("daily_spent", 0.0)
        state_cap = state_budget.get("daily_cap", 0.0)
        delta = abs(actual_daily - state_daily)

        findings.append(AuditFinding("pass", f"Scheduler state: ${state_daily:.2f} / ${state_cap:.2f} daily cap"))

        # Allow small float drift (< $0.10)
        if delta > 0.10:
            findings.append(
                AuditFinding(
                    "warn",
                    f"Budget discrepancy: JSONL=${actual_daily:.2f} vs state=${state_daily:.2f} (delta=${delta:.2f})",
                )
            )
    else:
        if state_file.exists():
            findings.append(AuditFinding("warn", "Scheduler state has no budget data"))
        else:
            findings.append(AuditFinding("warn", "No scheduler-state.json found"))

    status = _worst_status(findings) if findings else "pass"
    return AuditCheck(name="Budget consistency", status=status, findings=findings, summary=f"${actual_daily:.2f} today")


def check_dispatch(config: Config) -> AuditCheck:
    """Show last dispatch time per agent. Flag agents with no dispatch in >24h."""
    findings: list[AuditFinding] = []

    agents = list_agents(config=config)
    if not agents:
        return AuditCheck(
            name="Dispatch freshness",
            status="pass",
            findings=[AuditFinding("pass", "No agents registered")],
            summary="No agents",
        )

    # Read scheduler state for last dispatches
    state_file = config.scheduler_state_file
    if not state_file.exists():
        return AuditCheck(
            name="Dispatch freshness",
            status="warn",
            findings=[AuditFinding("warn", "No scheduler-state.json — cannot determine dispatch times")],
            summary="No scheduler state",
        )

    # Scan recent log files for dispatch records per agent
    now = datetime.now(config.tz)
    agent_last_dispatch: dict[str, str] = {}

    for agent in agents:
        aid = agent.agent_id
        log_dir = config.logs_dir / aid
        if not log_dir.exists():
            continue

        # Check today and yesterday's logs
        for days_back in range(2):
            date_str = (now - __import__("datetime").timedelta(days=days_back)).strftime("%Y-%m-%d")
            log_file = log_dir / f"{date_str}.jsonl"
            if not log_file.exists():
                continue
            try:
                for line in log_file.read_text().splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        # Look for cycle_start or any dispatch indicator
                        ts = entry.get("ts", "")
                        action = entry.get("action", "")
                        if action in ("cycle_start", "dispatch_start", "task_claimed"):
                            agent_last_dispatch[aid] = max(agent_last_dispatch.get(aid, ""), ts)
                    except json.JSONDecodeError:
                        continue
            except OSError:
                continue

    stale_agents = []
    agent_skip_ids = {"human"}  # skip pseudo-agents

    for agent in agents:
        aid = agent.agent_id
        if aid in agent_skip_ids:
            continue

        last = agent_last_dispatch.get(aid)
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                hours_ago = (
                    now - last_dt.replace(tzinfo=now.tzinfo if last_dt.tzinfo is None else last_dt.tzinfo)
                ).total_seconds() / 3600
                if hours_ago > 24:
                    stale_agents.append(aid)
                    findings.append(AuditFinding("warn", f"{aid}: last dispatch {hours_ago:.1f}h ago"))
                else:
                    findings.append(AuditFinding("pass", f"{aid}: last dispatch {hours_ago:.1f}h ago"))
            except (ValueError, TypeError):
                findings.append(AuditFinding("warn", f"{aid}: unparseable dispatch timestamp"))
        else:
            stale_agents.append(aid)
            findings.append(AuditFinding("warn", f"{aid}: no dispatch found in last 48h of logs"))

    status = _worst_status(findings) if findings else "pass"
    summary = f"{len(stale_agents)} stale" if stale_agents else "All agents dispatched recently"
    return AuditCheck(name="Dispatch freshness", status=status, findings=findings, summary=summary)


def check_freshness(config: Config) -> AuditCheck:
    """Show last-modified time for each agent's working-memory.md. Flag stale state."""
    findings: list[AuditFinding] = []

    agents = list_agents(config=config)
    if not agents:
        return AuditCheck(
            name="Cognitive freshness",
            status="pass",
            findings=[AuditFinding("pass", "No agents registered")],
            summary="No agents",
        )

    stale = []
    for agent in agents:
        aid = agent.agent_id
        wm_path = config.agents_state_dir / aid / "working-memory.md"
        if not wm_path.exists():
            findings.append(AuditFinding("warn", f"{aid}: no working-memory.md"))
            stale.append(aid)
            continue

        hours = _age_hours(wm_path)
        if hours > 48 or hours > 24:
            findings.append(AuditFinding("warn", f"{aid}: working memory {hours:.0f}h old"))
            stale.append(aid)
        else:
            findings.append(AuditFinding("pass", f"{aid}: working memory {hours:.1f}h old"))

    status = _worst_status(findings) if findings else "pass"
    summary = f"{len(stale)} stale" if stale else "All agents have fresh cognitive state"
    return AuditCheck(name="Cognitive freshness", status=status, findings=findings, summary=summary)


def check_worktrees(config: Config) -> AuditCheck:
    """List .worktrees/ and compare against active tasks. Flag dead worktrees."""
    findings: list[AuditFinding] = []

    wt_root = config.worktrees_root
    if not wt_root.exists():
        return AuditCheck(
            name="Worktree hygiene",
            status="pass",
            findings=[AuditFinding("pass", "No .worktrees/ directory")],
            summary="No worktrees",
        )

    # Collect active worktrees (skip _archive)
    active_worktrees: list[str] = []
    for entry in sorted(wt_root.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("_"):
            continue
        active_worktrees.append(entry.name)

    if not active_worktrees:
        return AuditCheck(
            name="Worktree hygiene",
            status="pass",
            findings=[AuditFinding("pass", "No active worktrees")],
            summary="Clean",
        )

    # Check which worktrees have corresponding in-progress tasks
    ip_dir = config.tasks_in_progress
    in_progress_ids: set[str] = set()
    if ip_dir.exists():
        for f in ip_dir.glob("*.md"):
            in_progress_ids.add(f.stem)

    dead = []
    for wt_name in active_worktrees:
        # Worktree name is the task-id
        if wt_name in in_progress_ids:
            findings.append(AuditFinding("pass", f"{wt_name}: has matching in-progress task"))
        else:
            dead.append(wt_name)
            findings.append(AuditFinding("warn", f"{wt_name}: no corresponding in-progress task (dead worktree)"))

    status = _worst_status(findings) if findings else "pass"
    summary = f"{len(dead)} dead worktrees" if dead else f"{len(active_worktrees)} worktrees, all active"
    return AuditCheck(name="Worktree hygiene", status=status, findings=findings, summary=summary)


def check_stale_tasks(config: Config, *, threshold_hours: float = 6.0) -> AuditCheck:
    """Flag tasks in in-progress/ for >N hours with no corresponding log activity."""
    findings: list[AuditFinding] = []

    ip_dir = config.tasks_in_progress
    if not ip_dir.exists():
        return AuditCheck(
            name="Stale tasks",
            status="pass",
            findings=[AuditFinding("pass", "No in-progress directory")],
            summary="No in-progress tasks",
        )

    tasks = list(ip_dir.glob("*.md"))
    if not tasks:
        return AuditCheck(
            name="Stale tasks",
            status="pass",
            findings=[AuditFinding("pass", "No tasks in progress")],
            summary="No in-progress tasks",
        )

    now = datetime.now(config.tz)
    stale = []

    for task_file in sorted(tasks):
        task_id = task_file.stem
        meta = _parse_task_frontmatter(task_file)
        assigned = meta.get("assigned_to", "")

        file_age_hours = _age_hours(task_file)

        if file_age_hours < threshold_hours:
            findings.append(AuditFinding("pass", f"{task_id}: {file_age_hours:.1f}h old (under threshold)"))
            continue

        # Check for recent log activity from the assigned agent
        has_recent_activity = False
        if assigned and assigned != "human":
            log_dir = config.logs_dir / assigned
            if log_dir.exists():
                date_str = now.strftime("%Y-%m-%d")
                log_file = log_dir / f"{date_str}.jsonl"
                if log_file.exists():
                    try:
                        for line in log_file.read_text().splitlines():
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                entry = json.loads(line)
                                refs = entry.get("refs", {})
                                if isinstance(refs, dict) and refs.get("task") == task_id:
                                    has_recent_activity = True
                                    break
                            except json.JSONDecodeError:
                                continue
                    except OSError:
                        pass

        if has_recent_activity:
            findings.append(AuditFinding("pass", f"{task_id}: {file_age_hours:.1f}h old but has recent log activity"))
        else:
            stale.append(task_id)
            detail = f"{task_id}: {file_age_hours:.0f}h old, no recent log activity"
            if assigned:
                detail += f" (assigned to {assigned})"
            findings.append(AuditFinding("warn", detail))

    status = _worst_status(findings) if findings else "pass"
    summary = f"{len(stale)} stale tasks" if stale else f"{len(tasks)} in-progress, all active"
    return AuditCheck(name="Stale tasks", status=status, findings=findings, summary=summary)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_audit(
    *,
    config: Config | None = None,
    checks: list[str] | None = None,
    stale_task_hours: float = 6.0,
) -> AuditReport:
    """Run requested audit checks and return the report.

    ``checks`` is a list of check names from ALL_CHECKS.
    If None or empty, runs all checks.
    """
    cfg = config or get_config()
    run_checks = checks if checks else list(ALL_CHECKS)

    now = datetime.now(cfg.tz)
    report = AuditReport(timestamp=now.isoformat())

    dispatch_table: dict[str, callable] = {
        "prs": lambda: check_prs(cfg),
        "budget": lambda: check_budget(cfg),
        "dispatch": lambda: check_dispatch(cfg),
        "freshness": lambda: check_freshness(cfg),
        "worktrees": lambda: check_worktrees(cfg),
        "stale_tasks": lambda: check_stale_tasks(cfg, threshold_hours=stale_task_hours),
    }

    for name in run_checks:
        fn = dispatch_table.get(name)
        if fn:
            report.checks.append(fn())

    return report


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

_STATUS_ORDER = {"pass": 0, "warn": 1, "fail": 2}


def format_audit_report(report: AuditReport, *, no_color: bool = False) -> str:
    """Format audit results for terminal display.

    Clean enough to quote in blog posts — avoids box-drawing characters
    and uses simple ASCII alignment.
    """
    use_color = not no_color and sys.stdout.isatty() and not os.environ.get("NO_COLOR")

    def _green(text: str) -> str:
        return f"\033[32m{text}\033[0m" if use_color else text

    def _yellow(text: str) -> str:
        return f"\033[33m{text}\033[0m" if use_color else text

    def _red(text: str) -> str:
        return f"\033[31m{text}\033[0m" if use_color else text

    def _bold(text: str) -> str:
        return f"\033[1m{text}\033[0m" if use_color else text

    def _status_icon(status: str) -> str:
        if status == "pass":
            return _green("PASS")
        elif status == "warn":
            return _yellow("WARN")
        else:
            return _red("FAIL")

    lines: list[str] = []
    lines.append("")
    lines.append(_bold("agent-os audit"))
    lines.append(f"  {report.timestamp}")
    lines.append("")

    for check in report.checks:
        icon = _status_icon(check.status)
        lines.append(f"  [{icon}] {check.name}")
        if check.summary:
            lines.append(f"         {check.summary}")
        lines.append("")

        for finding in check.findings:
            prefix = {
                "pass": _green("  +"),
                "warn": _yellow("  !"),
                "fail": _red("  x"),
            }.get(finding.level, "   ")
            lines.append(f"       {prefix} {finding.message}")

        lines.append("")

    # Summary line
    parts = []
    if report.pass_count:
        parts.append(_green(f"{report.pass_count} passed"))
    if report.warn_count:
        parts.append(_yellow(f"{report.warn_count} warnings"))
    if report.fail_count:
        parts.append(_red(f"{report.fail_count} failed"))
    lines.append(f"  {', '.join(parts)}")
    lines.append("")

    return "\n".join(lines)


def format_audit_json(report: AuditReport) -> str:
    """Format audit results as JSON."""
    data = {
        "timestamp": report.timestamp,
        "summary": {
            "pass": report.pass_count,
            "warn": report.warn_count,
            "fail": report.fail_count,
        },
        "checks": [],
    }

    for check in report.checks:
        check_data = {
            "name": check.name,
            "status": check.status,
            "summary": check.summary,
            "findings": [{"level": f.level, "message": f.message} for f in check.findings],
        }
        data["checks"].append(check_data)

    return json.dumps(data, indent=2)
