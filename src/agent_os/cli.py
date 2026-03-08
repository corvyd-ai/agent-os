"""agent-os CLI — the command-line interface for agent-os.

Provides subcommands for initializing, running, and managing agent companies.

Usage:
    agent-os init my-company          # Create a new company filesystem
    agent-os cycle agent-001          # Run one cycle (check tasks, messages, threads)
    agent-os run                      # Run all agents once (one cycle each)
    agent-os task agent-001 task-001  # Run a specific task
    agent-os standing-orders agent-001  # Run standing orders if due
    agent-os drives agent-001         # Run drive consultation
    agent-os dream agent-001          # Run dream cycle
    agent-os dashboard                # Launch the dashboard (coming soon)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# --- init command ---

# The canonical directory structure for a new company.
INIT_DIRS = [
    "agents/registry",
    "agents/state",
    "agents/tasks/queued",
    "agents/tasks/in-progress",
    "agents/tasks/in-review",
    "agents/tasks/done",
    "agents/tasks/failed",
    "agents/tasks/backlog",
    "agents/messages/broadcast",
    "agents/messages/threads",
    "agents/logs",
    "strategy/decisions",
    "strategy/proposals/active",
    "strategy/proposals/decided",
    "identity",
    "finance/costs",
    "products",
    "knowledge",
    "operations/scripts",
]


def cmd_init(args):
    """Create a new agent-os company filesystem."""
    name = args.name
    target = Path(name).resolve()

    if target.exists() and any(target.iterdir()):
        print(f"Error: directory '{name}' already exists and is not empty.")
        sys.exit(1)

    print(f"Creating agent-os company at {target}/")

    for d in INIT_DIRS:
        (target / d).mkdir(parents=True, exist_ok=True)

    # Write starter files
    (target / "identity" / "values.md").write_text(
        "# Values\n\n"
        "What does your company believe? Write your values here.\n"
        "These are injected into every agent prompt.\n"
    )

    (target / "identity" / "principles.md").write_text(
        "# Principles\n\n"
        "How does your company operate? Write your principles here.\n"
        "These guide agent decision-making.\n"
    )

    (target / "strategy" / "drives.md").write_text(
        "# Company Drives\n\n"
        "Drives are persistent goals that generate work.\n"
        "They never fully resolve — they create tension that agents act on.\n\n"
        "## Example Drive\n\n"
        "What is the most important thing right now? "
        "What tension exists between where you are and where you want to be?\n"
    )

    (target / "strategy" / "current-focus.md").write_text(
        "# Current Focus\n\n"
        "What is the company focused on right now?\n\n"
        "Write a short description of the current priority. "
        "Agents read this to understand context.\n"
    )

    print(f"""
Done! Your company is ready at {target}/

Next steps:
  cd {name}

  # Define your first agent:
  cat > agents/registry/agent-001-builder.md << 'EOF'
  ---
  id: agent-001-builder
  name: The Builder
  role: Software Engineer
  model: claude-sonnet-4-6
  ---

  I build software. I care about clean code, working tests, and shipping.
  EOF

  # Create a task:
  cat > agents/tasks/queued/task-001.md << 'EOF'
  ---
  id: task-001
  title: Write a hello world script
  assigned_to: agent-001-builder
  priority: medium
  ---

  Write a Python script that prints "Hello from agent-os."
  Write it to scripts/hello.py.
  EOF

  # Run your agent:
  export ANTHROPIC_API_KEY=your-key-here
  agent-os cycle agent-001-builder

  # Set up automatic scheduling:
  agent-os cron install
""")


# --- cycle command ---


def cmd_cycle(args):
    """Run one cycle for an agent: check tasks, messages, threads."""
    _set_root(args)
    from .runner import run_cycle

    asyncio.run(
        run_cycle(
            args.agent,
            max_turns=args.max_turns,
            max_budget_usd=args.max_budget,
        )
    )


# --- run command ---


def cmd_run(args):
    """Run one cycle for every registered agent."""
    _set_root(args)
    from .registry import list_agents
    from .runner import run_cycle

    agents = list_agents()
    if not agents:
        print("No agents found in agents/registry/. Define an agent first.")
        print("See: agent-os init --help")
        sys.exit(1)

    print(f"Running cycle for {len(agents)} agent(s)...")
    for agent in agents:
        print(f"\n{'=' * 60}")
        print(f"Agent: {agent.agent_id} ({agent.name})")
        print(f"{'=' * 60}")
        asyncio.run(
            run_cycle(
                agent.agent_id,
                max_turns=args.max_turns,
                max_budget_usd=args.max_budget,
            )
        )


# --- task command ---


def cmd_task(args):
    """Run a specific task for an agent."""
    _set_root(args)
    from .runner import run_agent

    asyncio.run(
        run_agent(
            args.agent,
            task_id=args.task_id,
            max_turns=args.max_turns,
            max_budget_usd=args.max_budget,
        )
    )


# --- standing-orders command ---


def cmd_standing_orders(args):
    """Run standing orders for an agent if due."""
    _set_root(args)
    from .runner import run_standing_orders

    asyncio.run(
        run_standing_orders(
            args.agent,
            max_turns=args.max_turns,
            max_budget_usd=args.max_budget,
        )
    )


# --- drives command ---


def cmd_drives(args):
    """Run drive consultation for an agent."""
    _set_root(args)
    from .runner import run_drive_consultation

    asyncio.run(
        run_drive_consultation(
            args.agent,
            max_turns=args.max_turns,
            max_budget_usd=args.max_budget,
        )
    )


# --- dream command ---


def cmd_dream(args):
    """Run dream cycle for an agent (nightly memory reorganization)."""
    _set_root(args)
    from .runner import run_dream_cycle

    asyncio.run(
        run_dream_cycle(
            args.agent,
            max_turns=args.max_turns,
            max_budget_usd=args.max_budget,
        )
    )


# --- tick command ---


def cmd_tick(args):
    """Run the scheduler tick — dispatches any due work."""
    _set_root(args)
    from .scheduler import tick

    result = asyncio.run(tick())
    if result.dispatched:
        print(f"[agent-os] Tick: dispatched {len(result.dispatched)} item(s)", flush=True)
    elif result.skipped:
        reasons = ", ".join(result.skipped)
        print(f"[agent-os] Tick: skipped ({reasons})", flush=True)
    else:
        print("[agent-os] Tick: nothing due", flush=True)


# --- schedule command ---


def cmd_schedule(args):
    """Show schedule status."""
    _set_root(args)
    from .scheduler import get_schedule_status

    print(get_schedule_status())


# --- budget command ---


def cmd_budget(args):
    """Show budget status with progress bars."""
    _set_root(args)
    from .budget import format_budget_report

    print(format_budget_report())


# --- backlog command ---


def cmd_backlog(args):
    """Manage the task backlog."""
    _set_root(args)
    from . import core as aios

    action = getattr(args, "backlog_action", None)

    if action == "promote":
        result = aios.promote_task(args.task_id)
        if result:
            print(f"Promoted {args.task_id} to queued/ at {result}")
        else:
            print(f"Error: {args.task_id} not found in backlog/")
            sys.exit(1)
    elif action == "reject":
        reason = args.reason or "No reason given"
        result = aios.reject_task(args.task_id, reason)
        if result:
            print(f"Rejected {args.task_id} -> declined/ at {result}")
        else:
            print(f"Error: {args.task_id} not found in backlog/")
            sys.exit(1)
    else:
        # List backlog
        items = aios.list_backlog()
        if not items:
            print("Backlog is empty.")
            return
        print(f"Backlog: {len(items)} item(s)")
        print("-" * 60)
        for meta, _body, path in items:
            task_id = meta.get("id", path.stem)
            title = meta.get("title", "Untitled")
            created_by = meta.get("created_by", "unknown")
            priority = meta.get("priority", "medium")
            print(f"  [{priority}] {task_id}: {title} (by {created_by})")


# --- archive command ---


def cmd_archive(args):
    """Run archive maintenance."""
    _set_root(args)
    from .maintenance import run_archive

    result = run_archive()
    print(
        f"Archived: {result.broadcasts_archived} broadcasts, {result.tasks_archived} tasks, {result.threads_archived} threads"
    )
    print(f"Total: {result.total_archived} items")


# --- manifest command ---


def cmd_manifest(args):
    """Regenerate knowledge manifest."""
    _set_root(args)
    from .maintenance import run_manifest

    path = run_manifest()
    print(f"Manifest written to {path}")


# --- watchdog command ---


def cmd_watchdog(args):
    """Check agent liveness."""
    _set_root(args)
    from .maintenance import run_watchdog

    result = run_watchdog()
    print(f"Checked: {result.agents_checked} agents")
    print(f"Healthy: {result.agents_healthy} | Stale: {result.agents_stale}")
    if result.alerts:
        print("\nAlerts:")
        for alert in result.alerts:
            print(f"  ! {alert}")
    else:
        print("All agents healthy.")


# --- cron command ---

_CRON_MARKER = "# agent-os-tick"


def _find_toml_path(args) -> Path:
    """Resolve the absolute path to the agent-os.toml config file."""
    config_path = getattr(args, "config", None)
    if config_path:
        return Path(config_path).resolve()

    from .config import Config

    root = getattr(args, "root", None)
    toml_path = Config.discover_toml(Path(root).resolve() if root else None)
    if toml_path:
        return toml_path.resolve()

    # Default: look in cwd
    candidate = Path.cwd() / "agent-os.toml"
    if candidate.is_file():
        return candidate.resolve()
    return candidate  # will be used in the cron line even if not found yet


def _get_current_crontab() -> str:
    """Read the current user crontab."""
    import subprocess

    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else ""
    except FileNotFoundError:
        return ""


def _set_crontab(content: str) -> bool:
    """Write a new crontab. Returns True on success."""
    import subprocess

    result = subprocess.run(["crontab", "-"], input=content, capture_output=True, text=True)
    return result.returncode == 0


def cmd_cron(args):
    """Manage the agent-os cron entry."""
    action = getattr(args, "cron_action", None)

    if action == "install":
        toml_path = _find_toml_path(args)
        log_dir = toml_path.parent / "company" / "operations" / "logs"

        cron_line = f"* * * * * agent-os tick --config {toml_path} >> {log_dir}/scheduler.log 2>&1 {_CRON_MARKER}"

        current = _get_current_crontab()
        if _CRON_MARKER in current:
            print("agent-os tick is already installed in crontab.")
            print("Run 'agent-os cron uninstall' first to replace it.")
            return

        new_crontab = current.rstrip("\n") + "\n" + cron_line + "\n"
        if _set_crontab(new_crontab):
            log_dir.mkdir(parents=True, exist_ok=True)
            print("Installed agent-os tick in crontab:")
            print(f"  {cron_line}")
        else:
            print("Error: failed to install crontab entry.", file=sys.stderr)
            sys.exit(1)

    elif action == "uninstall":
        current = _get_current_crontab()
        if _CRON_MARKER not in current:
            print("No agent-os tick entry found in crontab.")
            return

        lines = [line for line in current.splitlines() if _CRON_MARKER not in line]
        if _set_crontab("\n".join(lines) + "\n"):
            print("Removed agent-os tick from crontab.")
        else:
            print("Error: failed to update crontab.", file=sys.stderr)
            sys.exit(1)

    else:
        # status
        current = _get_current_crontab()
        if _CRON_MARKER in current:
            for line in current.splitlines():
                if _CRON_MARKER in line:
                    print(f"Installed: {line.replace(_CRON_MARKER, '').strip()}")
                    break
        else:
            print("Not installed. Run 'agent-os cron install' to set up.")


# --- dashboard command ---


def cmd_dashboard(args):
    """Launch the agent-os dashboard."""
    print("Dashboard is not yet included in this package.")
    print("See https://github.com/corvyd-ai/agent-os for updates.")
    sys.exit(0)


# --- helpers ---


def _set_root(args):
    """Set up Config from --config TOML file, --root flag, or defaults."""
    from .config import Config, configure

    config_path = getattr(args, "config", None)
    root = getattr(args, "root", None)

    if config_path:
        # Explicit TOML file
        cfg = Config.from_toml(Path(config_path))
    else:
        # Try TOML discovery
        toml_path = Config.discover_toml(Path(root).resolve() if root else None)
        if toml_path:
            cfg = Config.from_toml(toml_path)
        else:
            # Fallback to root-only config
            resolved = Path(root).resolve() if root else Path.cwd()
            cfg = Config(company_root=resolved)

    # Also set env var for any subprocess that might need it
    os.environ["AGENT_OS_ROOT"] = str(cfg.company_root)
    configure(cfg)


def _add_common_args(parser):
    """Add arguments common to all agent-invoking subcommands."""
    parser.add_argument("--root", default=None, help="Company root directory (default: current directory)")
    parser.add_argument("--config", default=None, help="Path to agent-os.toml config file")
    parser.add_argument("--max-turns", type=int, default=None, help="Override max turns for this invocation")
    parser.add_argument("--max-budget", type=float, default=None, help="Override max budget (USD) for this invocation")


# --- main entry point ---


def main():
    parser = argparse.ArgumentParser(
        prog="agent-os",
        description="The open-source operations layer for AI agents.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_get_version()}")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init
    p_init = subparsers.add_parser("init", help="Create a new agent-os company")
    p_init.add_argument("name", help="Name for the company directory")
    p_init.set_defaults(func=cmd_init)

    # cycle
    p_cycle = subparsers.add_parser("cycle", help="Run one cycle for an agent")
    p_cycle.add_argument("agent", help="Agent ID (e.g. agent-001-builder)")
    _add_common_args(p_cycle)
    p_cycle.set_defaults(func=cmd_cycle)

    # run
    p_run = subparsers.add_parser("run", help="Run one cycle for all agents")
    _add_common_args(p_run)
    p_run.set_defaults(func=cmd_run)

    # task
    p_task = subparsers.add_parser("task", help="Run a specific task")
    p_task.add_argument("agent", help="Agent ID")
    p_task.add_argument("task_id", help="Task ID to run")
    _add_common_args(p_task)
    p_task.set_defaults(func=cmd_task)

    # standing-orders
    p_so = subparsers.add_parser("standing-orders", help="Run standing orders for an agent")
    p_so.add_argument("agent", help="Agent ID")
    _add_common_args(p_so)
    p_so.set_defaults(func=cmd_standing_orders)

    # drives
    p_drives = subparsers.add_parser("drives", help="Run drive consultation for an agent")
    p_drives.add_argument("agent", help="Agent ID")
    _add_common_args(p_drives)
    p_drives.set_defaults(func=cmd_drives)

    # dream
    p_dream = subparsers.add_parser("dream", help="Run dream cycle for an agent")
    p_dream.add_argument("agent", help="Agent ID")
    _add_common_args(p_dream)
    p_dream.set_defaults(func=cmd_dream)

    # tick
    p_tick = subparsers.add_parser("tick", help="Run scheduler tick (the one cron entry)")
    _add_common_args(p_tick)
    p_tick.set_defaults(func=cmd_tick)

    # schedule
    p_sched = subparsers.add_parser("schedule", help="Show schedule status")
    _add_common_args(p_sched)
    p_sched.set_defaults(func=cmd_schedule)

    # budget
    p_budget = subparsers.add_parser("budget", help="Show budget status")
    _add_common_args(p_budget)
    p_budget.set_defaults(func=cmd_budget)

    # backlog
    p_backlog = subparsers.add_parser("backlog", help="Manage task backlog")
    _add_common_args(p_backlog)
    backlog_sub = p_backlog.add_subparsers(dest="backlog_action")

    p_bl_promote = backlog_sub.add_parser("promote", help="Promote backlog item to queued")
    p_bl_promote.add_argument("task_id", help="Task ID to promote")

    p_bl_reject = backlog_sub.add_parser("reject", help="Reject backlog item")
    p_bl_reject.add_argument("task_id", help="Task ID to reject")
    p_bl_reject.add_argument("--reason", default=None, help="Rejection reason")

    p_backlog.set_defaults(func=cmd_backlog)

    # archive
    p_archive = subparsers.add_parser("archive", help="Run archive maintenance")
    _add_common_args(p_archive)
    p_archive.set_defaults(func=cmd_archive)

    # manifest
    p_manifest = subparsers.add_parser("manifest", help="Regenerate knowledge manifest")
    _add_common_args(p_manifest)
    p_manifest.set_defaults(func=cmd_manifest)

    # watchdog
    p_watchdog = subparsers.add_parser("watchdog", help="Check agent liveness")
    _add_common_args(p_watchdog)
    p_watchdog.set_defaults(func=cmd_watchdog)

    # cron
    p_cron = subparsers.add_parser("cron", help="Manage the agent-os cron entry")
    p_cron.add_argument("--root", default=None, help="Company root directory")
    p_cron.add_argument("--config", default=None, help="Path to agent-os.toml config file")
    cron_sub = p_cron.add_subparsers(dest="cron_action")
    p_cron_install = cron_sub.add_parser("install", help="Install agent-os tick in crontab")
    p_cron_install.add_argument("--config", default=None, help="Path to agent-os.toml config file")
    p_cron_install.add_argument("--root", default=None, help="Company root directory")
    cron_sub.add_parser("uninstall", help="Remove agent-os tick from crontab")
    cron_sub.add_parser("status", help="Check if agent-os tick is installed")
    p_cron.set_defaults(func=cmd_cron)

    # dashboard
    p_dash = subparsers.add_parser("dashboard", help="Launch the dashboard")
    p_dash.set_defaults(func=cmd_dashboard)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


def _get_version():
    try:
        from . import __version__

        return __version__
    except ImportError:
        return "0.1.0"


if __name__ == "__main__":
    main()
