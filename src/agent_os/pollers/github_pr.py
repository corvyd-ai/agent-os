"""Layer-3: GitHub PR status poller.

Queries GitHub for PR state changes using the ``gh`` CLI.  Converts GitHub's
PR state model into the generic states the artifact store (layer 2) uses.

This module is the ONLY place that knows about GitHub's PR API response
format. It could be swapped for a GitLab or Gitea poller returning the
same ``PollResult`` protocol.

Usage:
    from agent_os.pollers.github_pr import poll_prs
    from agent_os.artifacts import Artifact

    results = poll_prs(artifacts, repo="corvyd-ai/agent-os")
"""

from __future__ import annotations

import json
import subprocess

from ..artifacts import Artifact
from . import PollResult

# ---------------------------------------------------------------------------
# GitHub state → artifact state mapping
# ---------------------------------------------------------------------------

_STATE_MAP: dict[str, str] = {
    "OPEN": "open",
    "CLOSED": "closed",
    "MERGED": "merged",
}

# GitHub check-suite conclusion → CI state
_CI_MAP: dict[str, str] = {
    "SUCCESS": "ci_passed",
    "FAILURE": "ci_failed",
    "PENDING": "ci_running",
    "NEUTRAL": "ci_passed",
    "CANCELLED": "ci_failed",
    "TIMED_OUT": "ci_failed",
    "ACTION_REQUIRED": "ci_running",
    "": "ci_running",  # no conclusion yet
}


# ---------------------------------------------------------------------------
# gh CLI helpers
# ---------------------------------------------------------------------------


def gh_available() -> bool:
    """Check if ``gh`` CLI is installed and authenticated."""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _query_prs(
    *,
    repo: str = "",
    limit: int = 200,
    timeout: int = 30,
) -> tuple[list[dict], str | None]:
    """Query PRs from GitHub via ``gh pr list``.

    Returns (prs, error).  On success error is None.
    """
    cmd = [
        "gh",
        "pr",
        "list",
        "--state",
        "all",
        "--limit",
        str(limit),
        "--json",
        "headRefName,state,url,number,mergeCommit,statusCheckRollup,reviews",
    ]
    if repo:
        cmd.extend(["--repo", repo])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            return [], f"gh pr list failed: {result.stderr.strip()}"
        prs = json.loads(result.stdout)
        return prs, None
    except FileNotFoundError:
        return [], "gh CLI not installed"
    except subprocess.TimeoutExpired:
        return [], "gh pr list timed out"
    except json.JSONDecodeError as e:
        return [], f"Invalid JSON from gh: {e}"


def _match_pr(artifact: Artifact, prs: list[dict]) -> dict | None:
    """Find the GitHub PR matching an artifact's branch."""
    for pr in prs:
        if pr.get("headRefName") == artifact.branch.removeprefix("agent/").replace(
            artifact.branch, artifact.branch
        ):
            return pr
        # Match on full branch name (agent/{task-id})
        branch_without_prefix = artifact.branch
        if pr.get("headRefName") == branch_without_prefix:
            return pr
        # Also match on just the task-id suffix
        if pr.get("headRefName") == f"agent/{artifact.task_id}":
            return pr
    return None


def _extract_detail(pr: dict) -> dict:
    """Extract artifact-relevant metadata from a GitHub PR JSON object."""
    detail: dict = {
        "pr_number": pr.get("number"),
        "pr_url": pr.get("url", ""),
    }

    # Merge commit info
    merge_commit = pr.get("mergeCommit")
    if merge_commit and isinstance(merge_commit, dict):
        detail["merge_sha"] = merge_commit.get("oid", "")

    # CI status from statusCheckRollup
    checks = pr.get("statusCheckRollup") or []
    if checks:
        # Overall status: any failure = failed, any pending = running, else passed
        states = set()
        for check in checks:
            conclusion = (check.get("conclusion") or "").upper()
            status = (check.get("status") or "").upper()
            if conclusion:
                states.add(conclusion)
            elif status == "IN_PROGRESS" or status == "QUEUED":
                states.add("PENDING")

        if "FAILURE" in states or "CANCELLED" in states or "TIMED_OUT" in states:
            detail["ci_status"] = "failed"
        elif "PENDING" in states:
            detail["ci_status"] = "running"
        elif states:
            detail["ci_status"] = "passed"

    return detail


def _determine_state(pr: dict, detail: dict, current_state: str) -> str | None:
    """Determine the new artifact state from a GitHub PR, or None if unchanged.

    State progression: pushed → ci_running → ci_passed/ci_failed → open → merged/closed

    We report the most granular actionable state. If CI is running, that
    takes precedence over "open" since the agent should wait. If CI has
    passed and the PR is still open, report "open". Merged/closed always win.
    """
    gh_state = _STATE_MAP.get(pr.get("state", "").upper(), "")

    if gh_state == "merged":
        return None if current_state == "merged" else "merged"

    if gh_state == "closed":
        return None if current_state == "closed" else "closed"

    # PR is open — determine sub-state from CI
    ci_status = detail.get("ci_status", "")
    if ci_status == "failed":
        target = "ci_failed"
    elif ci_status == "running":
        target = "ci_running"
    elif ci_status == "passed":
        target = "ci_passed"
    else:
        target = "open"

    return None if target == current_state else target


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def poll_prs(
    artifacts: list[Artifact],
    *,
    repo: str = "",
    timeout: int = 30,
) -> list[PollResult]:
    """Poll GitHub for status of tracked PR artifacts.

    Returns one ``PollResult`` per input artifact. ``new_state=None``
    means no change detected.
    """
    if not artifacts:
        return []

    prs, error = _query_prs(repo=repo, timeout=timeout)
    if error:
        return [PollResult(task_id=a.task_id, error=error) for a in artifacts]

    results: list[PollResult] = []
    for art in artifacts:
        pr = _match_pr(art, prs)
        if pr is None:
            # PR not found — might not have been created yet from the compare URL
            results.append(PollResult(task_id=art.task_id))
            continue

        detail = _extract_detail(pr)
        new_state = _determine_state(pr, detail, art.current_state)

        # Update the ref if we now know the PR URL and didn't before
        if not art.ref and detail.get("pr_url"):
            detail["update_ref"] = detail["pr_url"]

        results.append(
            PollResult(
                task_id=art.task_id,
                new_state=new_state,
                detail=detail,
            )
        )

    return results
