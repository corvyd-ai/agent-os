"""agent-os project — onboard a git repo for the workspace SDLC.

The workspace SDLC (see ``workspace.py``) requires a handful of things to
be true about the company's repo before it works end-to-end:

- Remote is reachable from the runtime host with the runtime user's creds
- The runtime user can push (SSH key or HTTPS token configured)
- Default branch exists on the remote
- ``[project].setup`` / ``[project].validate`` commands actually run
- ``.worktrees/`` (or configured ``worktrees_dir``) is gitignored

Before this module, setting all that up was ~10 manual steps spread across
the runtime host, GitHub, and ``agent-os.toml``. Miss one and agents fail
silently with "Push failed (non-fatal)" logs.

This module provides:

- ``run_project_check(cfg)`` — diagnostic, zero side effects. Returns a
  ``ProjectCheckResult`` with one ``ProjectCheck`` per dimension.
- ``write_project_config(...)`` — write a ``[project]`` section to
  ``agent-os.toml`` (preserving other sections).
- ``ssh_setup_instructions(...)`` — human-readable guidance for setting
  up a deploy key when auth fails. Does not auto-generate keys (too many
  host-specific decisions — key location, runtime user, naming).

The CLI wraps these in ``agent-os project check`` and
``agent-os project init``.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, get_config


@dataclass
class ProjectCheck:
    """Result of a single project-readiness check."""

    name: str
    status: str  # "ok", "warning", "error", "skipped"
    detail: str = ""
    fix: str = ""


@dataclass
class ProjectCheckResult:
    """Aggregated project-readiness checks."""

    checks: list[ProjectCheck] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for c in self.checks if c.status == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for c in self.checks if c.status == "warning")

    @property
    def ok(self) -> int:
        return sum(1 for c in self.checks if c.status == "ok")

    @property
    def ready(self) -> bool:
        """True if the repo is ready for the workspace SDLC."""
        return self.errors == 0


# --- Individual checks ---


def _check_project_configured(cfg: Config) -> ProjectCheck:
    if cfg.project_enabled:
        return ProjectCheck(
            name="[project] configured",
            status="ok",
            detail=f"Default branch: {cfg.project_default_branch}; push: {cfg.project_push}",
        )
    return ProjectCheck(
        name="[project] configured",
        status="warning",
        detail="No [project] section (or no setup/validate commands) in agent-os.toml — workspace SDLC is inactive",
        fix="agent-os project init",
    )


def _check_repo_exists(cfg: Config) -> ProjectCheck:
    repo = cfg.repo_root
    git_dir = repo / ".git"
    if git_dir.exists():
        return ProjectCheck(name="Repo exists", status="ok", detail=f"Git repo at {repo}")
    return ProjectCheck(
        name="Repo exists",
        status="error",
        detail=f"No git repo at {repo}",
        fix=f"cd {repo} && git init  (or clone the intended remote)",
    )


def _check_remote_configured(cfg: Config) -> ProjectCheck:
    repo = cfg.repo_root
    result = _run_git(["remote", "get-url", cfg.project_remote], cwd=repo)
    if result.returncode == 0:
        url = result.stdout.strip()
        return ProjectCheck(name=f"Remote '{cfg.project_remote}' configured", status="ok", detail=url)
    return ProjectCheck(
        name=f"Remote '{cfg.project_remote}' configured",
        status="error",
        detail=f"No remote named '{cfg.project_remote}'",
        fix=f"cd {repo} && git remote add {cfg.project_remote} git@github.com:ORG/REPO.git",
    )


def _check_remote_reachable(cfg: Config) -> ProjectCheck:
    """Verify we can reach the remote — tests both network and auth."""
    repo = cfg.repo_root
    result = _run_git(["ls-remote", "--heads", cfg.project_remote], cwd=repo, timeout=20)
    if result.returncode == 0:
        return ProjectCheck(
            name="Remote reachable",
            status="ok",
            detail=f"Authenticated and reachable via {cfg.project_remote}",
        )

    err = (result.stderr or result.stdout or "").strip()
    is_auth = any(
        s in err.lower() for s in ("permission denied", "publickey", "authentication", "access denied", "403")
    )
    return ProjectCheck(
        name="Remote reachable",
        status="error",
        detail=f"git ls-remote failed: {err[:200]}",
        fix="agent-os project init --ssh-help  # for deploy-key setup steps"
        if is_auth
        else f"Verify '{cfg.project_remote}' URL and network",
    )


def _check_default_branch_exists(cfg: Config) -> ProjectCheck:
    """Confirm the configured default branch exists on the remote."""
    repo = cfg.repo_root
    result = _run_git(
        ["ls-remote", "--heads", cfg.project_remote, cfg.project_default_branch],
        cwd=repo,
        timeout=20,
    )
    if result.returncode != 0:
        return ProjectCheck(
            name="Default branch on remote",
            status="skipped",
            detail="Could not query remote (see 'Remote reachable' check)",
        )
    if result.stdout.strip():
        return ProjectCheck(
            name="Default branch on remote",
            status="ok",
            detail=f"{cfg.project_default_branch} exists on {cfg.project_remote}",
        )
    return ProjectCheck(
        name="Default branch on remote",
        status="error",
        detail=f"Branch '{cfg.project_default_branch}' not found on {cfg.project_remote}",
        fix="Either push the branch or change [project].default_branch in agent-os.toml",
    )


def _check_setup_commands_runnable(cfg: Config) -> ProjectCheck:
    """Lightweight check that setup commands' first tokens resolve on PATH."""
    return _check_commands_runnable("setup", cfg.project_setup_commands)


def _check_validate_commands_runnable(cfg: Config) -> ProjectCheck:
    """Same for validate commands."""
    return _check_commands_runnable("validate", cfg.project_validate_commands)


def _check_commands_runnable(label: str, commands: list[str]) -> ProjectCheck:
    if not commands:
        return ProjectCheck(
            name=f"{label} commands configured",
            status="warning" if label == "validate" else "ok",
            detail=f"No [project.{label}].commands set"
            + (" (recommended — validate gates your pushes)" if label == "validate" else ""),
        )

    missing = []
    for cmd in commands:
        first = cmd.strip().split()[0] if cmd.strip() else ""
        if not first:
            continue
        if shutil.which(first) is None:
            missing.append(first)

    if missing:
        return ProjectCheck(
            name=f"{label} commands runnable",
            status="error",
            detail=f"Missing from PATH: {', '.join(sorted(set(missing)))}",
            fix=f"Install {missing[0]} on the runtime host, or adjust [project.{label}].commands",
        )
    return ProjectCheck(
        name=f"{label} commands runnable",
        status="ok",
        detail=f"{len(commands)} command(s), all binaries on PATH",
    )


def _check_worktrees_ignored(cfg: Config) -> ProjectCheck:
    """Verify the worktrees directory is gitignored — stray worktree state
    in commits breaks everything."""
    repo = cfg.repo_root
    gitignore = repo / ".gitignore"
    worktrees_dir = cfg.project_worktrees_dir.rstrip("/")

    if not gitignore.exists():
        return ProjectCheck(
            name=".worktrees/ gitignored",
            status="warning",
            detail=f"No .gitignore at {repo}",
            fix=f"echo '{worktrees_dir}/' >> {gitignore}",
        )

    content = gitignore.read_text()
    patterns = [f"{worktrees_dir}/", f"{worktrees_dir}", f"/{worktrees_dir}/"]
    if any(p in content.splitlines() for p in patterns):
        return ProjectCheck(name=".worktrees/ gitignored", status="ok", detail=f"{worktrees_dir}/ in .gitignore")
    return ProjectCheck(
        name=".worktrees/ gitignored",
        status="warning",
        detail=f"{worktrees_dir}/ not in .gitignore — agent worktrees may leak into commits",
        fix=f"echo '{worktrees_dir}/' >> {gitignore}",
    )


def run_project_check(*, config: Config | None = None) -> ProjectCheckResult:
    """Run all project-readiness checks. Zero side effects."""
    cfg = config or get_config()
    result = ProjectCheckResult()

    result.checks.append(_check_project_configured(cfg))

    # If [project] isn't configured at all, skip the rest — they'd be noise.
    if not cfg.project_enabled:
        return result

    result.checks.append(_check_repo_exists(cfg))
    # If no repo, downstream checks are meaningless
    if not (cfg.repo_root / ".git").exists():
        return result

    result.checks.append(_check_remote_configured(cfg))
    remote_ok = result.checks[-1].status == "ok"

    if remote_ok:
        result.checks.append(_check_remote_reachable(cfg))
        if result.checks[-1].status == "ok":
            result.checks.append(_check_default_branch_exists(cfg))

    result.checks.append(_check_setup_commands_runnable(cfg))
    result.checks.append(_check_validate_commands_runnable(cfg))
    result.checks.append(_check_worktrees_ignored(cfg))

    return result


# --- Interactive init support ---


def write_project_config(
    toml_path: Path,
    *,
    default_branch: str = "main",
    push: bool = True,
    remote: str = "origin",
    setup_commands: list[str] | None = None,
    validate_commands: list[str] | None = None,
    on_failure: str = "retry",
    max_retries: int = 2,
) -> None:
    """Append or replace a [project] section in agent-os.toml.

    Preserves all other sections. If a [project] section already exists,
    this raises ValueError — callers should read the existing config and
    confirm overwrite with the user before calling.
    """
    if not toml_path.exists():
        raise FileNotFoundError(f"Config file not found: {toml_path}")

    existing = toml_path.read_text()
    if _has_project_section(existing):
        raise ValueError("[project] section already exists — remove it manually before re-initializing")

    lines = ["", "# Workspace SDLC: agents work in isolated git branches."]
    lines.append("# See docs/configuration.md for the full schema.")
    lines.append("[project]")
    lines.append(f'default_branch = "{default_branch}"')
    lines.append(f"push = {str(push).lower()}")
    if remote != "origin":
        lines.append(f'remote = "{remote}"')
    lines.append("")

    if setup_commands:
        lines.append("[project.setup]")
        lines.append("commands = [" + ", ".join(f'"{c}"' for c in setup_commands) + "]")
        lines.append("")

    if validate_commands:
        lines.append("[project.validate]")
        lines.append("commands = [" + ", ".join(f'"{c}"' for c in validate_commands) + "]")
        lines.append(f'on_failure = "{on_failure}"')
        lines.append(f"max_retries = {max_retries}")
        lines.append("")

    # Ensure we start on a new line
    separator = "" if existing.endswith("\n") else "\n"
    toml_path.write_text(existing + separator + "\n".join(lines) + "\n")


def _has_project_section(toml_text: str) -> bool:
    """Check if a [project] section already exists, ignoring comments."""
    for line in toml_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped in ("[project]", "[project.setup]", "[project.validate]"):
            return True
    return False


def ensure_worktrees_gitignored(cfg: Config) -> bool:
    """Append worktrees_dir to .gitignore if missing. Returns True if modified."""
    gitignore = cfg.repo_root / ".gitignore"
    worktrees_dir = cfg.project_worktrees_dir.rstrip("/")
    entry = f"{worktrees_dir}/"

    if not gitignore.exists():
        gitignore.write_text(f"# Agent worktrees (managed by agent-os)\n{entry}\n")
        return True

    content = gitignore.read_text()
    if entry in content.splitlines() or worktrees_dir in content.splitlines():
        return False

    separator = "" if content.endswith("\n") else "\n"
    gitignore.write_text(content + separator + f"\n# Agent worktrees (managed by agent-os)\n{entry}\n")
    return True


def ssh_setup_instructions(cfg: Config, *, remote_url: str = "") -> str:
    """Human-readable deploy-key setup guidance.

    Not prescriptive about key location / naming — too host-specific. We
    tell the operator what needs to be true and point at the GitHub UI.
    """
    url = remote_url or _get_remote_url(cfg)
    repo_hint = _parse_github_repo(url) if url else None

    lines = [
        "",
        "Push authentication needs to be configured for the runtime user.",
        "",
        "Option 1 — GitHub deploy key (recommended for single-repo deployments):",
        "",
        "  1. As the runtime user (e.g., `sudo -u corvyd -i`), generate a key:",
        "       ssh-keygen -t ed25519 -f ~/.ssh/agent-os -N '' -C 'agent-os@<host>'",
        "",
        "  2. Print the public key:",
        "       cat ~/.ssh/agent-os.pub",
        "",
        "  3. Add it as a deploy key on GitHub "
        + (
            f"(https://github.com/{repo_hint}/settings/keys/new)"
            if repo_hint
            else "(repo Settings → Deploy keys → Add deploy key)"
        )
        + ",",
        "     CHECK 'Allow write access'.",
        "",
        "  4. Tell SSH to use this key for github.com. Add to ~/.ssh/config:",
        "       Host github.com",
        "         IdentityFile ~/.ssh/agent-os",
        "         IdentitiesOnly yes",
        "",
        "  5. Verify:",
        f"       cd {cfg.repo_root} && git ls-remote {cfg.project_remote}",
        "",
        "Option 2 — HTTPS with a fine-grained token: set the remote URL to",
        "  https://x-access-token:<TOKEN>@github.com/ORG/REPO.git",
        "  (Discouraged — tokens end up on disk. Deploy keys are cleaner.)",
        "",
        "After setup, re-run: agent-os project check",
    ]
    return "\n".join(lines)


# --- Helpers ---


def _run_git(args: list[str], *, cwd: Path, timeout: int = 10) -> subprocess.CompletedProcess:
    """Run a git subcommand, returning the completed process (never raising)."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr=str(e))


def _get_remote_url(cfg: Config) -> str:
    result = _run_git(["remote", "get-url", cfg.project_remote], cwd=cfg.repo_root)
    return result.stdout.strip() if result.returncode == 0 else ""


def _parse_github_repo(url: str) -> str:
    """Extract 'org/repo' from a GitHub remote URL. Empty string if not parseable."""
    url = url.strip()
    for prefix in ("git@github.com:", "https://github.com/", "ssh://git@github.com/"):
        if url.startswith(prefix):
            tail = url[len(prefix) :]
            if tail.endswith(".git"):
                tail = tail[:-4]
            return tail
    return ""
