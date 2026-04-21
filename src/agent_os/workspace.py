"""agent-os workspace — git worktree lifecycle for the agentic SDLC.

Creates isolated workspaces (git worktrees + branches) for builder agents.
All git operations are infrastructure — agents never call this module.
The runner calls it to set up, validate, commit, and clean up workspaces.
"""

from __future__ import annotations

import contextlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Config, get_config


class WorkspaceError(Exception):
    """Raised when workspace operations fail."""


@dataclass
class Workspace:
    """An active worktree workspace for a task."""

    task_id: str
    branch: str  # e.g. "agent/task-2026-0412-001"
    worktree_path: Path  # e.g. ".worktrees/task-2026-0412-001/"
    code_dir: Path  # worktree_path / project_code_dir (the agent's cwd)


# --- Internal helpers ---


def _git(
    args: list[str],
    *,
    cwd: Path,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    """Run a git command. Raises WorkspaceError on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise WorkspaceError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
        return result
    except subprocess.TimeoutExpired as e:
        raise WorkspaceError(f"git {' '.join(args)} timed out after {timeout}s") from e
    except FileNotFoundError as e:
        raise WorkspaceError("git is not installed or not on PATH") from e


def _run_commands(
    commands: list[str],
    *,
    cwd: Path,
    timeout: int,
) -> tuple[bool, str]:
    """Run shell commands sequentially. Returns (all_passed, combined_output)."""
    output_parts: list[str] = []

    for cmd in commands:
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            combined = result.stdout + result.stderr
            output_parts.append(f"$ {cmd}\n{combined}")
            if result.returncode != 0:
                return False, "\n".join(output_parts)
        except subprocess.TimeoutExpired:
            output_parts.append(f"$ {cmd}\nTIMEOUT after {timeout}s")
            return False, "\n".join(output_parts)

    return True, "\n".join(output_parts)


def _has_remote(remote: str, *, cwd: Path) -> bool:
    """Check if a git remote exists."""
    try:
        result = subprocess.run(
            ["git", "remote"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return remote in result.stdout.splitlines()
    except Exception:
        return False


# --- Public API ---


def create_workspace(
    task_id: str,
    *,
    config: Config | None = None,
) -> Workspace:
    """Create a git worktree + branch for a task.

    1. Ensure worktrees_root exists
    2. Fetch latest default_branch from remote (if push enabled and remote exists)
    3. Create worktree with new branch agent/{task_id} from default_branch
    4. Return Workspace
    """
    cfg = config or get_config()
    repo = cfg.repo_root
    branch = f"agent/{task_id}"
    worktree_path = cfg.worktrees_root / task_id

    # Ensure worktrees directory exists
    cfg.worktrees_root.mkdir(parents=True, exist_ok=True)

    # Clean up stale worktree if it exists (from a previous failed run)
    if worktree_path.exists():
        with contextlib.suppress(WorkspaceError):
            _git(["worktree", "remove", str(worktree_path), "--force"], cwd=repo)

    # Clean up stale branch if it exists
    with contextlib.suppress(WorkspaceError):
        _git(["branch", "-D", branch], cwd=repo)

    # Fetch latest if remote exists
    if cfg.project_push and _has_remote(cfg.project_remote, cwd=repo):
        with contextlib.suppress(WorkspaceError):
            _git(["fetch", cfg.project_remote, cfg.project_default_branch], cwd=repo, timeout=120)

    # Create worktree with new branch from default_branch
    _git(
        ["worktree", "add", "-b", branch, str(worktree_path), cfg.project_default_branch],
        cwd=repo,
    )

    code_dir = worktree_path / cfg.project_code_dir if cfg.project_code_dir != "." else worktree_path

    return Workspace(
        task_id=task_id,
        branch=branch,
        worktree_path=worktree_path,
        code_dir=code_dir,
    )


def setup_workspace(
    workspace: Workspace,
    *,
    config: Config | None = None,
) -> tuple[bool, str]:
    """Run setup commands in the workspace.

    Returns (success, combined_output).
    """
    cfg = config or get_config()
    if not cfg.project_setup_commands:
        return True, ""

    return _run_commands(
        cfg.project_setup_commands,
        cwd=workspace.code_dir,
        timeout=cfg.project_setup_timeout,
    )


def validate_workspace(
    workspace: Workspace,
    *,
    config: Config | None = None,
) -> tuple[bool, str]:
    """Run validation commands in the workspace.

    Returns (all_passed, combined_output).
    """
    cfg = config or get_config()
    if not cfg.project_validate_commands:
        return True, ""

    return _run_commands(
        cfg.project_validate_commands,
        cwd=workspace.code_dir,
        timeout=cfg.project_validate_timeout,
    )


def _resolve_commit_identity(agent_id: str, cfg: Config) -> list[str]:
    """Return `-c user.email=... -c user.name=...` overrides for `git commit`.

    Looks up per-agent override first, then falls back to the project-level
    default. Returns an empty list when nothing is configured — in that case
    we defer to whatever the runtime's git config provides (legacy behavior).

    We inject these as command-line overrides rather than writing to git
    config so the setting is visible, scoped to a single commit, and cannot
    silently drift with host state. This is the fix for the Corvyd Apr 19
    incident where a fresh runtime had no user.email set and every commit
    failed with "Author identity unknown".
    """
    agent_override = cfg.project_agent_commit_authors.get(agent_id) or {}
    email = agent_override.get("email") or cfg.project_commit_author_email
    name = agent_override.get("name") or cfg.project_commit_author_name
    args: list[str] = []
    if email:
        args.extend(["-c", f"user.email={email}"])
    if name:
        args.extend(["-c", f"user.name={name}"])
    return args


def commit_workspace(
    workspace: Workspace,
    task_meta: dict,
    agent_id: str,
    *,
    config: Config | None = None,
) -> str | None:
    """Stage all changes and commit. Returns commit SHA or None if no changes."""
    cfg = config or get_config()
    wt = workspace.worktree_path

    # Stage all changes
    _git(["add", "-A"], cwd=wt)

    # Check if there are changes to commit
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=str(wt),
        capture_output=True,
    )
    if result.returncode == 0:
        return None  # Nothing to commit

    # Build commit message
    task_id = task_meta.get("id", workspace.task_id)
    title = task_meta.get("title", "Untitled task")
    priority = task_meta.get("priority", "medium")
    message = f"[{task_id}] {title}\n\nAgent: {agent_id}\nTask: {task_id}\nPriority: {priority}"

    identity_args = _resolve_commit_identity(agent_id, cfg)
    _git([*identity_args, "commit", "-m", message], cwd=wt)

    # Get the commit SHA
    sha_result = _git(["rev-parse", "HEAD"], cwd=wt)
    return sha_result.stdout.strip()


def has_uncommitted_changes(workspace: Workspace) -> bool:
    """Return True if the worktree has staged, unstaged, or untracked changes.

    Used on failure paths to decide whether the agent produced work worth
    preserving before the runner cleans up. Best-effort — on git/OS failure
    we return False so the caller falls through to the normal cleanup path.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(workspace.worktree_path),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except (subprocess.SubprocessError, OSError):
        return False


def salvage_commit(
    workspace: Workspace,
    task_meta: dict,
    agent_id: str,
    reason: str,
    *,
    config: Config | None = None,
) -> str | None:
    """Commit any uncommitted changes to preserve partial work after a failure.

    The resulting commit is flagged as a SALVAGE in the message body so a
    human reviewer can tell it apart from a normal task completion — the work
    it captures was not validated and may not even build.

    Returns the commit SHA, or None if there was nothing to commit or the
    commit itself failed (e.g. missing git identity). Swallows WorkspaceError
    because this runs from an already-failing path and must not re-raise.
    """
    cfg = config or get_config()
    wt = workspace.worktree_path

    try:
        _git(["add", "-A"], cwd=wt)

        diff_result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(wt),
            capture_output=True,
        )
        if diff_result.returncode == 0:
            return None

        task_id = task_meta.get("id", workspace.task_id)
        title = task_meta.get("title", "Untitled task")
        message = (
            f"[{task_id}] SALVAGE: {title}\n\n"
            f"Partial work preserved after: {reason}\n\n"
            f"Agent: {agent_id}\n"
            f"Task: {task_id}\n\n"
            f"This commit was made by the agent-os runner to preserve "
            f"in-progress work on a failure path. It has NOT been validated "
            f"and likely needs human review before merging."
        )

        identity_args = _resolve_commit_identity(agent_id, cfg)
        _git([*identity_args, "commit", "-m", message], cwd=wt)

        sha_result = _git(["rev-parse", "HEAD"], cwd=wt)
        return sha_result.stdout.strip()
    except WorkspaceError:
        return None


def push_workspace(
    workspace: Workspace,
    *,
    config: Config | None = None,
) -> tuple[bool, str]:
    """Push the workspace branch to remote.

    Only pushes if project_push is True and remote exists.
    Returns (success, output).
    """
    cfg = config or get_config()
    repo = cfg.repo_root

    if not cfg.project_push:
        return True, "Push disabled in config"

    if not _has_remote(cfg.project_remote, cwd=repo):
        return True, f"No remote '{cfg.project_remote}' — skipping push"

    try:
        result = _git(
            ["push", "-u", cfg.project_remote, workspace.branch],
            cwd=workspace.worktree_path,
            timeout=120,
        )
        return True, result.stdout + result.stderr
    except WorkspaceError as e:
        return False, str(e)


def cleanup_workspace(
    workspace: Workspace,
    *,
    delete_branch: bool = False,
    config: Config | None = None,
) -> None:
    """Remove the worktree and optionally the branch."""
    cfg = config or get_config()
    repo = cfg.repo_root

    if workspace.worktree_path.exists():
        with contextlib.suppress(WorkspaceError):
            _git(["worktree", "remove", str(workspace.worktree_path), "--force"], cwd=repo)

    if delete_branch:
        with contextlib.suppress(WorkspaceError):
            _git(["branch", "-D", workspace.branch], cwd=repo)


def get_workspace(
    task_id: str,
    *,
    config: Config | None = None,
) -> Workspace | None:
    """Check if a workspace exists for a task (for recovery)."""
    cfg = config or get_config()
    worktree_path = cfg.worktrees_root / task_id

    if not worktree_path.exists():
        return None

    branch = f"agent/{task_id}"
    code_dir = worktree_path / cfg.project_code_dir if cfg.project_code_dir != "." else worktree_path

    return Workspace(
        task_id=task_id,
        branch=branch,
        worktree_path=worktree_path,
        code_dir=code_dir,
    )
