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
    _require_config_source(args, "agent-os budget")
    from .budget import format_budget_report

    print(f"Config: {args._config_source_path}")
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
    """Self-update agent-os.

    Dispatches on installation mode: a git checkout (editable install)
    pulls and reinstalls; a wheel install fetches the latest GitHub
    release and reinstalls. Both end by firing release notes so agents
    running on this deployment learn what changed.
    """
    repo_root = _find_repo_root()
    if repo_root is not None:
        _update_from_git(args, repo_root)
    else:
        _update_from_wheel(args)


def _update_from_git(args, repo_root: Path) -> None:
    """Self-update from a local git checkout (editable install)."""
    import subprocess

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


def _update_from_wheel(args) -> None:
    """Self-update from a published GitHub Release wheel.

    Used when agent-os is installed from a built wheel (the production
    deployment path) and there's no local git checkout to pull from.
    Resolves the release source from --source > [update].source >
    upstream default, fetches the release JSON via the public GitHub
    API (no auth needed for public repos), downloads the .whl asset,
    and `pip install --upgrade`s it. Then fires release notes.

    Errors are surfaced — a network failure or missing asset must NOT
    silently no-op, since the whole point of this path is to keep
    production deployments current.
    """
    import json
    import subprocess
    import tempfile
    import urllib.error
    import urllib.request

    from . import __version__ as previous_version

    source = _resolve_update_source(args)
    owner_repo, _, tag = source.partition("@")
    if not owner_repo:
        print(f"Error: invalid update source '{source}'. Expected 'owner/repo@tag'.", file=sys.stderr)
        sys.exit(1)
    tag = tag or "latest"

    api_url = f"https://api.github.com/repos/{owner_repo}/releases/tags/{tag}"
    print(f"Fetching {owner_repo}@{tag} release info...")

    try:
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": "agent-os-update",
                "Accept": "application/vnd.github+json",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"Error: GitHub API returned {e.code} {e.reason} for {api_url}", file=sys.stderr)
        sys.exit(1)
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        print(f"Error: could not fetch release info from {api_url}: {e}", file=sys.stderr)
        sys.exit(1)

    wheel_assets = [a for a in data.get("assets", []) if a.get("name", "").endswith(".whl")]
    if not wheel_assets:
        print(f"Error: release {owner_repo}@{tag} has no .whl asset to install.", file=sys.stderr)
        sys.exit(1)

    asset = wheel_assets[0]
    wheel_url = asset["browser_download_url"]
    wheel_name = asset["name"]
    new_version_from_wheel = _parse_wheel_version(wheel_name)

    if new_version_from_wheel and new_version_from_wheel == previous_version:
        print(f"Already up to date (v{previous_version}).")
        return

    print()
    print(f"Current: v{previous_version}")
    print(f"Latest:  v{new_version_from_wheel or '?'}  ({wheel_name})")
    body = (data.get("body") or "").strip()
    if body:
        print()
        print("Release notes from GitHub:")
        print("─" * 40)
        print(body)
        print("─" * 40)
    print()

    if not getattr(args, "yes", False):
        try:
            answer = input("Apply update? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return
        if answer and answer not in ("y", "yes"):
            print("Aborted.")
            return

    # Download wheel to a temp file, install, then clean up
    print(f"\nDownloading {wheel_name}...")
    with tempfile.NamedTemporaryFile(suffix=".whl", delete=False) as tmp:
        wheel_path = Path(tmp.name)
    try:
        try:
            req = urllib.request.Request(wheel_url, headers={"User-Agent": "agent-os-update"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                wheel_path.write_bytes(resp.read())
        except (urllib.error.URLError, OSError) as e:
            print(f"Error: download failed: {e}", file=sys.stderr)
            sys.exit(1)

        print(f"Installing {wheel_name}...")
        r = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--upgrade",
                "--force-reinstall",
                "--no-deps",
                str(wheel_path),
                "--quiet",
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            print(f"Error: pip install failed: {r.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
    finally:
        import contextlib

        with contextlib.suppress(OSError):
            wheel_path.unlink()

    # Re-read installed version from a subprocess so we see the new code
    r = subprocess.run(
        [sys.executable, "-c", "from agent_os import __version__; print(__version__)"],
        capture_output=True,
        text=True,
    )
    new_version = r.stdout.strip() if r.returncode == 0 else (new_version_from_wheel or "unknown")
    print(f"\nUpdated to v{new_version}.")

    # Translate the GitHub release body into "commit_subjects" the release-notes
    # mechanism can render. Markdown bullet lines become individual subjects;
    # otherwise the body becomes a single-blob entry. This means the agent-visible
    # broadcast/changelog mirrors what humans see on the release page.
    commit_subjects = _extract_subjects_from_release_body(body)
    new_commit = _extract_commit_sha_from_release_body(body)

    _write_release_notes_if_possible(
        previous_commit="",
        new_commit=new_commit,
        commit_subjects=commit_subjects,
        previous_version=previous_version,
        new_version=new_version,
    )


def _resolve_update_source(args) -> str:
    """Resolve the update source spec ('owner/repo@tag').

    Resolution order: --source flag > [update].source in agent-os.toml >
    Config default ('corvyd-ai/agent-os@latest').

    `agent-os update` does not run `_set_root()` (it operates on the
    platform package, not a company tree), so we discover and load the
    TOML directly here for the [update].source lookup.
    """
    cli_source = getattr(args, "source", None)
    if cli_source:
        return cli_source

    try:
        from .config import Config

        toml_path = Config.discover_toml()
        if toml_path is not None:
            cfg = Config.from_toml(toml_path)
            return cfg.update_source
    except (OSError, ValueError):
        pass

    from .config import Config

    return Config().update_source


def _parse_wheel_version(wheel_name: str) -> str:
    """Extract the version segment from a wheel filename per PEP 491.

    `agent_os-0.3.0-py3-none-any.whl` → `0.3.0`
    `agent_os-0.3.0.dev5+g1234567-py3-none-any.whl` → `0.3.0.dev5+g1234567`
    Returns '' if the filename doesn't have at least two `-`-separated parts.
    """
    parts = wheel_name.split("-")
    if len(parts) >= 2:
        return parts[1]
    return ""


def _extract_subjects_from_release_body(body: str) -> list[str]:
    """Pull bullet items out of a GitHub release body for the release-notes broadcast.

    If the body has markdown bullet lines, those become individual entries
    (the broadcast/changelog renders them as a list). Otherwise the body
    falls through as a single entry — better than nothing, since wheel
    updates can't read per-commit subjects from local git.
    """
    if not body:
        return []
    bullets = [line.lstrip("-* \t").rstrip() for line in body.splitlines() if line.lstrip().startswith(("-", "*"))]
    bullets = [b for b in bullets if b]
    if bullets:
        return bullets
    first_line = body.splitlines()[0].strip()
    return [first_line] if first_line else []


def _extract_commit_sha_from_release_body(body: str) -> str:
    """Pull a 'Commit: <sha>' line out of a GitHub release body, if present.

    CI publishes the source commit in each release body as
    `Commit: <full-sha>`. Returns '' if not found.
    """
    import re

    if not body:
        return ""
    m = re.search(r"\bCommit:\s*([0-9a-f]{7,40})\b", body)
    return m.group(1) if m else ""


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


# --- budget-set / autonomy / schedule-toggle (config mutations) ---


def _discover_toml_path(args) -> Path:
    """Locate agent-os.toml the same way `_set_root` does, but return the path.

    On failure, prints a clear error with recovery hints (cd or --root) and
    exits non-zero so agents and shells can detect it.
    """
    from .config import Config as _Cfg

    config_path = getattr(args, "config", None)
    root = getattr(args, "root", None)
    if config_path:
        return Path(config_path)
    discovered = _Cfg.discover_toml(Path(root).resolve() if root else None)
    if discovered is None:
        print(
            "Error: could not find agent-os.toml.\n"
            "Hint: run this from inside the company directory, "
            "or pass --root /path/to/company (or --config /path/to/agent-os.toml).",
            file=sys.stderr,
        )
        sys.exit(1)
    return discovered


def cmd_budget_set(args):
    """Update budget caps. Requires at least one of --daily/--weekly/--monthly."""
    from .write_cmds import set_budget_caps

    if args.daily is None and args.weekly is None and args.monthly is None:
        print(
            "Error: nothing to set. Pass at least one of --daily, --weekly, --monthly.\n"
            "Example: agent-os budget-set --daily 50",
            file=sys.stderr,
        )
        sys.exit(1)

    toml = _discover_toml_path(args)
    set_budget_caps(toml, daily=args.daily, weekly=args.weekly, monthly=args.monthly)
    print(f"Updated budget caps in {toml}.")


def cmd_autonomy(args):
    from .write_cmds import set_agent_autonomy

    toml = _discover_toml_path(args)
    try:
        set_agent_autonomy(toml, args.agent_id, args.level)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Set {args.agent_id} autonomy to {args.level} in {toml}.")


def cmd_schedule_toggle(args):
    from .write_cmds import toggle_schedule

    toml = _discover_toml_path(args)
    enabled = args.state == "on"
    try:
        toggle_schedule(toml, args.kind, enabled)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Set {args.kind} to {'on' if enabled else 'off'} in {toml}.")


# --- notifications (configure + test) -------------------------------


def cmd_notifications(args):
    """Dispatch `agent-os notifications <action>`."""
    action = getattr(args, "notif_action", None)
    dispatch = {
        "status": cmd_notifications_status,
        "events": cmd_notifications_events,
        "enable": lambda a: cmd_notifications_set_enabled(a, True),
        "disable": lambda a: cmd_notifications_set_enabled(a, False),
        "severity": cmd_notifications_severity,
        "event": cmd_notifications_event,
        "channel": cmd_notifications_channel,
        "webhook": cmd_notifications_webhook,
        "script": cmd_notifications_script,
        "test": cmd_notifications_test,
    }
    handler = dispatch.get(action)
    if handler is None:
        print(
            "Error: missing subcommand.\n"
            "Usage: agent-os notifications "
            "{status|events|enable|disable|severity|event|channel|webhook|script|test}",
            file=sys.stderr,
        )
        sys.exit(1)
    return handler(args)


def cmd_notifications_status(args):
    """Print a readable summary of the current notification configuration."""
    _set_root(args)
    from .config import get_config
    from .notifications import KNOWN_EVENT_TYPES

    cfg = get_config()
    toml = getattr(args, "_config_source_path", None)

    def _on_off(b: bool) -> str:
        return "on" if b else "off"

    print("agent-os notifications")
    print("=" * 40)
    print(f"Enabled:             {_on_off(cfg.notifications_enabled)}")
    print(f"Global min severity: {cfg.notifications_min_severity}")
    print()
    print("Channels:")
    print(f"  file:    {_on_off(cfg.notifications_file)}")
    print(f"  desktop: {_on_off(cfg.notifications_desktop)}")
    webhook_note = cfg.notifications_webhook_url or "(no URL configured)"
    print(f"  webhook: {webhook_note}")
    script_note = cfg.notifications_script or "(no script configured)"
    print(f"  script:  {script_note}")
    print()
    print("Per-event overrides:")
    if not cfg.notifications_event_overrides:
        print("  (none — all events use the global min severity)")
    else:
        width = max(len(k) for k in cfg.notifications_event_overrides)
        for event_type, sev in sorted(cfg.notifications_event_overrides.items()):
            marker = "" if event_type in KNOWN_EVENT_TYPES else "  [unknown event type]"
            print(f"  {event_type.ljust(width)}  -> {sev}{marker}")
    if toml:
        print()
        print(f"Config file: {toml}")


def cmd_notifications_events(args):
    """List known event types with their effective severity."""
    _set_root(args)
    from .config import get_config
    from .notifications import KNOWN_EVENT_TYPES

    cfg = get_config()
    width = max(len(k) for k in KNOWN_EVENT_TYPES)
    print("Known notification event types:")
    print()
    for event_type, description in KNOWN_EVENT_TYPES.items():
        override = cfg.notifications_event_overrides.get(event_type)
        effective = override or cfg.notifications_min_severity
        tag = "[override]" if override else ""
        print(f"  {event_type.ljust(width)}  ({effective:>8})  {description} {tag}".rstrip())
    print()
    print("Set an override with: agent-os notifications event <event_type> <info|warning|critical>")
    print("Clear one with:      agent-os notifications event <event_type> clear")


def cmd_notifications_set_enabled(args, enabled: bool):
    from .write_cmds import set_notifications_enabled

    toml = _discover_toml_path(args)
    set_notifications_enabled(toml, enabled)
    print(f"Notifications {'enabled' if enabled else 'disabled'} in {toml}.")


def cmd_notifications_severity(args):
    from .write_cmds import set_notifications_severity

    toml = _discover_toml_path(args)
    try:
        set_notifications_severity(toml, args.level)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Set global notification min_severity to {args.level} in {toml}.")


def cmd_notifications_event(args):
    from .write_cmds import (
        clear_notifications_event_override,
        set_notifications_event_override,
    )

    toml = _discover_toml_path(args)
    if args.severity == "clear":
        removed = clear_notifications_event_override(toml, args.event_type)
        if removed:
            print(f"Cleared override for {args.event_type} in {toml}.")
        else:
            print(f"No override was set for {args.event_type}.")
        return
    try:
        set_notifications_event_override(toml, args.event_type, args.severity)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Set {args.event_type} override to {args.severity} in {toml}.")


def cmd_notifications_channel(args):
    from .write_cmds import set_notifications_channel

    toml = _discover_toml_path(args)
    enabled = args.state == "on"
    try:
        set_notifications_channel(toml, args.channel, enabled)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Set {args.channel} channel to {'on' if enabled else 'off'} in {toml}.")


def cmd_notifications_webhook(args):
    from .write_cmds import set_notifications_webhook

    toml = _discover_toml_path(args)
    url = "" if args.url == "clear" else args.url
    set_notifications_webhook(toml, url)
    if url:
        print(f"Set notification webhook URL in {toml}.")
    else:
        print(f"Cleared notification webhook URL in {toml}.")


def cmd_notifications_script(args):
    from .write_cmds import set_notifications_script

    toml = _discover_toml_path(args)
    path = "" if args.path == "clear" else args.path
    set_notifications_script(toml, path)
    if path:
        print(f"Set notification script to {path} in {toml}.")
    else:
        print(f"Cleared notification script in {toml}.")


def cmd_notifications_test(args):
    """Fire a test notification through all configured channels."""
    _set_root(args)
    from .config import get_config
    from .notifications import NotificationEvent, send_notification

    cfg = get_config()
    if not cfg.notifications_enabled:
        print(
            "Notifications are disabled. Run `agent-os notifications enable` first.",
            file=sys.stderr,
        )
        sys.exit(1)

    event_type = getattr(args, "event", None) or "test_event"
    severity = getattr(args, "severity", None) or "warning"

    event = NotificationEvent(
        event_type=event_type,
        severity=severity,
        title=f"agent-os test notification ({event_type}, {severity})",
        detail="This is a test notification dispatched via `agent-os notifications test`.",
        agent_id="",
    )
    results = send_notification(event, config=cfg)
    if not results:
        print(
            f"No channels dispatched. The event was filtered (severity={severity}, "
            f"effective threshold="
            f"{cfg.notifications_event_overrides.get(event_type, cfg.notifications_min_severity)})."
        )
        return

    print("Test notification dispatched:")
    for r in results:
        status = "ok" if r.success else f"FAILED: {r.error}"
        print(f"  {r.channel:<8} {status}")


# --- timeline / messages / strategy (read-only inspection) ---


def cmd_timeline(args):
    _set_root(args)
    from .config import get_config
    from .read_cmds import render_timeline

    cfg = get_config()
    print(
        render_timeline(
            cfg,
            date=getattr(args, "date", None),
            agent=getattr(args, "agent", None),
            hide_idle=getattr(args, "hide_idle", False),
        )
    )


def cmd_messages(args):
    _set_root(args)
    from .config import get_config
    from .read_cmds import render_messages

    if args.channel == "inbox" and not getattr(args, "agent", None):
        print(
            "Error: the `inbox` channel requires an agent id.\nExample: agent-os messages inbox agent-001-maker",
            file=sys.stderr,
        )
        sys.exit(1)

    cfg = get_config()
    print(render_messages(cfg, channel=args.channel, agent=getattr(args, "agent", None)))


def cmd_strategy(args):
    _set_root(args)
    from .config import get_config
    from .read_cmds import render_strategy

    cfg = get_config()
    print(render_strategy(cfg, topic=args.topic))


# --- tasks command (plural — inspection, distinct from `task` runner) ---


def cmd_tasks(args):
    """Dispatch `agent-os tasks {list,show}`."""
    _set_root(args)
    from .config import get_config
    from .task_cmd import render_task_list, render_task_list_json, render_task_show, task_exists

    cfg = get_config()
    action = getattr(args, "tasks_action", None)
    if action == "list":
        if getattr(args, "format", "human") == "json":
            print(render_task_list_json(cfg, status=getattr(args, "status", None), agent=getattr(args, "agent", None)))
        else:
            print(render_task_list(cfg, status=getattr(args, "status", None), agent=getattr(args, "agent", None)))
    elif action == "show":
        if not task_exists(cfg, args.task_id):
            print(
                f"Error: task '{args.task_id}' not found.\nHint: run `agent-os tasks list` to see all known task ids.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(render_task_show(cfg, args.task_id))
    else:
        print(
            "Error: missing subcommand.\nUsage: agent-os tasks {list|show <task-id>}",
            file=sys.stderr,
        )
        sys.exit(1)


# --- agent command ---


def cmd_agent(args):
    """Dispatch `agent-os agent {list,show}`."""
    _set_root(args)
    from .agent_cmd import agent_exists, render_agent_list, render_agent_list_json, render_agent_show
    from .config import get_config

    cfg = get_config()
    action = getattr(args, "agent_action", None)
    if action == "list":
        if getattr(args, "format", "human") == "json":
            print(render_agent_list_json(cfg))
        else:
            print(render_agent_list(cfg))
    elif action == "show":
        if not agent_exists(cfg, args.agent_id):
            print(
                f"Error: agent '{args.agent_id}' not found in registry.\n"
                "Hint: run `agent-os agent list` to see registered agents.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(render_agent_show(cfg, args.agent_id))
    else:
        print(
            "Error: missing subcommand.\nUsage: agent-os agent {list|show <agent-id>}",
            file=sys.stderr,
        )
        sys.exit(1)


# --- cost command ---


def cmd_cost(args):
    """Spend rollup — total, per-agent, per-task-type."""
    _set_root(args)
    from .config import get_config
    from .cost_cmd import render_cost, render_cost_json

    cfg = get_config()
    days = getattr(args, "days", 7)

    if getattr(args, "format", "human") == "json":
        print(render_cost_json(cfg, days=days))
    else:
        print(render_cost(cfg, days=days, by=getattr(args, "by", "agent")))


# --- health command ---


def cmd_health(args):
    """Render per-agent and system health scores."""
    _set_root(args)
    from .agent_cmd import agent_exists
    from .config import get_config
    from .health_cmd import render_health, render_health_json

    cfg = get_config()
    days = getattr(args, "days", 7)
    agent = getattr(args, "agent", None)

    if agent and not agent_exists(cfg, agent):
        print(
            f"Error: agent '{agent}' not found in registry.\nHint: run `agent-os agent list` to see registered agents.",
            file=sys.stderr,
        )
        sys.exit(1)

    if getattr(args, "format", "human") == "json":
        print(render_health_json(cfg, days=days, agent=agent))
    else:
        print(render_health(cfg, days=days, agent=agent))


# --- briefing command ---


def cmd_briefing(args):
    """Render the LLM-optimized session-bootstrap briefing to stdout."""
    _set_root(args)
    from .agent_cmd import agent_exists
    from .briefing import render_briefing
    from .config import get_config

    cfg = get_config()
    agent = getattr(args, "agent", None)
    if agent and not agent_exists(cfg, agent):
        print(
            f"Error: agent '{agent}' not found in registry.\nHint: run `agent-os agent list` to see registered agents.",
            file=sys.stderr,
        )
        sys.exit(1)

    output = render_briefing(cfg, depth=getattr(args, "depth", "short"), agent=agent)
    print(output)


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
    """Set up Config from --config TOML file, --root flag, or defaults.

    Records the resolved config source on ``args._config_source_kind`` and
    ``args._config_source_path`` so safety-sensitive commands (e.g. `budget`)
    can surface the provenance in their output and refuse to operate on
    accidental defaults. Kind is one of ``"explicit"``, ``"discovered"``,
    or ``"defaults"``.
    """
    from .config import Config, configure, load_dotenv

    config_path = getattr(args, "config", None)
    root = getattr(args, "root", None)

    source_kind: str
    source_path: Path | None

    if config_path:
        # Explicit TOML file
        toml_path = Path(config_path).resolve()
        cfg = Config.from_toml(Path(config_path))
        source_kind = "explicit"
        source_path = toml_path
    else:
        # Try TOML discovery
        toml_path = Config.discover_toml(Path(root).resolve() if root else None)
        if toml_path:
            cfg = Config.from_toml(toml_path)
            source_kind = "discovered"
            source_path = toml_path.resolve()
        else:
            # Fallback to root-only config
            resolved = Path(root).resolve() if root else Path.cwd()
            cfg = Config(company_root=resolved)
            source_kind = "defaults"
            source_path = None

    args._config_source_kind = source_kind
    args._config_source_path = source_path

    # Load .env from project root (before anything checks env vars)
    load_dotenv(cfg.company_root)

    # Also set env var for any subprocess that might need it
    os.environ["AGENT_OS_ROOT"] = str(cfg.company_root)
    configure(cfg)


def _require_config_source(args, command: str) -> None:
    """Exit non-zero if no agent-os.toml was discovered.

    Use this for commands whose safety depends on reading the same values
    the scheduler writes (budget caps, cost ledger). If the CLI falls back
    to defaults, those commands would report values unrelated to the
    running deployment — e.g. `$0.00 / $100.00` on a company whose real
    scheduler-state.json shows `$13.22 / $75.00`. Better to fail loudly.
    """
    if getattr(args, "_config_source_kind", None) == "defaults":
        print(
            f"ERROR: no agent-os.toml discovered — {command} refuses to run "
            "on default caps and costs.\n"
            "\n"
            "The CLI must read the same config the scheduler writes, otherwise "
            "budget numbers and circuit-breaker state are unrelated to the "
            "running deployment.\n"
            "\n"
            "Options:\n"
            "  - Run from inside a directory that has (or is under) an agent-os.toml\n"
            "  - Pass --config /path/to/agent-os.toml\n"
            "  - Set AGENT_OS_CONFIG=/path/to/agent-os.toml in the environment",
            file=sys.stderr,
        )
        sys.exit(2)


def _add_config_args(parser):
    """Add --root / --config — the minimum needed to locate a company.

    Use this on commands that don't invoke an agent (no model turns, no cost).
    """
    parser.add_argument("--root", default=None, help="Company root directory (default: current directory)")
    parser.add_argument("--config", default=None, help="Path to agent-os.toml config file")


def _add_common_args(parser):
    """Add arguments common to all agent-invoking subcommands.

    Superset of `_add_config_args` — includes `--max-turns` and `--max-budget`,
    which only make sense for commands that actually invoke an agent (cycle,
    task, run, standing-orders, drives, dream).
    """
    _add_config_args(parser)
    parser.add_argument("--max-turns", type=int, default=None, help="Override max turns for this invocation")
    parser.add_argument("--max-budget", type=float, default=None, help="Override max budget (USD) for this invocation")


# --- main entry point ---


_COMMAND_GROUPS_EPILOG = """\
Common commands, grouped by intent:

  Get oriented (run these in a new session)
    briefing          Dense LLM-optimized summary of company state (start here)
    status            Compact system status overview
    health            Per-agent and system health scores
    cost              Spend rollup by day / agent / task type

  Inspect
    agent {list,show} Registered agents and per-agent detail
    tasks {list,show} Tasks across all status directories
    messages <ch>     Broadcasts, threads, human inbox, agent inbox
    strategy <topic>  Drives, decisions, or proposals
    timeline          Merged activity log for a day

  Run an agent
    cycle <agent>             One work cycle (tasks, messages, threads)
    task <agent> <task-id>    A specific task
    drives <agent>            Drive consultation
    standing-orders <agent>   Standing orders if due
    dream <agent>             Nightly dream cycle
    run                       Cycle every registered agent once
    tick                      Scheduler tick (the one cron entry)

  Control
    budget-set         Update daily / weekly / monthly caps
    autonomy           Set per-agent autonomy level
    schedule-toggle    Flip scheduler features on/off
    backlog {promote,reject}  Move tasks out of backlog

  Create
    init <name>   Create a new company filesystem
    new <title>   Create a task

  Maintenance
    doctor        Diagnose system health issues
    digest        Daily health digest
    watchdog      Check agent liveness
    archive       Move stale items to _archive/
    manifest      Regenerate knowledge manifest
    update        Self-update agent-os from git
    cron          Manage the cron entry

Run `agent-os <command> --help` for details on any command.
"""


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level argparse parser.

    Extracted so tests can introspect the command surface without running it.
    """
    parser = argparse.ArgumentParser(
        prog="agent-os",
        description="The open-source operations layer for AI agents.",
        epilog=_COMMAND_GROUPS_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_get_version()}")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>", help="Run `agent-os <command> --help`")

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
    p_update = subparsers.add_parser(
        "update",
        help="Self-update agent-os (git checkout: pull+reinstall; wheel install: fetch latest GitHub release)",
    )
    p_update.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    p_update.add_argument(
        "--source",
        default=None,
        help=(
            "GitHub release source for wheel installs, format 'owner/repo@tag'. "
            "Overrides [update].source in agent-os.toml. "
            "Default: corvyd-ai/agent-os@latest. Ignored for git-checkout installs."
        ),
    )
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

    # briefing — LLM-optimized session bootstrap summary
    p_brief = subparsers.add_parser(
        "briefing",
        help="Print a dense, LLM-optimized summary of company state (run this first in a Claude session)",
    )
    p_brief.add_argument(
        "--depth",
        choices=["short", "full"],
        default="short",
        help="Briefing depth (short keeps it to one screen; full expands per-section detail)",
    )
    p_brief.add_argument("--agent", default=None, help="Scope the briefing to a single agent id")
    _add_config_args(p_brief)
    p_brief.set_defaults(func=cmd_briefing)

    # budget-set — mutate agent-os.toml budget caps
    p_budget_set = subparsers.add_parser("budget-set", help="Update daily/weekly/monthly budget caps in agent-os.toml")
    p_budget_set.add_argument("--daily", type=float, default=None, help="New daily cap in USD")
    p_budget_set.add_argument("--weekly", type=float, default=None, help="New weekly cap in USD")
    p_budget_set.add_argument("--monthly", type=float, default=None, help="New monthly cap in USD")
    _add_config_args(p_budget_set)
    p_budget_set.set_defaults(func=cmd_budget_set)

    # autonomy — set per-agent autonomy level
    p_autonomy = subparsers.add_parser("autonomy", help="Set per-agent autonomy level")
    p_autonomy.add_argument("agent_id")
    p_autonomy.add_argument("level", choices=["low", "medium", "high"])
    _add_config_args(p_autonomy)
    p_autonomy.set_defaults(func=cmd_autonomy)

    # schedule-toggle — flip scheduler master switch or sub-feature
    p_sched_tog = subparsers.add_parser("schedule-toggle", help="Flip the scheduler master switch or a sub-feature")
    p_sched_tog.add_argument(
        "kind",
        choices=["scheduler", "cycles", "standing-orders", "drives", "dreams"],
        help="Which scheduler feature to toggle",
    )
    p_sched_tog.add_argument("state", choices=["on", "off"])
    _add_config_args(p_sched_tog)
    p_sched_tog.set_defaults(func=cmd_schedule_toggle)

    # notifications — configure and test the notification system
    p_notif = subparsers.add_parser(
        "notifications",
        help="Configure and test the notification system",
    )
    _add_config_args(p_notif)
    notif_sub = p_notif.add_subparsers(dest="notif_action")

    p_notif_status = notif_sub.add_parser("status", help="Show current notification configuration")
    _add_config_args(p_notif_status)

    p_notif_events = notif_sub.add_parser(
        "events",
        help="List known event types with their effective severity",
    )
    _add_config_args(p_notif_events)

    p_notif_enable = notif_sub.add_parser("enable", help="Enable notifications globally")
    _add_config_args(p_notif_enable)

    p_notif_disable = notif_sub.add_parser("disable", help="Disable notifications globally")
    _add_config_args(p_notif_disable)

    p_notif_sev = notif_sub.add_parser("severity", help="Set the global minimum notification severity")
    p_notif_sev.add_argument("level", choices=["info", "warning", "critical"])
    _add_config_args(p_notif_sev)

    p_notif_event = notif_sub.add_parser(
        "event",
        help="Set or clear a per-event-type severity override",
    )
    p_notif_event.add_argument(
        "event_type",
        help="Event type (run `agent-os notifications events` to list known types)",
    )
    p_notif_event.add_argument(
        "severity",
        help='Severity ("info", "warning", "critical") or "clear" to remove the override',
    )
    _add_config_args(p_notif_event)

    p_notif_chan = notif_sub.add_parser(
        "channel",
        help="Toggle the file or desktop notification channel",
    )
    p_notif_chan.add_argument("channel", choices=["file", "desktop"])
    p_notif_chan.add_argument("state", choices=["on", "off"])
    _add_config_args(p_notif_chan)

    p_notif_web = notif_sub.add_parser(
        "webhook",
        help="Set or clear the notification webhook URL",
    )
    p_notif_web.add_argument("url", help='Webhook URL, or "clear" to remove it')
    _add_config_args(p_notif_web)

    p_notif_script = notif_sub.add_parser(
        "script",
        help="Set or clear the notification script path",
    )
    p_notif_script.add_argument("path", help='Script path, or "clear" to remove it')
    _add_config_args(p_notif_script)

    p_notif_test = notif_sub.add_parser(
        "test",
        help="Fire a test notification through all configured channels",
    )
    p_notif_test.add_argument(
        "--event",
        default="test_event",
        help="Event type to tag the test with (default: test_event)",
    )
    p_notif_test.add_argument(
        "--severity",
        choices=["info", "warning", "critical"],
        default="warning",
    )
    _add_config_args(p_notif_test)

    p_notif.set_defaults(func=cmd_notifications)

    # timeline — merged activity feed for a day
    p_timeline = subparsers.add_parser("timeline", help="Show merged activity log for a day")
    p_timeline.add_argument("--date", default=None, help="Date to show (YYYY-MM-DD). Default: today.")
    p_timeline.add_argument("--agent", default=None, help="Filter to a single agent")
    p_timeline.add_argument("--hide-idle", action="store_true", help="Hide cycle_idle entries")
    _add_config_args(p_timeline)
    p_timeline.set_defaults(func=cmd_timeline)

    # messages — inspect broadcasts, threads, human inbox, or an agent's inbox
    p_messages = subparsers.add_parser("messages", help="Inspect broadcasts, threads, or inboxes")
    p_messages.add_argument(
        "channel",
        choices=["broadcast", "threads", "human", "inbox"],
        help="Which message channel to inspect",
    )
    p_messages.add_argument("agent", nargs="?", default=None, help="Agent id (required for `inbox`)")
    _add_config_args(p_messages)
    p_messages.set_defaults(func=cmd_messages)

    # strategy — drives / decisions / proposals
    p_strategy = subparsers.add_parser("strategy", help="Show drives, decisions, or proposals")
    p_strategy.add_argument(
        "topic",
        choices=["drives", "decisions", "proposals"],
        help="Strategy topic to show: drives (strategy/drives.md), decisions (index of strategy/decisions/), or proposals (active + decided)",
    )
    _add_config_args(p_strategy)
    p_strategy.set_defaults(func=cmd_strategy)

    # tasks (plural) — read-only task inspection. Distinct from the `task`
    # runner command which executes a specific task for an agent.
    p_tasks = subparsers.add_parser("tasks", help="List or show tasks (inspection, not execution)")
    tasks_sub = p_tasks.add_subparsers(dest="tasks_action")

    p_tasks_list = tasks_sub.add_parser("list", help="List tasks (optionally filtered)")
    p_tasks_list.add_argument("--status", default=None, help="Filter by status (queued, in-progress, done, ...)")
    p_tasks_list.add_argument("--agent", default=None, help="Filter by assigned agent")
    p_tasks_list.add_argument("--format", choices=["human", "json"], default="human")
    _add_config_args(p_tasks_list)

    p_tasks_show = tasks_sub.add_parser("show", help="Show full detail for one task")
    p_tasks_show.add_argument("task_id", help="Task id")
    _add_config_args(p_tasks_show)

    p_tasks.set_defaults(func=cmd_tasks)

    # agent — inspect agents
    p_agent = subparsers.add_parser("agent", help="List or show registered agents")
    agent_sub = p_agent.add_subparsers(dest="agent_action")

    p_agent_list = agent_sub.add_parser("list", help="List all registered agents")
    p_agent_list.add_argument("--format", choices=["human", "json"], default="human", help="Output format")
    _add_config_args(p_agent_list)

    p_agent_show = agent_sub.add_parser("show", help="Show detail for one agent")
    p_agent_show.add_argument("agent_id", help="Agent id to show")
    _add_config_args(p_agent_show)

    p_agent.set_defaults(func=cmd_agent)

    # cost — spend rollup
    p_cost = subparsers.add_parser("cost", help="Show spend totals by day, agent, and task type")
    p_cost.add_argument("--days", type=int, default=7, help="Window in days (default: 7)")
    p_cost.add_argument(
        "--by", choices=["agent", "task-type"], default="agent", help="Breakdown dimension for human mode"
    )
    p_cost.add_argument("--format", choices=["human", "json"], default="human", help="Output format")
    _add_config_args(p_cost)
    p_cost.set_defaults(func=cmd_cost)

    # health — per-agent + system health scores
    p_health = subparsers.add_parser("health", help="Show per-agent and system health scores")
    p_health.add_argument("--agent", default=None, help="Scope the report to a single agent id")
    p_health.add_argument("--days", type=int, default=7, help="Window in days (default: 7)")
    p_health.add_argument(
        "--format",
        choices=["human", "json"],
        default="human",
        help="Output format: human (default) or json (for agents/scripts)",
    )
    _add_config_args(p_health)
    p_health.set_defaults(func=cmd_health)

    return parser


def main():
    parser = _build_parser()
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
