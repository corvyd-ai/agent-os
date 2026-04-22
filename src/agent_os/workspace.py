"""agent-os workspace — git worktree lifecycle for the agentic SDLC.

Creates isolated workspaces (git worktrees + branches) for builder agents.
All git operations are infrastructure — agents never call this module.
The runner calls it to set up, validate, commit, and clean up workspaces.

Design properties (target hardening, Apr 2026):
- The active worktree path is never blocked by leftover state. If the
  primary path is occupied, we either archive the occupant or fall back to
  a per-attempt path `{task-id}__attempt-N`.
- Failed/completed worktrees are archived under `{worktrees_root}/_archive/`
  with a status + timestamp suffix. The archive keeps the last N entries
  (configurable via `[project.archive]`). Archives give humans forensic
  material after failure and let agents inspect prior attempts.
- Cleanup failures are surfaced through `WorkspaceEvent` records returned
  to the caller, not silently suppressed. The runner logs them and emits
  notifications — this is how agents learn that the platform hit trouble.
- Branches are cut from `origin/{default}` after a successful fetch. If
  fetch fails we record a warning event and fall back to the local ref so
  the task can still run.
"""

from __future__ import annotations

import contextlib
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .config import Config, get_config


class WorkspaceError(Exception):
    """Raised when workspace operations fail."""


@dataclass
class WorkspaceEvent:
    """A notable thing that happened during a workspace operation.

    Returned alongside successful results so the runner can log and notify
    without raising. Events are the mechanism that makes platform behavior
    legible to agents — every WorkspaceEvent should translate into a log
    line and (if significant) a notification the agents can read.
    """

    kind: str  # e.g. "existing_worktree_archived", "fetch_failed", "per_attempt_path_used"
    message: str
    detail: dict = field(default_factory=dict)


@dataclass
class Workspace:
    """An active worktree workspace for a task."""

    task_id: str
    branch: str  # e.g. "agent/task-2026-0412-001"
    worktree_path: Path  # e.g. ".worktrees/task-2026-0412-001/"
    code_dir: Path  # worktree_path / project_code_dir (the agent's cwd)
    attempt: int = 1  # 1 for primary path, 2+ for per-attempt fallback paths
    events: list[WorkspaceEvent] = field(default_factory=list)


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


def _remote_url(remote: str, *, cwd: Path) -> str:
    """Return the URL of a git remote, or empty string if missing/failed."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", remote],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _is_github_remote(url: str) -> bool:
    """True if a remote URL looks like a GitHub repo (ssh or https)."""
    if not url:
        return False
    return "github.com" in url.lower()


def _timestamp() -> str:
    """UTC timestamp suitable for archive directory names (unique to the μs)."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _archive_dir_for(task_id: str, status: str, *, config: Config) -> Path:
    """Compute a fresh archive directory path for a worktree.

    Format: `{worktrees_archive_root}/{task-id}__{status}__{timestamp}/`
    Example: `.worktrees/_archive/task-2026-0421-002__completed__20260421T180512341592Z/`
    """
    return config.worktrees_archive_root / f"{task_id}__{status}__{_timestamp()}"


def _prune_archives(config: Config) -> list[Path]:
    """Prune old archive directories, keeping the most recent `keep_last`.

    Returns the list of pruned paths. Errors pruning a single entry are
    swallowed (best-effort); a directory that can't be removed stays and
    will be retried next prune. The archive root itself is never removed.
    """
    archive_root = config.worktrees_archive_root
    if not archive_root.exists():
        return []

    keep_last = max(0, config.project_archive_keep_last)
    entries: list[tuple[float, Path]] = []
    for child in archive_root.iterdir():
        if not child.is_dir():
            continue
        try:
            entries.append((child.stat().st_mtime, child))
        except OSError:
            continue

    entries.sort(reverse=True)  # newest first
    pruned: list[Path] = []
    for _, path in entries[keep_last:]:
        try:
            shutil.rmtree(path)
            pruned.append(path)
        except OSError:
            # Leave it; next prune will try again. Don't fail the caller.
            continue
    return pruned


def _force_cleanup_worktree(
    worktree_path: Path,
    branch: str | None,
    *,
    repo: Path,
) -> tuple[bool, list[str], str | None]:
    """Best-effort cleanup of a leftover worktree + branch.

    Tries in order:
      1. `git worktree remove --force {path}` — normal release
      2. `git worktree prune` — handles the case where git's admin dir is
         out of sync with the filesystem
      3. `shutil.rmtree(path)` — last resort if the directory still exists

    Then `git branch -D {branch}` if a branch name was provided.

    Returns `(success, steps_taken, error)`. `success` is True if the path
    no longer exists at the end AND (if branch was provided) the branch no
    longer exists. `steps_taken` describes what we actually tried so the
    caller can decide how loudly to report.
    """
    steps: list[str] = []
    last_error: str | None = None

    if worktree_path.exists():
        try:
            _git(["worktree", "remove", str(worktree_path), "--force"], cwd=repo)
            steps.append("worktree_remove_force")
        except WorkspaceError as e:
            last_error = str(e)
            steps.append("worktree_remove_force_failed")

    if worktree_path.exists():
        with contextlib.suppress(WorkspaceError):
            _git(["worktree", "prune"], cwd=repo)
            steps.append("worktree_prune")

    if worktree_path.exists():
        try:
            shutil.rmtree(worktree_path)
            steps.append("rmtree")
        except OSError as e:
            last_error = f"rmtree failed: {e}"
            steps.append("rmtree_failed")

    if branch:
        # Always run prune before branch delete — a stale worktree admin
        # entry will block `branch -D` with "branch is checked out".
        with contextlib.suppress(WorkspaceError):
            _git(["worktree", "prune"], cwd=repo)
        try:
            _git(["branch", "-D", branch], cwd=repo)
            steps.append("branch_delete")
        except WorkspaceError as e:
            # Not fatal on its own — if the branch doesn't exist that's fine,
            # and if it does and we couldn't delete it, the caller may still
            # decide to proceed with a per-attempt path.
            msg = str(e).lower()
            if "not found" in msg or "does not exist" in msg:
                pass  # already gone
            else:
                last_error = last_error or str(e)
                steps.append("branch_delete_failed")

    success = not worktree_path.exists()
    if branch and success:
        # Re-check branch existence; treat inability to delete as failure.
        br = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=str(repo),
            capture_output=True,
        )
        if br.returncode == 0:
            success = False

    return success, steps, last_error if not success else None


def _ff_local_default_branch(events: list[WorkspaceEvent], *, config: Config) -> None:
    """Best-effort fast-forward of the base clone's local default branch.

    After we've fetched `{remote}/{default_branch}`, attempt to update
    local `{default_branch}` to match. Only safe when the remote is strictly
    ahead of local (fast-forward territory). If local has diverged, or HEAD
    is currently on that branch with a dirty worktree, we record a warning
    event and leave local alone — never destructive.

    We never touch the worktree: if HEAD is on the default branch, we still
    update the ref via `git update-ref`, but only after confirming the
    worktree is clean so the branch/worktree don't get out of sync.
    """
    cfg = config
    repo = cfg.repo_root
    remote = cfg.project_remote
    branch = cfg.project_default_branch
    local_ref = f"refs/heads/{branch}"
    remote_ref = f"{remote}/{branch}"

    # Does the local branch exist? A fresh clone may only have the remote-
    # tracking ref; there's nothing to fast-forward in that case.
    show_local = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", local_ref],
        cwd=str(repo),
        capture_output=True,
    )
    if show_local.returncode != 0:
        return

    # Is local strictly an ancestor of remote? If so, FF is safe.
    is_ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", branch, remote_ref],
        cwd=str(repo),
        capture_output=True,
        timeout=10,
    )
    if is_ancestor.returncode == 1:
        # Diverged — local has commits not on remote. Don't touch it.
        events.append(
            WorkspaceEvent(
                kind="local_default_diverged",
                message=(
                    f"Local {branch} has diverged from {remote_ref}; not "
                    f"fast-forwarding. The base clone's `git log {branch}` "
                    f"will show stale state until a human resolves the "
                    f"divergence. Worktree is still cut from the fresh "
                    f"remote ref, so this is cosmetic — but it indicates "
                    f"someone committed directly to the base clone, which "
                    f"shouldn't happen in a service deployment."
                ),
                detail={"branch": branch, "remote_ref": remote_ref},
            )
        )
        return
    if is_ancestor.returncode != 0:
        # Unexpected error (e.g., remote ref not found after fetch). Skip.
        return

    # Check if remote is ahead of local (nothing to do if they match).
    same = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", branch],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=10,
    )
    remote_sha = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", remote_ref],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=10,
    )
    if same.returncode == 0 and remote_sha.returncode == 0 and same.stdout.strip() == remote_sha.stdout.strip():
        return  # Already in sync

    # Is HEAD currently on the default branch? If so we need to also keep
    # the worktree coherent — only safe if the worktree is clean.
    head_ref = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "HEAD"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=10,
    )
    head_on_default = head_ref.returncode == 0 and head_ref.stdout.strip() == local_ref
    if head_on_default:
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if dirty.returncode != 0 or dirty.stdout.strip():
            events.append(
                WorkspaceEvent(
                    kind="local_default_dirty",
                    message=(
                        f"Base clone has HEAD on {branch} with a dirty worktree; "
                        f"skipping fast-forward to avoid mixing uncommitted changes "
                        f"with updated HEAD. Agent worktrees are unaffected."
                    ),
                    detail={"branch": branch},
                )
            )
            return

    try:
        _git(["update-ref", local_ref, remote_ref], cwd=repo)
    except WorkspaceError as e:
        events.append(
            WorkspaceEvent(
                kind="local_default_ff_failed",
                message=f"Fast-forward of local {branch} failed: {e}",
                detail={"branch": branch, "error": str(e)},
            )
        )
        return

    # If HEAD is on the branch, reset the worktree to match the updated ref.
    # We only reach here with a clean worktree, so this is non-destructive.
    if head_on_default:
        with contextlib.suppress(WorkspaceError):
            _git(["reset", "--hard", remote_ref], cwd=repo)


def _next_attempt_path_and_branch(
    task_id: str,
    *,
    config: Config,
) -> tuple[Path, str, int]:
    """Return the next available `{task-id}__attempt-N` path + branch + N.

    N starts at 2 (attempt 1 is the primary path). Caller should only reach
    this when primary cleanup failed — we need to guarantee a fresh path.
    """
    n = 2
    while True:
        path = config.worktrees_root / f"{task_id}__attempt-{n}"
        branch = f"agent/{task_id}--attempt-{n}"
        if not path.exists():
            br = subprocess.run(
                ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
                cwd=str(config.repo_root),
                capture_output=True,
            )
            if br.returncode != 0:  # branch doesn't exist
                return path, branch, n
        n += 1
        if n > 99:
            # Pathological — 99 stuck attempts means something is very wrong.
            # Return anyway; the caller will surface the failure.
            return path, branch, n


# --- Public API ---


def create_workspace(
    task_id: str,
    *,
    config: Config | None = None,
) -> Workspace:
    """Create a git worktree + branch for a task.

    Lifecycle:
      1. Ensure worktrees_root (and _archive subdir, if enabled) exist.
      2. If the primary path is occupied by leftover state, either archive
         it (default) or force-delete it, then retry. If the primary path
         still can't be freed, fall back to a per-attempt path.
      3. Fetch `{remote}/{default_branch}`. On failure, record a warning
         event and use the local ref as fallback.
      4. Create worktree + branch from the freshest available base ref.
      5. Return the Workspace. Non-fatal anomalies (archived leftover,
         fetch failed, per-attempt fallback used) are attached as events
         on the Workspace so the runner can log + notify.
    """
    cfg = config or get_config()
    repo = cfg.repo_root
    events: list[WorkspaceEvent] = []

    # Ensure root directories exist.
    cfg.worktrees_root.mkdir(parents=True, exist_ok=True)
    if cfg.project_archive_enabled:
        cfg.worktrees_archive_root.mkdir(parents=True, exist_ok=True)

    primary_path = cfg.worktrees_root / task_id
    primary_branch = f"agent/{task_id}"

    # --- Free the primary path if occupied ---
    if primary_path.exists():
        archived_path: Path | None = None
        if cfg.project_archive_enabled:
            try:
                target = _archive_dir_for(task_id, "leftover", config=cfg)
                shutil.move(str(primary_path), str(target))
                archived_path = target
                with contextlib.suppress(WorkspaceError):
                    _git(["worktree", "prune"], cwd=repo)
                events.append(
                    WorkspaceEvent(
                        kind="existing_worktree_archived",
                        message=(
                            f"Found leftover worktree at {primary_path}; moved to "
                            f"{target} before creating a fresh workspace."
                        ),
                        detail={"from": str(primary_path), "to": str(target)},
                    )
                )
            except OSError as e:
                events.append(
                    WorkspaceEvent(
                        kind="existing_worktree_archive_failed",
                        message=(
                            f"Could not archive leftover worktree at {primary_path}: {e}. "
                            f"Falling back to force-cleanup."
                        ),
                        detail={"path": str(primary_path), "error": str(e)},
                    )
                )

        if primary_path.exists():
            # Archive either disabled or failed — try force-cleanup.
            success, steps, err = _force_cleanup_worktree(primary_path, primary_branch, repo=repo)
            if success:
                events.append(
                    WorkspaceEvent(
                        kind="existing_worktree_force_removed",
                        message=f"Force-cleaned leftover worktree at {primary_path}.",
                        detail={"path": str(primary_path), "steps": steps},
                    )
                )
            else:
                events.append(
                    WorkspaceEvent(
                        kind="existing_worktree_cleanup_failed",
                        message=(
                            f"Could not clean up leftover worktree at {primary_path} "
                            f"({err}); will use per-attempt path."
                        ),
                        detail={"path": str(primary_path), "steps": steps, "error": err or ""},
                    )
                )
        # If we archived, the branch might also be stale (the archived dir
        # no longer holds it checked out). Clean the branch ref so our new
        # worktree can use the primary name. Non-fatal.
        if archived_path is not None:
            with contextlib.suppress(WorkspaceError):
                _git(["branch", "-D", primary_branch], cwd=repo)

    # --- Pick the actual path/branch we'll use ---
    if primary_path.exists():
        worktree_path, branch, attempt = _next_attempt_path_and_branch(task_id, config=cfg)
        events.append(
            WorkspaceEvent(
                kind="per_attempt_path_used",
                message=(
                    f"Primary path still occupied after cleanup; using {worktree_path} "
                    f"(attempt {attempt}) with branch {branch}."
                ),
                detail={
                    "primary": str(primary_path),
                    "chosen": str(worktree_path),
                    "attempt": attempt,
                    "branch": branch,
                },
            )
        )
    else:
        worktree_path = primary_path
        branch = primary_branch
        attempt = 1

    # --- Fetch; pick the freshest base ref we can ---
    base_ref = cfg.project_default_branch
    has_remote = cfg.project_push and _has_remote(cfg.project_remote, cwd=repo)
    if has_remote:
        try:
            _git(
                ["fetch", cfg.project_remote, cfg.project_default_branch],
                cwd=repo,
                timeout=120,
            )
            # Branch from the freshly-fetched remote ref so the base is never
            # stale. Prevents PR-time merge conflicts from days-old local main.
            base_ref = f"{cfg.project_remote}/{cfg.project_default_branch}"
        except WorkspaceError as e:
            events.append(
                WorkspaceEvent(
                    kind="fetch_failed",
                    message=(
                        f"Fetch of {cfg.project_remote}/{cfg.project_default_branch} failed; "
                        f"workspace will branch from local {cfg.project_default_branch} "
                        f"and may produce PR-time merge conflicts. Error: {e}"
                    ),
                    detail={
                        "remote": cfg.project_remote,
                        "branch": cfg.project_default_branch,
                        "error": str(e),
                    },
                )
            )

        # Fast-forward the local default branch to match the remote so the
        # base clone's own `main` doesn't drift forever. Worktrees are
        # already cut from origin/main so this is cosmetic for the SDLC —
        # but without it, a long-running service deployment's base clone
        # ends up with `git log main` showing state from the day the clone
        # was made. Only fast-forwards: if local has diverged (someone
        # committed on main directly), we record a warning and leave it
        # alone rather than destroy work.
        _ff_local_default_branch(events, config=cfg)

    # --- Create the worktree + branch ---
    _git(
        ["worktree", "add", "-b", branch, str(worktree_path), base_ref],
        cwd=repo,
    )

    code_dir = worktree_path / cfg.project_code_dir if cfg.project_code_dir != "." else worktree_path

    return Workspace(
        task_id=task_id,
        branch=branch,
        worktree_path=worktree_path,
        code_dir=code_dir,
        attempt=attempt,
        events=events,
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
) -> tuple[bool, list[str], str | None]:
    """Remove the worktree and optionally the branch.

    Used for cases where the worktree has no forensic value (setup
    failures, empty tasks). For completed/failed-with-work tasks, prefer
    `archive_workspace` so the files survive.

    Returns `(success, steps_taken, error)` — same shape as
    `_force_cleanup_worktree`. Callers that used to ignore the return value
    still can; hardened callers log + notify when `success is False`.
    """
    cfg = config or get_config()
    branch = workspace.branch if delete_branch else None
    return _force_cleanup_worktree(workspace.worktree_path, branch, repo=cfg.repo_root)


def archive_workspace(
    workspace: Workspace,
    status: str,
    *,
    config: Config | None = None,
) -> tuple[Path | None, list[WorkspaceEvent]]:
    """Archive a worktree for forensics, pruning to `keep_last`.

    `status` is one of "completed", "failed", "salvaged", "no_changes", etc. —
    it lands in the archive directory name so humans can scan the archive
    and see at a glance what happened.

    Semantics:
      - Moves the worktree directory under `_archive/{id}__{status}__{ts}/`.
      - Runs `git worktree prune` so git forgets the old location.
      - Does NOT delete the branch — commits are in the branch, which is
        the forensic record humans and agents can check out later.
      - Prunes older archives to `project_archive_keep_last`.

    If archiving is disabled in config OR the move fails, falls through to
    `_force_cleanup_worktree` (delete). Returns `(archive_path, events)`.
    `archive_path` is None when we fell through to delete. Events describe
    any fallbacks so the runner can log and notify.
    """
    cfg = config or get_config()
    repo = cfg.repo_root
    events: list[WorkspaceEvent] = []
    wt = workspace.worktree_path

    if not wt.exists():
        # Nothing to do — just prune any stale git admin entry.
        with contextlib.suppress(WorkspaceError):
            _git(["worktree", "prune"], cwd=repo)
        return None, events

    if not cfg.project_archive_enabled:
        success, steps, err = _force_cleanup_worktree(wt, None, repo=repo)
        if not success:
            events.append(
                WorkspaceEvent(
                    kind="cleanup_failed",
                    message=f"Could not remove worktree {wt}: {err}",
                    detail={"path": str(wt), "steps": steps, "error": err or ""},
                )
            )
        return None, events

    cfg.worktrees_archive_root.mkdir(parents=True, exist_ok=True)
    target = _archive_dir_for(workspace.task_id, status, config=cfg)

    try:
        shutil.move(str(wt), str(target))
    except OSError as e:
        events.append(
            WorkspaceEvent(
                kind="archive_move_failed",
                message=(
                    f"Could not archive worktree {wt} to {target}: {e}. "
                    f"Falling back to force-cleanup so the path is freed."
                ),
                detail={"from": str(wt), "to": str(target), "error": str(e)},
            )
        )
        success, steps, err = _force_cleanup_worktree(wt, None, repo=repo)
        if not success:
            events.append(
                WorkspaceEvent(
                    kind="cleanup_failed",
                    message=f"Could not remove worktree {wt} after archive failure: {err}",
                    detail={"path": str(wt), "steps": steps, "error": err or ""},
                )
            )
        return None, events

    # Move succeeded — clean up git's view of the old path.
    with contextlib.suppress(WorkspaceError):
        _git(["worktree", "prune"], cwd=repo)

    # Prune old archives — best-effort, never fails the caller.
    pruned = _prune_archives(cfg)
    if pruned:
        events.append(
            WorkspaceEvent(
                kind="archives_pruned",
                message=f"Pruned {len(pruned)} old archive(s) to keep last {cfg.project_archive_keep_last}.",
                detail={"pruned_count": len(pruned), "keep_last": cfg.project_archive_keep_last},
            )
        )

    return target, events


_PR_URL_RE = re.compile(r"https://github\.com/[^\s]+/pull/\d+")


def open_pull_request(
    workspace: Workspace,
    task_meta: dict,
    agent_id: str,
    *,
    config: Config | None = None,
) -> tuple[bool, str | None, str]:
    """Open a pull request for the workspace branch via `gh pr create`.

    Returns `(ok, url, message)`:
      - `ok=True, url="https://github.com/…/pull/N", message=""` on success
      - `ok=True, url=None, message="skipped: …"` on intentional skip
        (push disabled, PR disabled, non-GitHub remote, etc.)
      - `ok=False, url=None, message="error …"` on failure

    GitHub-only for now. Non-fatal by design — the branch is already pushed
    and a human can always open the PR manually.
    """
    cfg = config or get_config()
    repo = cfg.repo_root

    if not cfg.project_pull_request_enabled:
        return True, None, "skipped: [project.pull_request] disabled"
    if not cfg.project_push:
        return True, None, "skipped: [project].push is disabled — no pushed branch to PR"
    if not _has_remote(cfg.project_remote, cwd=repo):
        return True, None, f"skipped: remote '{cfg.project_remote}' is not configured"

    url = _remote_url(cfg.project_remote, cwd=repo)
    if not _is_github_remote(url):
        return True, None, f"skipped: remote '{cfg.project_remote}' ({url}) is not a GitHub repo"

    # Verify gh is installed + authenticated. `gh auth status` returns 0
    # when authenticated to any host — good enough signal.
    gh_check = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if gh_check.returncode != 0:
        return (
            False,
            None,
            f"gh not authenticated: {(gh_check.stderr or gh_check.stdout).strip()[:300]}",
        )

    task_id = task_meta.get("id", workspace.task_id)
    title = task_meta.get("title", "Untitled task")
    priority = task_meta.get("priority", "medium")
    description = task_meta.get("description", "") or ""

    base_branch = cfg.project_pull_request_base_branch or cfg.project_default_branch

    body_parts = [
        f"Automated PR from agent-os for task `{task_id}`.",
        "",
        f"- **Agent:** `{agent_id}`",
        f"- **Task:** `{task_id}`",
        f"- **Priority:** {priority}",
        f"- **Branch:** `{workspace.branch}`",
    ]
    if workspace.attempt > 1:
        body_parts.append(f"- **Attempt:** {workspace.attempt} (primary path was occupied)")
    body_parts.append("")
    if description.strip():
        body_parts.extend(["## Task description", "", description.strip(), ""])
    body_parts.extend(
        [
            "---",
            "",
            "_Opened by agent-os. See the task file and commit history for details._",
        ]
    )
    body = "\n".join(body_parts)

    pr_title = f"[{task_id}] {title}"
    args = [
        "gh",
        "pr",
        "create",
        "--base",
        base_branch,
        "--head",
        workspace.branch,
        "--title",
        pr_title,
        "--body",
        body,
    ]
    if cfg.project_pull_request_draft:
        args.append("--draft")

    try:
        result = subprocess.run(
            args,
            cwd=str(workspace.worktree_path) if workspace.worktree_path.exists() else str(repo),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return False, None, "gh pr create timed out after 60s"
    except FileNotFoundError:
        return False, None, "gh CLI not installed"

    combined = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        return False, None, f"gh pr create failed: {combined.strip()[:500]}"

    match = _PR_URL_RE.search(combined)
    url = match.group(0) if match else None
    return True, url, combined.strip()


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
