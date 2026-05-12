"""Tests for the observations module — observe-cycle data model and storage.

Tests cover: artifact storage/loading, pruning, briefing formatting,
observation domains, config defaults, and composer integration.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_os.composer import PromptComposer
from agent_os.config import Config
from agent_os.observations import (
    OBSERVATION_DOMAINS,
    ObservationArtifact,
    _DEFAULT_DOMAIN,
    format_observation_for_briefing,
    get_observation_domain,
    load_latest_observation,
    load_observations,
    prune_observations,
    store_observation,
)
from agent_os.registry import AgentConfig


@pytest.fixture
def obs_config(tmp_path):
    """Create a config with temp directory for observation tests."""
    root = tmp_path / "company"
    (root / "agents" / "state" / "agent-001-maker" / "observations").mkdir(parents=True)
    (root / "agents" / "state" / "agent-000-steward" / "observations").mkdir(parents=True)
    (root / "agents" / "registry").mkdir(parents=True)
    (root / "agents" / "tasks" / "queued").mkdir(parents=True)
    (root / "agents" / "tasks" / "in-progress").mkdir(parents=True)
    (root / "agents" / "tasks" / "done").mkdir(parents=True)
    (root / "agents" / "tasks" / "failed").mkdir(parents=True)
    (root / "agents" / "tasks" / "declined").mkdir(parents=True)
    (root / "agents" / "tasks" / "backlog").mkdir(parents=True)
    (root / "agents" / "tasks" / "in-review").mkdir(parents=True)
    (root / "agents" / "messages" / "broadcast").mkdir(parents=True)
    (root / "agents" / "messages" / "threads").mkdir(parents=True)
    (root / "agents" / "logs").mkdir(parents=True)
    (root / "finance" / "costs").mkdir(parents=True)
    (root / "strategy" / "proposals" / "active").mkdir(parents=True)
    (root / "strategy" / "proposals" / "decided").mkdir(parents=True)
    (root / "identity").mkdir(parents=True)
    (root / "identity" / "values.md").write_text("# Values\nTest values")
    (root / "strategy" / "drives.md").write_text("# Drives\nTest drives")
    return Config(company_root=root)


def _make_agent_config(**overrides):
    """Build a minimal AgentConfig for testing."""
    defaults = {
        "agent_id": "agent-001-maker",
        "name": "The Maker",
        "role": "Software Engineer",
        "model": "claude-opus-4-6",
        "allowed_tools": ["Read", "Write", "Edit", "Bash"],
        "registry_path": Path("/tmp/fake-registry.md"),
        "system_body": "You are The Maker. You build things.",
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


# ── Observation Domains ──────────────────────────────────────────────


def test_observation_domains_defined():
    """All five agents have explicit observation domains."""
    expected = {
        "agent-000-steward",
        "agent-001-maker",
        "agent-003-operator",
        "agent-005-grower",
        "agent-006-strategist",
    }
    assert set(OBSERVATION_DOMAINS.keys()) == expected


def test_observation_domain_structure():
    """Each domain has name and description."""
    for agent_id, domain in OBSERVATION_DOMAINS.items():
        assert "name" in domain, f"{agent_id} missing 'name'"
        assert "description" in domain, f"{agent_id} missing 'description'"
        assert len(domain["description"]) > 50, f"{agent_id} description too short"


def test_get_observation_domain_known():
    domain = get_observation_domain("agent-001-maker")
    assert domain["name"] == "Repo + Worktrees"


def test_get_observation_domain_unknown():
    domain = get_observation_domain("agent-999-unknown")
    assert domain == _DEFAULT_DOMAIN
    assert domain["name"] == "General"


# ── ObservationArtifact dataclass ────────────────────────────────────


def test_artifact_to_dict():
    a = ObservationArtifact(
        agent_id="agent-001-maker",
        domain="Repo + Worktrees",
        observed_at="2026-05-11T10:00:00",
        checks=[{"name": "git status", "status": "ok", "detail": "clean"}],
        summary_counts={"ok": 1},
    )
    d = a.to_dict()
    assert d["agent_id"] == "agent-001-maker"
    assert d["domain"] == "Repo + Worktrees"
    assert len(d["checks"]) == 1
    assert d["summary_counts"]["ok"] == 1


def test_artifact_from_dict():
    data = {
        "agent_id": "agent-001-maker",
        "domain": "Repo + Worktrees",
        "observed_at": "2026-05-11T10:00:00",
        "checks": [{"name": "test", "status": "warning", "detail": "flaky"}],
        "summary_counts": {"warning": 1},
    }
    a = ObservationArtifact.from_dict(data)
    assert a.agent_id == "agent-001-maker"
    assert a.checks[0]["status"] == "warning"


def test_artifact_roundtrip():
    a = ObservationArtifact(
        agent_id="agent-003-operator",
        domain="Production Systems",
        observed_at="2026-05-11T12:00:00",
        checks=[
            {"name": "http check", "status": "ok", "detail": "200 OK"},
            {"name": "disk", "status": "warning", "detail": "85% full"},
        ],
        summary_counts={"ok": 1, "warning": 1},
    )
    d = a.to_dict()
    b = ObservationArtifact.from_dict(d)
    assert a.agent_id == b.agent_id
    assert a.checks == b.checks
    assert a.summary_counts == b.summary_counts


# ── Store / Load ─────────────────────────────────────────────────────


def test_store_observation(obs_config):
    artifact = {
        "domain": "Repo + Worktrees",
        "checks": [{"name": "git status", "status": "ok", "detail": "clean"}],
        "summary_counts": {"ok": 1},
    }
    path = store_observation("agent-001-maker", artifact, config=obs_config)
    assert path.exists()
    assert path.suffix == ".json"
    assert path.name.startswith("obs-")

    data = json.loads(path.read_text())
    assert data["agent_id"] == "agent-001-maker"
    assert data["domain"] == "Repo + Worktrees"
    assert "observed_at" in data


def test_load_latest_observation(obs_config):
    # Store two observations
    store_observation(
        "agent-001-maker",
        {"domain": "first", "checks": [], "summary_counts": {}},
        config=obs_config,
    )
    # Ensure different timestamps in filenames
    import time

    time.sleep(0.01)
    store_observation(
        "agent-001-maker",
        {"domain": "second", "checks": [], "summary_counts": {}},
        config=obs_config,
    )

    latest = load_latest_observation("agent-001-maker", config=obs_config)
    assert latest is not None
    assert latest["domain"] == "second"


def test_load_latest_observation_no_observations(obs_config):
    result = load_latest_observation("agent-001-maker", config=obs_config)
    assert result is None


def test_load_latest_observation_no_dir(obs_config):
    result = load_latest_observation("agent-999-nonexistent", config=obs_config)
    assert result is None


def test_load_observations_multiple(obs_config):
    # Write distinct files directly to avoid timestamp collisions
    obs_dir = obs_config.agents_state_dir / "agent-001-maker" / "observations"
    for i in range(3):
        fname = f"obs-2026-05-1{i}T100000.json"
        (obs_dir / fname).write_text(
            json.dumps({"agent_id": "agent-001-maker", "domain": f"obs-{i}", "checks": [], "summary_counts": {}})
        )

    results = load_observations("agent-001-maker", max_count=2, config=obs_config)
    assert len(results) == 2


def test_load_observations_empty(obs_config):
    results = load_observations("agent-001-maker", config=obs_config)
    assert results == []


# ── Pruning ──────────────────────────────────────────────────────────


def test_prune_observations_removes_old(obs_config):
    obs_dir = obs_config.agents_state_dir / "agent-001-maker" / "observations"

    # Create an old observation file (8 days ago)
    old_time = datetime.now(timezone.utc) - timedelta(days=8)
    old_name = f"obs-{old_time.strftime('%Y-%m-%dT%H%M%S')}.json"
    (obs_dir / old_name).write_text(json.dumps({"domain": "old", "checks": []}))

    # Create a recent observation file
    recent_time = datetime.now(timezone.utc)
    recent_name = f"obs-{recent_time.strftime('%Y-%m-%dT%H%M%S')}.json"
    (obs_dir / recent_name).write_text(json.dumps({"domain": "recent", "checks": []}))

    removed = prune_observations("agent-001-maker", retention_days=7, config=obs_config)
    assert removed == 1
    assert not (obs_dir / old_name).exists()
    assert (obs_dir / recent_name).exists()


def test_prune_observations_keeps_recent(obs_config):
    store_observation(
        "agent-001-maker",
        {"domain": "recent", "checks": [], "summary_counts": {}},
        config=obs_config,
    )
    removed = prune_observations("agent-001-maker", retention_days=7, config=obs_config)
    assert removed == 0


def test_prune_observations_no_dir(obs_config):
    removed = prune_observations("agent-999-nonexistent", retention_days=7, config=obs_config)
    assert removed == 0


# ── Briefing Formatting ──────────────────────────────────────────────


def test_format_observation_for_briefing():
    obs = {
        "domain": "Production Systems",
        "observed_at": "2026-05-11T10:00:00",
        "checks": [
            {"name": "HTTP health", "status": "ok", "detail": "All 10 products returning 200"},
            {"name": "Disk usage", "status": "warning", "detail": "85% on /srv"},
            {"name": "SSL certs", "status": "error", "detail": "corvyd.ai expires in 3 days"},
        ],
        "summary_counts": {"ok": 1, "warning": 1, "error": 1},
    }

    text = format_observation_for_briefing(obs)
    assert "Production Systems" in text
    assert "2026-05-11T10:00:00" in text
    assert "1 ok, 1 warning, 1 error" in text
    assert "[+] HTTP health" in text
    assert "[!] Disk usage" in text
    assert "[X] SSL certs" in text


def test_format_observation_empty_checks():
    obs = {
        "domain": "General",
        "observed_at": "2026-05-11T10:00:00",
        "checks": [],
        "summary_counts": {},
    }
    text = format_observation_for_briefing(obs)
    assert "General" in text
    assert "2026-05-11T10:00:00" in text


# ── Config Defaults ──────────────────────────────────────────────────


def test_config_observe_defaults():
    cfg = Config()
    assert cfg.observe_model == "claude-sonnet-4-6"
    assert cfg.observe_max_budget_usd == 0.75
    assert cfg.observe_max_turns == 15
    assert cfg.observe_retention_days == 7
    assert cfg.schedule_observe_enabled is True
    assert cfg.schedule_observe_interval_minutes == 360


def test_config_from_toml_observe(tmp_path):
    toml_path = tmp_path / "agent-os.toml"
    toml_path.write_text(
        '[company]\nname = "Test"\nroot = "."\n'
        "\n[budget]\nobserve = 1.25\n"
        "\n[schedule.observe]\nenabled = false\ninterval_minutes = 120\n"
    )
    cfg = Config.from_toml(toml_path)
    assert cfg.observe_max_budget_usd == 1.25
    assert cfg.schedule_observe_enabled is False
    assert cfg.schedule_observe_interval_minutes == 120


# ── Composer Integration ─────────────────────────────────────────────


def test_composer_includes_observation_section(obs_config):
    # Store an observation
    store_observation(
        "agent-001-maker",
        {
            "domain": "Repo + Worktrees",
            "checks": [{"name": "git status", "status": "ok", "detail": "clean"}],
            "summary_counts": {"ok": 1},
        },
        config=obs_config,
    )

    agent_config = _make_agent_config()
    composer = PromptComposer(config=obs_config)
    sections = list(composer.get_sections(agent_config))
    section_names = [name for name, _ in sections]

    assert "latest_observation" in section_names
    obs_content = dict(sections)["latest_observation"]
    assert "Latest Observation" in obs_content
    assert "Repo + Worktrees" in obs_content
    assert "verified state" in obs_content


def test_composer_no_observation_when_empty(obs_config):
    agent_config = _make_agent_config()
    composer = PromptComposer(config=obs_config)
    sections = list(composer.get_sections(agent_config))
    section_names = [name for name, _ in sections]

    assert "latest_observation" not in section_names


def test_composer_observation_before_failures(obs_config):
    """Observation section should come before recent failures."""
    store_observation(
        "agent-001-maker",
        {"domain": "test", "checks": [], "summary_counts": {}},
        config=obs_config,
    )

    # Create a failed task so failures section appears
    failed_dir = obs_config.tasks_failed
    failed_dir.mkdir(parents=True, exist_ok=True)
    (failed_dir / "task-2026-0511-001.md").write_text(
        "---\nid: task-2026-0511-001\ntitle: Test task\n"
        "assigned_to: agent-001-maker\ncreated_at: 2026-05-11\n---\n\n"
        "**Reason**: test failure\n**Date**: 2026-05-11\n"
    )

    agent_config = _make_agent_config()
    composer = PromptComposer(config=obs_config)
    sections = list(composer.get_sections(agent_config))
    section_names = [name for name, _ in sections]

    if "latest_observation" in section_names and "recent_failures" in section_names:
        obs_idx = section_names.index("latest_observation")
        fail_idx = section_names.index("recent_failures")
        assert obs_idx < fail_idx, "Observation should come before failures"
