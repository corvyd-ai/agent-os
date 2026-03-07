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
