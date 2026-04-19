"""agent-os CLI — the command-line interface for agent-os.

Provides subcommands for initializing, running, and managing agent companies.

Usage:
    agent-os init my-company          # Create a new company filesystem
    agent-os status                   # Show compact system status overview
    agent-os cycle agent-001          # Run one cycle (check tasks, messages, threads)
    agent-os run                      # Run all agents once (one cycle each)
    agent-os task agent-001 task-001  # Run a specific task
    agent-os standing-orders agent-001  # Run standing orders if due
    agent-os drives agent-001         # Run drive consultation
    agent-os dream agent-001          # Run dream cycle
    agent-os update                   # Self-update agent-os from git
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
    "products",
    "knowledge",
    "knowledge/technical",
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

    (target / "agent-os.toml").write_text(
        f"# agent-os configuration for {name}\n"
        f"# Full reference: https://github.com/corvyd-ai/agent-os/blob/main/docs/configuration.md\n"
        f"\n"
        f"[company]\n"
        f'name = "{name}"\n'
        f'root = "."\n'
        f"\n"
        f"[runtime]\n"
        f'model = "claude-sonnet-4-6"\n'
        f"\n"
        f"[budget]\n"
        f"task = 5.00\n"
        f"daily_cap = 50.00\n"
        f"weekly_cap = 250.00\n"
        f"monthly_cap = 750.00\n"
        f"\n"
        f"# Uncomment to enable workspace isolation for builder agents.\n"
        f"# Agents will work in isolated git branches with automated validation.\n"
        f"# [project]\n"
        f'# default_branch = "main"\n'
        f"#\n"
        f"# [project.setup]\n"
        f'# commands = ["npm install"]\n'
        f"#\n"
        f"# [project.validate]\n"
        f'# commands = ["npm test", "npm run lint"]\n'
    )

    # Create .gitignore with worktrees directory
    (target / ".gitignore").write_text("# Agent worktrees (managed by agent-os)\n.worktrees/\n\n# Environment\n.env\n")

    print(f"""\
Done! Your company is ready at {target}/

Next steps:

  1. cd {name}

  2. Define your first agent:

  cat > agents/registry/agent-001-builder.md << 'EOF'
---
id: agent-001-builder
name: The Builder
role: Software Engineer
model: claude-sonnet-4-6
---

I build software. I care about clean code, working tests, and shipping.
EOF

  3. Create a task:

  agent-os new "Write a hello world script" -a agent-001-builder

  4. Set your API key:

  export ANTHROPIC_API_KEY=your-key-here

  5. Run your agent:

  agent-os cycle agent-001-builder

  6. Set up automatic scheduling:

  agent-os cron install
""")


# --- helpers ---


def _handle_agent_not_found(e: FileNotFoundError) -> None:
    """Print a friendly error when an agent registry file is not found."""
    print(f"Error: {e}", file=sys.stderr)
    print("\nHint: check available agents with: ls agents/registry/", file=sys.stderr)
    sys.exit(1)


# --- status command ---


def cmd_status(args):
    """Show compact system status overview."""
    _set_root(args)
    from .status import format_status

    no_color = getattr(args, "no_color", False)
    output, exit_code = format_status(no_color=no_color)
    print(output)
    sys.exit(exit_code)


# --- new command ---


def cmd_new(args):
    """Create a new task."""
    _set_root(args)
    import subprocess
    import tempfile

    from .core import create_task_human

    title = args.title
    assigned_to = args.assign
    priority = args.priority
    tags = args.tag or []

    # Validate assignee exists in registry if provided
    if assigned_to:
        from .config import get_config

        cfg = get_config()
        registry_dir = cfg.company_root / "agents" / "registry"
        agent_file = registry_dir / f"{assigned_to}.md"
        if not agent_file.exists():
            print(f"Error: agent '{assigned_to}' not found in registry.", file=sys.stderr)
            print(f"\nHint: check available agents with: ls {registry_dir}/", file=sys.stderr)
            sys.exit(1)

    # Get body from: --edit flag, stdin pipe, or empty
    body = ""
    if args.edit:
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR", "vi")
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            f.write(f"# {title}\n\n")
            f.write("<!-- Describe the task below. This line will be included. -->\n")
            tmp_path = f.name
        try:
            subprocess.run([editor, tmp_path], check=True)
            body = Path(tmp_path).read_text()
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    elif not sys.stdin.isatty():
        body = sys.stdin.read()

    task_id, destination = create_task_human(
        title=title,
        body=body,
        assigned_to=assigned_to,
        priority=priority,
        tags=tags,
    )

    print(f"Created {task_id} -> {destination}/")
    if not assigned_to:
        print("Assign and promote with: agent-os backlog promote", task_id)


# --- cycle command ---


def cmd_cycle(args):
    """Run one cycle for an agent: check tasks, messages, threads."""
    _set_root(args)
    from .runner import run_cycle

    try:
        asyncio.run(
            run_cycle(
                args.agent,
                max_turns=args.max_turns,
                max_budget_usd=args.max_budget,
            )
        )
    except FileNotFoundError as e:
        _handle_agent_not_found(e)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


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

    try:
        asyncio.run(
            run_agent(
                args.agent,
                task_id=args.task_id,
                max_turns=args.max_turns,
                max_budget_usd=args.max_budget,
            )
        )
    except FileNotFoundError as e:
        _handle_agent_not_found(e)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# --- standing-orders command ---


def cmd_standing_orders(args):
    """Run standing orders for an agent if due."""
    _set_root(args)
    from .runner import run_standing_orders

    try:
        asyncio.run(
            run_standing_orders(
                args.agent,
                max_turns=args.max_turns,
                max_budget_usd=args.max_budget,
            )
        )
    except FileNotFoundError as e:
        _handle_agent_not_found(e)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# --- drives command ---


def cmd_drives(args):
    """Run drive consultation for an agent."""
    _set_root(args)
    from .runner import run_drive_consultation

    try:
        asyncio.run(
            run_drive_consultation(
                args.agent,
                max_turns=args.max_turns,
                max_budget_usd=args.max_budget,
            )
        )
    except FileNotFoundError as e:
        _handle_agent_not_found(e)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# --- dream command ---


def cmd_dream(args):
    """Run dream cycle for an agent (nightly memory reorganization)."""
    _set_root(args)
    from .runner import run_dream_cycle

    try:
        asyncio.run(
            run_dream_cycle(
                args.agent,
                max_turns=args.max_turns,
                max_budget_usd=args.max_budget,
            )
        )
    except FileNotFoundError as e:
        _handle_agent_not_found(e)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


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


# --- update command ---


def _find_repo_root() -> Path:
    """Find the git repo root for the installed agent-os package."""
    pkg_dir = Path(__file__).resolve().parent
    # Walk up from the package directory to find the .git root
    current = pkg_dir
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent
    return None


def cmd_update(args):
    """Self-update agent-os from its git repository."""
    import subprocess

    repo_root = _find_repo_root()
    if repo_root is None:
        print("Error: agent-os is not installed from a git repository.", file=sys.stderr)
        print("Install from git to use self-update:", file=sys.stderr)
        print("  git clone https://github.com/corvyd-ai/agent-os && cd agent-os && pip install -e .", file=sys.stderr)
        sys.exit(1)

    def git(*cmd):
        result = subprocess.run(
            ["git", *cmd],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        return result

    # Determine the current branch
    r = git("rev-parse", "--abbrev-ref", "HEAD")
    if r.returncode != 0:
        print("Error: could not determine current branch.", file=sys.stderr)
        sys.exit(1)
    branch = r.stdout.strip()

    # Check for uncommitted changes
    r = git("status", "--porcelain")
    if r.stdout.strip():
        print(f"Warning: agent-os repo has uncommitted changes at {repo_root}", file=sys.stderr)
        print("Stash or commit them before updating.", file=sys.stderr)
        sys.exit(1)

    # Fetch latest
    print(f"Fetching origin/{branch}...")
    r = git("fetch", "origin", branch)
    if r.returncode != 0:
        print(f"Error: git fetch failed: {r.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    # Check if already up to date
    r = git("rev-list", f"HEAD..origin/{branch}", "--count")
    new_commits = int(r.stdout.strip()) if r.returncode == 0 else 0

    if new_commits == 0:
        from . import __version__

        print(f"Already up to date (v{__version__} on {branch}).")
        return

    # Capture the pre-pull commit and subject lines — we'll use these to
    # write release notes for agents after the install succeeds.
    previous_commit = git("rev-parse", "HEAD").stdout.strip()
    from . import __version__ as previous_version

    # Show what's new
    print(f"\n{new_commits} new commit(s):\n")
    git_log = git("log", f"HEAD..origin/{branch}", "--oneline", "--no-decorate")
    print(git_log.stdout.strip())

    # Capture the subjects for the release notes broadcast
    subjects_raw = git("log", f"HEAD..origin/{branch}", "--pretty=format:%s").stdout
    commit_subjects = [s for s in subjects_raw.splitlines() if s.strip()]

    if not getattr(args, "yes", False):
        try:
            answer = input("\nApply update? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return
        if answer and answer not in ("y", "yes"):
            print("Aborted.")
            return

    # Pull (fast-forward only)
    print(f"\nPulling origin/{branch}...")
    r = git("pull", "--ff-only", "origin", branch)
    if r.returncode != 0:
        print(f"Error: git pull failed: {r.stderr.strip()}", file=sys.stderr)
        print("Your branch may have diverged. Resolve manually.", file=sys.stderr)
        sys.exit(1)

    new_commit = git("rev-parse", "HEAD").stdout.strip()

    # Reinstall
    print("Reinstalling...")
    r = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-e", ".", "--quiet"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print(f"Error: pip install failed: {r.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    # Show new version — re-import from the freshly installed package
    r = subprocess.run(
        [sys.executable, "-c", "from agent_os import __version__; print(__version__)"],
        capture_output=True,
        text=True,
    )
    new_version = r.stdout.strip() if r.returncode == 0 else "unknown"
    print(f"\nUpdated to v{new_version}.")

    # Write release notes to the company's knowledge base so agents running
    # on this deployment learn what changed. Skipped silently if no company
    # config is reachable (e.g., running `agent-os update` from the platform
    # repo without AGENT_OS_ROOT pointing at a company).
    _write_release_notes_if_possible(
        previous_commit=previous_commit,
        new_commit=new_commit,
        commit_subjects=commit_subjects,
        previous_version=previous_version,
        new_version=new_version,
    )


def _write_release_notes_if_possible(
    *,
    previous_commit: str,
    new_commit: str,
    commit_subjects: list[str],
    previous_version: str,
    new_version: str,
) -> None:
    """Best-effort write of agent-visible release notes to the company.

    Runs in a subprocess against the freshly-installed package so it uses
    the new code (not the old, still-loaded-in-memory release_notes module).
    Failures are non-fatal — they print a warning but do not fail the
    update itself, which has already succeeded by this point.
    """
    import json
    import subprocess

    payload = json.dumps(
        {
            "previous_commit": previous_commit,
            "new_commit": new_commit,
            "commit_subjects": commit_subjects,
            "previous_version": previous_version,
            "new_version": new_version,
        }
    )

    # We call the freshly-installed package via a subprocess so the agent
    # reading the release notes sees the new behaviors, not the behaviors
    # from the pre-update module still loaded in this process.
    script = (
        "import json, sys;"
        "from agent_os.release_notes import write_update_notes;"
        "from agent_os.config import get_config;"
        "data = json.loads(sys.argv[1]);"
        "cfg = get_config();"
        "r = write_update_notes("
        "previous_commit=data['previous_commit'],"
        "new_commit=data['new_commit'],"
        "commit_subjects=data['commit_subjects'],"
        "previous_version=data['previous_version'],"
        "new_version=data['new_version'],"
        "config=cfg);"
        "print(json.dumps({'broadcast_id': r.broadcast_id, 'reference': r.reference_doc_path, 'changelog': r.changelog_path, 'errors': r.errors}))"
    )

    try:
        result = subprocess.run(
            [sys.executable, "-c", script, payload],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"Warning: could not write release notes: {e}", file=sys.stderr)
        return

    if result.returncode != 0:
        # Most common cause: no company config reachable — silent skip is fine.
        # But if stderr is non-empty, surface it as a warning.
        if result.stderr.strip():
            print(f"Warning: release notes step skipped: {result.stderr.strip()}", file=sys.stderr)
        return

    try:
        out = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return

    if out.get("errors"):
        for err in out["errors"]:
            print(f"Warning: release notes: {err}", file=sys.stderr)
    if out.get("broadcast_id"):
        print(f"Release notes: posted broadcast {out['broadcast_id']} and regenerated platform reference doc.")


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


# --- doctor command ---


def cmd_doctor(args):
    """Run diagnostic health checks."""
    _set_root(args)
    from .doctor import format_doctor_output, run_doctor

    verbose = getattr(args, "verbose", False)
    runtime_user = getattr(args, "runtime_user", None)
    result = run_doctor(verbose=verbose, runtime_user=runtime_user)
    no_color = getattr(args, "no_color", False)
    print(format_doctor_output(result, no_color=no_color, verbose=verbose))
    sys.exit(1 if result.errors else 0)


# --- digest command ---


def cmd_digest(args):
    """Generate a health digest."""
    _set_root(args)
    from .maintenance import run_daily_digest

    result = run_daily_digest()
    print(f"Tasks: {result.tasks_completed} completed, {result.tasks_failed} failed, {result.tasks_created} created")
    print(f"Agents: {result.agents_healthy} healthy, {result.agents_stale} stale")
    if result.breakers_tripped:
        print(f"Breakers tripped: {', '.join(result.breakers_tripped)}")
    print(f"Spend: ${result.daily_spend:.2f} / ${result.daily_cap:.2f}")
    if result.anomalies:
        print("\nAnomalies:")
        for a in result.anomalies:
            print(f"  ! {a}")
    if result.digest_path:
        print(f"\nDigest written to: {result.digest_path}")


# --- project command ---


def cmd_project(args):
    """Dispatch for `agent-os project <action>`."""
    action = getattr(args, "project_action", None)
    if action == "check":
        return cmd_project_check(args)
    if action == "init":
        return cmd_project_init(args)
    if action == "backfill":
        return cmd_project_backfill(args)
    print("Usage: agent-os project {check|init|backfill}", file=sys.stderr)
    sys.exit(1)


def cmd_project_check(args):
    """Run project-readiness diagnostics."""
    _set_root(args)
    from .project import run_project_check

    use_color = not getattr(args, "no_color", False) and sys.stdout.isatty() and not os.environ.get("NO_COLOR")

    def _color(text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if use_color else text

    status_icons = {
        "ok": _color("[OK]     ", "32"),
        "warning": _color("[WARNING]", "33"),
        "error": _color("[ERROR]  ", "31"),
        "skipped": _color("[SKIP]   ", "2"),
    }

    result = run_project_check()
    print()
    print("agent-os project check")
    print("=" * 40)
    print()
    for check in result.checks:
        icon = status_icons.get(check.status, "[???]    ")
        print(f"  {icon}  {check.name}")
        if check.detail:
            print(f"             {check.detail}")
        if check.fix:
            print(f"             Fix: {check.fix}")
        print()

    summary = f"  {result.ok} passed, {result.warnings} warning(s), {result.errors} error(s)"
    print(summary)
    print()
    sys.exit(1 if result.errors else 0)


def cmd_project_init(args):
    """Interactive bootstrap of the workspace SDLC config."""
    _set_root(args)
    from .config import Config, get_config
    from .project import (
        ensure_worktrees_gitignored,
        run_project_check,
        ssh_setup_instructions,
        write_project_config,
    )

    if getattr(args, "ssh_help", False):
        # Short-circuit: just print SSH setup guidance, don't do anything else
        cfg = get_config()
        print(ssh_setup_instructions(cfg))
        return

    cfg = get_config()
    toml_path = _find_toml_path(args)

    if cfg.project_enabled:
        print(f"[project] section already configured in {toml_path}.")
        print("Running `agent-os project check` to show current state:\n")
        return cmd_project_check(args)

    print()
    print(f"Configuring the workspace SDLC for {cfg.company_name}.")
    print(f"Config file: {toml_path}")
    print()
    print("Agents will work in isolated git worktrees. agent-os will commit")
    print("and push for them — agents never run git commands.")
    print()

    yes = getattr(args, "yes", False)

    def ask(prompt: str, default: str) -> str:
        if yes:
            return default
        try:
            answer = input(f"{prompt} [{default}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(1)
        return answer or default

    def ask_list(prompt: str, default: list[str]) -> list[str]:
        default_str = ", ".join(default) if default else ""
        if yes:
            return default
        try:
            answer = input(f"{prompt} [{default_str}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(1)
        if not answer:
            return default
        return [c.strip() for c in answer.split(",") if c.strip()]

    default_branch = ask("Default branch", "main")
    setup_commands = ask_list("Setup commands (comma-separated)", [])
    validate_commands = ask_list("Validate commands (comma-separated)", [])

    print()
    print("Writing [project] config...")
    try:
        write_project_config(
            toml_path,
            default_branch=default_branch,
            setup_commands=setup_commands,
            validate_commands=validate_commands,
        )
        print(f"  ✓ {toml_path}")
    except (FileNotFoundError, ValueError) as e:
        print(f"  ✗ {e}", file=sys.stderr)
        sys.exit(1)

    # Reload config so downstream checks see the new [project] section
    cfg = Config.from_toml(toml_path)

    if ensure_worktrees_gitignored(cfg):
        print(f"  ✓ Added {cfg.project_worktrees_dir}/ to {cfg.repo_root}/.gitignore")

    # Run readiness check against the new config
    print()
    print("Running readiness check against the new config...")
    print()
    result = run_project_check(config=cfg)
    for check in result.checks:
        icon = {"ok": "✓", "warning": "!", "error": "✗", "skipped": "·"}.get(check.status, "?")
        print(f"  {icon} {check.name}: {check.detail}")

    auth_failed = any(
        c.status == "error" and c.name == "Remote reachable" and "ls-remote failed" in c.detail for c in result.checks
    )
    if auth_failed:
        print()
        print("Push authentication is not yet configured. Guidance follows:")
        print(ssh_setup_instructions(cfg))
    elif result.errors:
        print()
        print(f"{result.errors} error(s) remaining. Re-run `agent-os project check` after fixing.")
    else:
        print()
        print("All checks passed. The workspace SDLC is ready.")


def cmd_project_backfill(args):
    """Bootstrap the platform changelog from git history.

    One-time catch-up for deployments that existed before release notes
    shipped. Reads the agent-os platform repo's git log + tags, generates
    changelog entries grouped by tag boundary, and writes them to the
    company's ``knowledge/technical/`` directory.
    """
    _set_root(args)
    from . import __version__
    from .config import get_config
    from .release_notes import build_backfill_entries, write_backfill_notes

    repo_root = _find_repo_root()
    if repo_root is None:
        print(
            "Error: agent-os is not installed from a git repository — can't read history to backfill.",
            file=sys.stderr,
        )
        print("Install from git if you want to use backfill.", file=sys.stderr)
        sys.exit(1)

    since = getattr(args, "since", None)
    force = getattr(args, "force", False)
    no_broadcast = getattr(args, "no_broadcast", False)

    # Pull commits + tags from the platform repo
    commits = _read_git_commits(repo_root, since=since)
    tags = _read_git_tags(repo_root, since=since)

    if not commits:
        print("No commits found to backfill.")
        return

    entries = build_backfill_entries(
        commits=commits,
        tags=tags,
        current_version=__version__,
    )

    total_commits = sum(len(e.commit_subjects) for e in entries)
    print()
    print("agent-os project backfill")
    print("=" * 40)
    print()
    print(f"Source:  {repo_root}")
    print(f"Commits: {len(commits)} ({total_commits} grouped into {len(entries)} changelog entries)")
    print(f"Tags:    {len(tags)}")
    print(f"Target:  {get_config().company_root}/knowledge/technical/")
    print()

    if not getattr(args, "yes", False):
        try:
            answer = input("Proceed? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return
        if answer and answer not in ("y", "yes"):
            print("Aborted.")
            return

    result = write_backfill_notes(
        entries=entries,
        current_version=__version__,
        force=force,
        post_broadcast=not no_broadcast,
    )

    if result.errors:
        for err in result.errors:
            print(f"Error: {err}", file=sys.stderr)
        if not result.changelog_path:
            sys.exit(1)

    print()
    if result.reference_doc_path:
        print(f"  ✓ Reference doc: {result.reference_doc_path}")
    if result.changelog_path:
        print(f"  ✓ Changelog:     {result.changelog_path} ({result.entries_written} entries)")
    if result.broadcast_id:
        print(f"  ✓ Broadcast:     {result.broadcast_id}")
    elif no_broadcast:
        print("  · Broadcast skipped (--no-broadcast)")
    print()


def _read_git_commits(repo_root: Path, *, since: str | None = None) -> list[tuple[str, str, str]]:
    """Read commits from the platform repo in chronological order.

    Returns [(sha, subject, iso_date), ...] oldest first.
    """
    import subprocess

    rev_range = f"{since}..HEAD" if since else "HEAD"
    # Reverse chronological by default; we want chronological for grouping
    result = subprocess.run(
        ["git", "log", "--reverse", "--pretty=format:%H\t%s\t%cI", rev_range],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []

    commits: list[tuple[str, str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            commits.append((parts[0], parts[1], parts[2]))
    return commits


def _read_git_tags(repo_root: Path, *, since: str | None = None) -> list[tuple[str, str, str]]:
    """Read tags from the platform repo in chronological order.

    Returns [(tag_name, sha, iso_date), ...] oldest first. Filters to tags
    that look like versions (start with 'v' followed by a digit) — other
    tags (e.g., 'stable', 'prod') aren't version boundaries.
    """
    import subprocess

    result = subprocess.run(
        [
            "git",
            "for-each-ref",
            "--sort=creatordate",
            "--format=%(refname:short)\t%(objectname)\t%(creatordate:iso-strict)",
            "refs/tags/",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []

    tags: list[tuple[str, str, str]] = []
    since_seen = since is None
    for line in result.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        name, sha, ts = parts
        if not (name.startswith("v") and len(name) > 1 and name[1].isdigit()):
            continue
        # If --since was provided, filter to tags reachable from that point forward
        if since and not since_seen:
            if name == since:
                since_seen = True
            continue
        tags.append((name, sha, ts))
    return tags


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
    _set_root(args)

    try:
        import uvicorn
    except ImportError:
        print("Dashboard dependencies not installed.")
        print("Run: pip install agent-os[dashboard]")
        sys.exit(1)

    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8787)
    print(f"Starting agent-os dashboard on http://{host}:{port}")
    uvicorn.run("agent_os.dashboard.app:app", host=host, port=port, reload=True)


# --- helpers ---


def _set_root(args):
    """Set up Config from --config TOML file, --root flag, or defaults."""
    from .config import Config, configure, load_dotenv

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

    # Load .env from project root (before anything checks env vars)
    load_dotenv(cfg.company_root)

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

    # new
    p_new = subparsers.add_parser("new", help="Create a new task")
    p_new.add_argument("title", help="Task title (the only required field)")
    p_new.add_argument(
        "-a", "--assign", default=None, metavar="AGENT", help="Assign to agent (sends to queued/ instead of backlog/)"
    )
    p_new.add_argument(
        "-p",
        "--priority",
        default="medium",
        choices=["low", "medium", "high", "critical"],
        help="Priority level (default: medium)",
    )
    p_new.add_argument("-t", "--tag", action="append", metavar="TAG", help="Add a tag (repeatable)")
    p_new.add_argument("-e", "--edit", action="store_true", help="Open $EDITOR to write the task body")
    p_new.add_argument("--root", default=None, help="Company root directory")
    p_new.add_argument("--config", default=None, help="Path to agent-os.toml config file")
    p_new.set_defaults(func=cmd_new)

    # status
    p_status = subparsers.add_parser("status", help="Show compact system status overview")
    p_status.add_argument("--no-color", action="store_true", help="Disable color output")
    _add_common_args(p_status)
    p_status.set_defaults(func=cmd_status)

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

    # doctor
    p_doctor = subparsers.add_parser("doctor", help="Diagnose system health issues")
    p_doctor.add_argument("--verbose", "-v", action="store_true", help="Show all checks, not just failures")
    p_doctor.add_argument("--no-color", action="store_true", help="Disable color output")
    p_doctor.add_argument(
        "--runtime-user",
        default=None,
        help="User account the scheduler runs as (for ownership check). Overrides config runtime_user.",
    )
    _add_common_args(p_doctor)
    p_doctor.set_defaults(func=cmd_doctor)

    # digest
    p_digest = subparsers.add_parser("digest", help="Generate health digest")
    _add_common_args(p_digest)
    p_digest.set_defaults(func=cmd_digest)

    # project
    p_project = subparsers.add_parser("project", help="Onboard a repo for the workspace SDLC")
    _add_common_args(p_project)
    project_sub = p_project.add_subparsers(dest="project_action")

    p_project_check = project_sub.add_parser("check", help="Run project-readiness diagnostics")
    p_project_check.add_argument("--no-color", action="store_true")
    _add_common_args(p_project_check)

    p_project_init = project_sub.add_parser("init", help="Interactively configure the workspace SDLC")
    p_project_init.add_argument("-y", "--yes", action="store_true", help="Use defaults non-interactively")
    p_project_init.add_argument("--ssh-help", action="store_true", help="Print SSH deploy-key setup steps and exit")
    _add_common_args(p_project_init)

    p_project_backfill = project_sub.add_parser(
        "backfill",
        help="One-time bootstrap: seed the platform changelog from git history (for deployments that existed before release notes shipped)",
    )
    p_project_backfill.add_argument(
        "--since",
        default=None,
        help="Start point for history (commit SHA or tag). Default: entire history.",
    )
    p_project_backfill.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the changelog even if it already has entries",
    )
    p_project_backfill.add_argument(
        "--no-broadcast",
        action="store_true",
        help="Skip posting the 'release notes enabled' broadcast",
    )
    p_project_backfill.add_argument("-y", "--yes", action="store_true", help="Skip the confirmation prompt")
    _add_common_args(p_project_backfill)

    p_project.set_defaults(func=cmd_project)

    # update
    p_update = subparsers.add_parser("update", help="Self-update agent-os from git")
    p_update.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    p_update.set_defaults(func=cmd_update)

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
    p_dash.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
    p_dash.add_argument("--port", type=int, default=8787, help="Port (default: 8787)")
    _add_common_args(p_dash)
    p_dash.set_defaults(func=cmd_dashboard)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


def _get_version():
    from . import __version__

    return __version__


if __name__ == "__main__":
    main()
