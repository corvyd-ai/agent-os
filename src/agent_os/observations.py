"""agent-os observations — structured reality-grounding artifacts.

Observe-cycles produce machine-readable observation artifacts that record
what an agent actually saw when it looked at the world. These artifacts
are stored per-agent and surfaced in subsequent cycle briefings, replacing
"remembered" state with verified state.

Architecture layer: middleware (bridges kernel scheduler with application
cognition). Structured data in, structured data out — no narrative.

Reference: decision-2026-0509-001 (approval + observation domains)

Usage:
    from agent_os.observations import (
        OBSERVATION_DOMAINS,
        get_observation_domain,
        store_observation,
        load_latest_observation,
        load_observations,
        prune_observations,
        format_observation_for_briefing,
    )

    # Store after an observe-cycle
    store_observation(agent_id, artifact_dict, config=cfg)

    # Load for briefing injection
    latest = load_latest_observation(agent_id, config=cfg)

    # Prune old artifacts (called by maintenance)
    pruned = prune_observations(agent_id, config=cfg)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .config import Config, get_config


# Per-agent observation domains (from decision-2026-0509-001).
# Keys are agent IDs; values describe what each agent should observe.
OBSERVATION_DOMAINS: dict[str, dict[str, str]] = {
    "agent-000-steward": {
        "name": "Runtime + Governance",
        "description": (
            "Observe the platform runtime and governance state. Check:\n"
            "- Task queue health: queued, in-progress, failed, stale tasks\n"
            "- Agent activity: recent log entries, last dispatch times\n"
            "- Budget state: daily/weekly spend, circuit breaker status\n"
            "- Governance: open proposals, pending decisions, unresolved threads\n"
            "- Notifications: unacknowledged warnings or critical events"
        ),
    },
    "agent-001-maker": {
        "name": "Repo + Worktrees",
        "description": (
            "Observe the codebase and development state. Check:\n"
            "- Worktree status: active worktrees, stale branches\n"
            "- Recent commits: what shipped, what's pending\n"
            "- Quality: any failing validation gates, lint issues\n"
            "- Product health: do build artifacts exist, are they current\n"
            "- Own task history: recent completions and failures"
        ),
    },
    "agent-003-operator": {
        "name": "Production Systems",
        "description": (
            "Observe production infrastructure and service health. Check:\n"
            "- Service status: HTTP health of all deployed products\n"
            "- Server resources: disk, memory, load if observable\n"
            "- SSL/TLS: certificate expiry dates\n"
            "- Deployment state: running versions, last deploy times\n"
            "- Logs: recent errors or warnings in service logs"
        ),
    },
    "agent-005-grower": {
        "name": "External Surfaces",
        "description": (
            "Observe public-facing surfaces and distribution channels. Check:\n"
            "- Website status: corvyd.ai and product sites responding\n"
            "- Content: latest blog post date, any draft content\n"
            "- SEO basics: are pages indexed, any obvious issues\n"
            "- README/docs: are they current and accurate\n"
            "- Social/distribution: any pending launch tasks"
        ),
    },
    "agent-006-strategist": {
        "name": "Cross-Cutting Meta-State",
        "description": (
            "Observe the company's strategic coherence. Check:\n"
            "- Current focus alignment: are agents working toward it\n"
            "- Drive tension: which drives have highest unresolved tension\n"
            "- Decision backlog: decisions made but not implemented\n"
            "- Agent coordination: are threads stale, are handoffs stuck\n"
            "- Working memory drift: do agent worldviews match reality"
        ),
    },
}

# Fallback domain for agents not in the explicit map.
_DEFAULT_DOMAIN: dict[str, str] = {
    "name": "General",
    "description": (
        "Observe your operational environment. Check:\n"
        "- Your task history: recent completions and failures\n"
        "- Your working memory accuracy: any stale claims\n"
        "- Your inbox and threads: anything pending\n"
        "- The company knowledge base: any relevant recent updates"
    ),
}


def get_observation_domain(agent_id: str) -> dict[str, str]:
    """Return the observation domain config for an agent."""
    return OBSERVATION_DOMAINS.get(agent_id, _DEFAULT_DOMAIN)


@dataclass
class ObservationArtifact:
    """A single observation artifact produced by an observe-cycle.

    Contains raw structured data (what was observed) plus metadata.
    No narrative — that happens when drive/task cycles consume the artifact.
    """

    agent_id: str
    domain: str  # domain name (e.g. "Runtime + Governance")
    observed_at: str  # ISO timestamp
    checks: list[dict] = field(default_factory=list)
    # Each check: {"name": str, "status": "ok"|"warning"|"error"|"unknown",
    #              "detail": str, "raw": any}
    summary_counts: dict[str, int] = field(default_factory=dict)
    # {"ok": N, "warning": N, "error": N, "unknown": N}

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ObservationArtifact:
        """Deserialize from a dict."""
        return cls(
            agent_id=data.get("agent_id", ""),
            domain=data.get("domain", ""),
            observed_at=data.get("observed_at", ""),
            checks=data.get("checks", []),
            summary_counts=data.get("summary_counts", {}),
        )


def _observations_dir(agent_id: str, *, config: Config | None = None) -> Path:
    """Return the observations directory for an agent, creating if needed."""
    cfg = config or get_config()
    obs_dir = cfg.agents_state_dir / agent_id / "observations"
    obs_dir.mkdir(parents=True, exist_ok=True)
    return obs_dir


def store_observation(
    agent_id: str,
    artifact: dict,
    *,
    config: Config | None = None,
) -> Path:
    """Store an observation artifact as a timestamped JSON file.

    Args:
        agent_id: The observing agent's ID.
        artifact: Dict with observation data (checks, summary_counts, etc.).
        config: Optional config override.

    Returns:
        Path to the written artifact file.
    """
    cfg = config or get_config()
    obs_dir = _observations_dir(agent_id, config=cfg)

    now = datetime.now(cfg.tz)
    filename = f"obs-{now.strftime('%Y-%m-%dT%H%M%S')}.json"
    path = obs_dir / filename

    # Ensure required fields
    artifact.setdefault("agent_id", agent_id)
    artifact.setdefault("observed_at", now.isoformat())

    path.write_text(json.dumps(artifact, indent=2, default=str) + "\n")
    return path


def load_latest_observation(
    agent_id: str,
    *,
    config: Config | None = None,
) -> dict | None:
    """Load the most recent observation artifact for an agent.

    Returns None if no observations exist.
    """
    cfg = config or get_config()
    obs_dir = cfg.agents_state_dir / agent_id / "observations"

    if not obs_dir.exists():
        return None

    files = sorted(obs_dir.glob("obs-*.json"), reverse=True)
    if not files:
        return None

    try:
        return json.loads(files[0].read_text())
    except (json.JSONDecodeError, OSError):
        return None


def load_observations(
    agent_id: str,
    *,
    max_count: int = 5,
    config: Config | None = None,
) -> list[dict]:
    """Load recent observation artifacts for an agent.

    Returns up to max_count most recent observations, newest first.
    """
    cfg = config or get_config()
    obs_dir = cfg.agents_state_dir / agent_id / "observations"

    if not obs_dir.exists():
        return []

    files = sorted(obs_dir.glob("obs-*.json"), reverse=True)[:max_count]
    results = []
    for f in files:
        try:
            results.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return results


def prune_observations(
    agent_id: str,
    *,
    retention_days: int = 7,
    config: Config | None = None,
) -> int:
    """Remove observation artifacts older than retention_days.

    Returns the number of files removed.
    """
    cfg = config or get_config()
    obs_dir = cfg.agents_state_dir / agent_id / "observations"

    if not obs_dir.exists():
        return 0

    cutoff = datetime.now(cfg.tz) - timedelta(days=retention_days)
    removed = 0

    for f in obs_dir.glob("obs-*.json"):
        try:
            # Parse timestamp from filename: obs-YYYY-MM-DDTHHMMSS.json
            ts_str = f.stem[4:]  # strip "obs-"
            file_dt = datetime.strptime(ts_str, "%Y-%m-%dT%H%M%S")
            file_dt = file_dt.replace(tzinfo=cfg.tz)
            if file_dt < cutoff:
                f.unlink()
                removed += 1
        except (ValueError, OSError):
            continue

    return removed


def format_observation_for_briefing(observation: dict) -> str:
    """Format an observation artifact as a compact briefing section.

    Designed for injection into system prompts — concise, scannable,
    machine-readable enough for agents to act on.
    """
    domain = observation.get("domain", "Unknown")
    observed_at = observation.get("observed_at", "unknown")
    checks = observation.get("checks", [])
    counts = observation.get("summary_counts", {})

    lines = [
        f"**Domain**: {domain}",
        f"**Observed at**: {observed_at}",
    ]

    if counts:
        count_parts = []
        for status in ("ok", "warning", "error", "unknown"):
            n = counts.get(status, 0)
            if n > 0:
                count_parts.append(f"{n} {status}")
        if count_parts:
            lines.append(f"**Summary**: {', '.join(count_parts)}")

    if checks:
        lines.append("")
        for check in checks[:8]:  # cap at 8 to avoid prompt bloat
            name = check.get("name", "?")
            status = check.get("status", "unknown")
            detail = check.get("detail", "")
            icon = {"ok": "+", "warning": "!", "error": "X", "unknown": "?"}.get(status, "?")
            line = f"[{icon}] {name}: {detail}" if detail else f"[{icon}] {name}"
            lines.append(line)
        if len(checks) > 8:
            lines.append(f"... and {len(checks) - 8} more checks")

    return "\n".join(lines)
