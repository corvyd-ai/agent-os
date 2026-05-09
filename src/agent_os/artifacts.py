"""Layer-2: Artifact lifecycle store — provider-agnostic tracking of task outputs.

Tracks artifacts (PRs, commits, deploys) produced by workspace SDLC tasks.
One JSON file per artifact, keyed by task ID, stored at
``{company_root}/state/artifacts/{task-id}.json``.

This module knows nothing about GitHub, GitLab, or any specific provider.
It stores state, records transitions, and surfaces pending items for the
composer.  Provider-specific polling lives in ``pollers/`` (layer 3).

Usage:
    from agent_os.artifacts import load_artifact, record_transition

    art = load_artifact("task-2026-0504-001", config=cfg)
    art = record_transition("task-2026-0504-001", "merged",
                            detail={"merge_sha": "abc123"}, config=cfg)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from .config import Config, get_config

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class StateEntry:
    """A single point-in-time state transition."""

    state: str  # "pushed", "ci_running", "ci_passed", "ci_failed", "open", "merged", "closed", "deployed"
    at: str  # ISO timestamp
    detail: dict = field(default_factory=dict)


@dataclass
class Artifact:
    """A tracked artifact produced by a workspace SDLC task."""

    task_id: str
    agent_id: str
    artifact_type: str  # "github_pr", "git_commit"
    provider: str  # "github", "local"
    ref: str  # canonical reference — PR URL or commit SHA
    branch: str
    current_state: str
    created_at: str
    updated_at: str
    history: list[StateEntry] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Artifact:
        """Deserialize from a dict (as read from JSON on disk)."""
        history = [StateEntry(**entry) for entry in data.get("history", [])]
        return cls(
            task_id=data["task_id"],
            agent_id=data.get("agent_id", ""),
            artifact_type=data.get("artifact_type", ""),
            provider=data.get("provider", ""),
            ref=data.get("ref", ""),
            branch=data.get("branch", ""),
            current_state=data.get("current_state", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            history=history,
            metadata=data.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Store operations
# ---------------------------------------------------------------------------


def _artifacts_dir(*, config: Config | None = None) -> Path:
    """Return the artifacts directory, creating it if needed."""
    cfg = config or get_config()
    d = cfg.company_root / "state" / "artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now_iso(*, config: Config | None = None) -> str:
    cfg = config or get_config()
    return datetime.now(cfg.tz).isoformat()


def load_artifact(task_id: str, *, config: Config | None = None) -> Artifact | None:
    """Load a single artifact by task ID.  Returns None if not found."""
    path = _artifacts_dir(config=config) / f"{task_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return Artifact.from_dict(data)
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def save_artifact(artifact: Artifact, *, config: Config | None = None) -> Path:
    """Write artifact JSON to disk.  Returns the file path."""
    path = _artifacts_dir(config=config) / f"{artifact.task_id}.json"
    path.write_text(json.dumps(artifact.to_dict(), indent=2) + "\n")
    return path


def list_artifacts(
    *,
    state: str | None = None,
    stale_threshold_hours: float | None = None,
    config: Config | None = None,
) -> list[Artifact]:
    """List all tracked artifacts, optionally filtering.

    Args:
        state: if set, only return artifacts with this current_state
        stale_threshold_hours: if set, only return artifacts created more than
            this many hours ago that are NOT in a terminal state
        config: agent-os config
    """
    d = _artifacts_dir(config=config)
    results: list[Artifact] = []
    for path in sorted(d.glob("*.json")):
        art = load_artifact(path.stem, config=config)
        if art is None:
            continue
        if state is not None and art.current_state != state:
            continue
        results.append(art)

    if stale_threshold_hours is not None:
        cfg = config or get_config()
        now = datetime.now(cfg.tz)
        terminal = {"merged", "closed", "deployed"}
        filtered = []
        for art in results:
            if art.current_state in terminal:
                continue
            try:
                created = datetime.fromisoformat(art.created_at)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=now.tzinfo)
                age_hours = (now - created).total_seconds() / 3600
                if age_hours > stale_threshold_hours:
                    filtered.append(art)
            except (ValueError, TypeError):
                filtered.append(art)
        return filtered

    return results


def record_transition(
    task_id: str,
    new_state: str,
    detail: dict | None = None,
    *,
    config: Config | None = None,
) -> Artifact | None:
    """Append a state transition to an artifact's history.

    Returns the updated artifact, or None if the artifact doesn't exist.
    Idempotent: if current_state already == new_state, no-op.
    """
    art = load_artifact(task_id, config=config)
    if art is None:
        return None

    # Idempotent — don't record duplicate consecutive states
    if art.current_state == new_state:
        return art

    now = _now_iso(config=config)
    entry = StateEntry(state=new_state, at=now, detail=detail or {})
    art.history.append(entry)
    art.current_state = new_state
    art.updated_at = now

    # Merge detail into metadata for important fields
    if detail:
        for key in ("merge_sha", "merged_at", "ci_status", "deployed_in"):
            if key in detail:
                art.metadata[key] = detail[key]

    save_artifact(art, config=config)

    # Side-effect: if merged, write back to the task's frontmatter
    if new_state == "merged":
        writeback_merge_to_task(task_id, art, config=config)

    return art


# ---------------------------------------------------------------------------
# Artifact creation (called from runner after workspace commit/push)
# ---------------------------------------------------------------------------


def create_artifact(
    task_id: str,
    agent_id: str,
    *,
    artifact_type: str = "github_pr",
    provider: str = "github",
    ref: str = "",
    branch: str = "",
    sha: str = "",
    config: Config | None = None,
) -> Artifact:
    """Create a new artifact record after a workspace task completes."""
    now = _now_iso(config=config)
    initial_state = "pushed"
    metadata: dict = {}
    if sha:
        metadata["commit_sha"] = sha

    art = Artifact(
        task_id=task_id,
        agent_id=agent_id,
        artifact_type=artifact_type,
        provider=provider,
        ref=ref,
        branch=branch,
        current_state=initial_state,
        created_at=now,
        updated_at=now,
        history=[StateEntry(state=initial_state, at=now, detail={"sha": sha} if sha else {})],
        metadata=metadata,
    )
    save_artifact(art, config=config)
    return art


# ---------------------------------------------------------------------------
# Frontmatter writeback
# ---------------------------------------------------------------------------


def writeback_merge_to_task(
    task_id: str,
    artifact: Artifact,
    *,
    config: Config | None = None,
) -> bool:
    """Write merge metadata into the originating task's frontmatter.

    Searches done/ and in-review/ for the task file. Adds pr_url,
    merged (bool), and merge_sha fields. Returns True if writeback succeeded.
    """
    cfg = config or get_config()
    for search_dir in (cfg.tasks_done, cfg.tasks_in_review):
        if not search_dir.exists():
            continue
        for candidate in search_dir.glob(f"{task_id}*"):
            if not candidate.name.endswith(".md"):
                continue
            try:
                text = candidate.read_text()
                if not text.startswith("---"):
                    continue
                parts = text.split("---", 2)
                if len(parts) < 3:
                    continue
                meta = yaml.safe_load(parts[1]) or {}
                meta["merged"] = True
                merge_sha = artifact.metadata.get("merge_sha", "")
                if merge_sha:
                    meta["merge_sha"] = merge_sha
                if artifact.ref:
                    meta["pr_url"] = artifact.ref
                body = parts[2]
                content = "---\n" + yaml.dump(meta, default_flow_style=False, sort_keys=False) + "---" + body
                candidate.write_text(content)
                return True
            except (OSError, yaml.YAMLError):
                continue
    return False


# ---------------------------------------------------------------------------
# Deploy verification
# ---------------------------------------------------------------------------


def mark_deployed(
    task_id: str,
    version: str,
    *,
    config: Config | None = None,
) -> Artifact | None:
    """Record that a merged artifact's code was deployed at the given version."""
    art = load_artifact(task_id, config=config)
    if art is None:
        return None
    if art.current_state not in ("merged", "deployed"):
        return art  # only mark merged PRs as deployed

    now = _now_iso(config=config)
    art.metadata["deployed_in"] = version
    entry = StateEntry(state="deployed", at=now, detail={"version": version})
    art.history.append(entry)
    art.current_state = "deployed"
    art.updated_at = now
    save_artifact(art, config=config)
    return art


def correlate_deploy(
    version: str,
    pr_refs: list[str],
    *,
    config: Config | None = None,
) -> list[Artifact]:
    """Correlate a deployment to its merged PRs.

    Given a version string and a list of PR references (URLs or branch names)
    included in the deploy, mark matching merged artifacts as deployed.

    Returns the list of artifacts that were updated.
    """
    all_arts = list_artifacts(config=config)
    updated: list[Artifact] = []
    for art in all_arts:
        if art.current_state != "merged":
            continue
        # Match by ref (PR URL) or branch name
        if art.ref in pr_refs or art.branch in pr_refs:
            result = mark_deployed(art.task_id, version, config=config)
            if result:
                updated.append(result)
    return updated


# ---------------------------------------------------------------------------
# Composer integration: pending artifacts digest
# ---------------------------------------------------------------------------


_TERMINAL_STATES = {"closed", "deployed"}


def get_pending_artifacts(*, config: Config | None = None) -> list[Artifact]:
    """Return artifacts that are NOT in a terminal state.

    These are items an agent should know about — open PRs, merged but
    not yet deployed, CI failures, etc.
    """
    all_arts = list_artifacts(config=config)
    return [a for a in all_arts if a.current_state not in _TERMINAL_STATES]


def format_artifacts_digest(artifacts: list[Artifact]) -> str:
    """Format pending artifacts for system prompt injection.

    Produces a compact summary with CI failures surfaced first (higher salience).
    """
    if not artifacts:
        return ""

    # Partition: CI failures first (high salience), then everything else
    ci_failures: list[Artifact] = []
    others: list[Artifact] = []
    for art in artifacts:
        if art.current_state == "ci_failed":
            ci_failures.append(art)
        else:
            others.append(art)

    lines: list[str] = ["# Pending Artifacts\n"]

    if ci_failures:
        lines.append("## ⚠ CI Failures (action required)\n")
        for art in ci_failures:
            lines.append(f"- **{art.task_id}** ({art.artifact_type}): CI failed — {art.ref}")
            ci_detail = art.metadata.get("ci_status", "")
            if ci_detail:
                lines.append(f"  Status: {ci_detail}")
        lines.append("")

    if others:
        # Group by state for a compact digest
        by_state: dict[str, list[Artifact]] = {}
        for art in others:
            by_state.setdefault(art.current_state, []).append(art)

        summary_parts = []
        for state, arts in sorted(by_state.items()):
            summary_parts.append(f"{len(arts)} {state}")
        lines.append(f"Summary: {', '.join(summary_parts)}\n")

        for art in others:
            deploy_note = ""
            if art.current_state == "merged" and "deployed_in" not in art.metadata:
                deploy_note = " — deploy verification pending"
            lines.append(f"- **{art.task_id}** ({art.current_state}): {art.ref}{deploy_note}")

    return "\n".join(lines)
