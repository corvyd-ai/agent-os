"""Tests for agent_os.observations — observation store and briefing integration."""

import json
from datetime import datetime, timedelta

import pytest

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


class TestObservationDomains:
    """Per-agent domain configuration from decision-2026-0509-001."""

    def test_known_agents_have_domains(self):
        expected = {
            "agent-000-steward",
            "agent-001-maker",
            "agent-003-operator",
            "agent-005-grower",
            "agent-006-strategist",
        }
        assert set(OBSERVATION_DOMAINS.keys()) == expected

    def test_each_domain_has_name_and_description(self):
        for agent_id, domain in OBSERVATION_DOMAINS.items():
            assert "name" in domain, f"{agent_id} missing name"
            assert "description" in domain, f"{agent_id} missing description"
            assert len(domain["name"]) > 0
            assert len(domain["description"]) > 10

    def test_get_known_agent(self):
        domain = get_observation_domain("agent-001-maker")
        assert domain["name"] == "Repo + Worktrees"

    def test_get_unknown_agent_returns_default(self):
        domain = get_observation_domain("agent-999-unknown")
        assert domain == _DEFAULT_DOMAIN
        assert domain["name"] == "General"


class TestObservationArtifact:
    """Dataclass serialization round-trip."""

    def test_to_dict_round_trip(self):
        artifact = ObservationArtifact(
            agent_id="agent-001-maker",
            domain="Repo + Worktrees",
            observed_at="2026-05-10T12:00:00-07:00",
            checks=[
                {"name": "worktree_count", "status": "ok", "detail": "3 active worktrees"},
            ],
            summary_counts={"ok": 1, "warning": 0, "error": 0, "unknown": 0},
        )
        d = artifact.to_dict()
        restored = ObservationArtifact.from_dict(d)
        assert restored.agent_id == artifact.agent_id
        assert restored.domain == artifact.domain
        assert restored.checks == artifact.checks
        assert restored.summary_counts == artifact.summary_counts

    def test_from_dict_missing_fields(self):
        artifact = ObservationArtifact.from_dict({})
        assert artifact.agent_id == ""
        assert artifact.checks == []
        assert artifact.summary_counts == {}


class TestStoreObservation:
    """Writing observation artifacts to the filesystem."""

    def test_store_creates_file(self, aios_config):
        artifact = {
            "domain": "Test",
            "checks": [{"name": "test", "status": "ok", "detail": "all good"}],
            "summary_counts": {"ok": 1},
        }
        path = store_observation("agent-001-maker", artifact, config=aios_config)
        assert path.exists()
        assert path.suffix == ".json"
        assert path.name.startswith("obs-")

        data = json.loads(path.read_text())
        assert data["agent_id"] == "agent-001-maker"
        assert data["domain"] == "Test"
        assert "observed_at" in data

    def test_store_preserves_existing_agent_id(self, aios_config):
        artifact = {"agent_id": "custom-id", "domain": "Test"}
        path = store_observation("agent-001-maker", artifact, config=aios_config)
        data = json.loads(path.read_text())
        # setdefault only sets if missing — existing value preserved
        assert data["agent_id"] == "custom-id"

    def test_store_creates_observations_dir(self, aios_config):
        obs_dir = aios_config.agents_state_dir / "agent-001-maker" / "observations"
        assert not obs_dir.exists()
        store_observation("agent-001-maker", {"domain": "Test"}, config=aios_config)
        assert obs_dir.exists()


class TestLoadObservations:
    """Reading observation artifacts back."""

    def test_load_latest_no_observations(self, aios_config):
        result = load_latest_observation("agent-001-maker", config=aios_config)
        assert result is None

    def test_load_latest_returns_newest(self, aios_config):
        obs_dir = aios_config.agents_state_dir / "agent-001-maker" / "observations"
        obs_dir.mkdir(parents=True)

        # Write two observations with ordered filenames
        (obs_dir / "obs-2026-05-10T120000.json").write_text(json.dumps({"seq": 1}))
        (obs_dir / "obs-2026-05-10T130000.json").write_text(json.dumps({"seq": 2}))

        result = load_latest_observation("agent-001-maker", config=aios_config)
        assert result is not None
        assert result["seq"] == 2

    def test_load_latest_handles_corrupt_file(self, aios_config):
        obs_dir = aios_config.agents_state_dir / "agent-001-maker" / "observations"
        obs_dir.mkdir(parents=True)
        (obs_dir / "obs-2026-05-10T120000.json").write_text("not json")

        result = load_latest_observation("agent-001-maker", config=aios_config)
        assert result is None

    def test_load_observations_respects_max_count(self, aios_config):
        obs_dir = aios_config.agents_state_dir / "agent-001-maker" / "observations"
        obs_dir.mkdir(parents=True)

        for i in range(5):
            (obs_dir / f"obs-2026-05-10T12000{i}.json").write_text(json.dumps({"seq": i}))

        results = load_observations("agent-001-maker", max_count=3, config=aios_config)
        assert len(results) == 3
        # Should be newest first (reverse sorted)
        assert results[0]["seq"] == 4
        assert results[1]["seq"] == 3
        assert results[2]["seq"] == 2

    def test_load_observations_empty_dir(self, aios_config):
        results = load_observations("agent-001-maker", config=aios_config)
        assert results == []


class TestPruneObservations:
    """Retention policy enforcement."""

    def test_prune_removes_old_files(self, aios_config):
        obs_dir = aios_config.agents_state_dir / "agent-001-maker" / "observations"
        obs_dir.mkdir(parents=True)

        # File from 10 days ago (should be pruned with 7-day retention)
        (obs_dir / "obs-2026-04-01T120000.json").write_text(json.dumps({"old": True}))
        # File from today (should be kept)
        now = datetime.now(aios_config.tz)
        today_name = f"obs-{now.strftime('%Y-%m-%dT%H%M%S')}.json"
        (obs_dir / today_name).write_text(json.dumps({"new": True}))

        removed = prune_observations("agent-001-maker", retention_days=7, config=aios_config)
        assert removed == 1
        assert not (obs_dir / "obs-2026-04-01T120000.json").exists()
        assert (obs_dir / today_name).exists()

    def test_prune_no_dir(self, aios_config):
        removed = prune_observations("agent-001-maker", config=aios_config)
        assert removed == 0

    def test_prune_handles_malformed_filenames(self, aios_config):
        obs_dir = aios_config.agents_state_dir / "agent-001-maker" / "observations"
        obs_dir.mkdir(parents=True)
        (obs_dir / "obs-not-a-date.json").write_text("{}")

        removed = prune_observations("agent-001-maker", config=aios_config)
        assert removed == 0  # Skipped, not crashed


class TestFormatObservationForBriefing:
    """Compact prompt-injection formatting."""

    def test_basic_format(self):
        observation = {
            "domain": "Repo + Worktrees",
            "observed_at": "2026-05-10T12:00:00-07:00",
            "checks": [
                {"name": "worktrees", "status": "ok", "detail": "3 active, 0 stale"},
                {"name": "lint", "status": "warning", "detail": "2 unused imports"},
            ],
            "summary_counts": {"ok": 1, "warning": 1},
        }
        result = format_observation_for_briefing(observation)
        assert "Repo + Worktrees" in result
        assert "2026-05-10" in result
        assert "[+] worktrees: 3 active, 0 stale" in result
        assert "[!] lint: 2 unused imports" in result
        assert "1 ok, 1 warning" in result

    def test_empty_observation(self):
        result = format_observation_for_briefing({})
        assert "Unknown" in result

    def test_caps_checks_at_eight(self):
        checks = [{"name": f"check-{i}", "status": "ok", "detail": f"ok {i}"} for i in range(12)]
        observation = {"checks": checks, "summary_counts": {}}
        result = format_observation_for_briefing(observation)
        assert "check-7" in result  # 8th check (0-indexed) should be present
        assert "check-8" not in result  # 9th check should NOT be present
        assert "4 more checks" in result

    def test_status_icons(self):
        checks = [
            {"name": "ok-check", "status": "ok"},
            {"name": "warn-check", "status": "warning"},
            {"name": "err-check", "status": "error"},
            {"name": "unk-check", "status": "unknown"},
        ]
        result = format_observation_for_briefing({"checks": checks})
        assert "[+] ok-check" in result
        assert "[!] warn-check" in result
        assert "[X] err-check" in result
        assert "[?] unk-check" in result


class TestConfigObserve:
    """Config fields for observe-cycles."""

    def test_default_observe_config(self):
        cfg = Config()
        assert cfg.observe_model == "claude-sonnet-4-6"
        assert cfg.observe_max_budget_usd == 0.50
        assert cfg.observe_max_turns == 15
        assert cfg.observe_retention_days == 7
        assert cfg.schedule_observes_enabled is True
        assert cfg.schedule_observes_interval_minutes == 360
        assert cfg.schedule_observes_stagger_minutes == 5

    def test_toml_observe_budget(self, tmp_path):
        toml_path = tmp_path / "agent-os.toml"
        toml_path.write_text(
            '[company]\nroot = "."\n\n'
            "[budget]\nobserve = 0.75\n\n"
            "[schedule.observes]\nenabled = false\ninterval_minutes = 720\n"
        )
        cfg = Config.from_toml(toml_path)
        assert cfg.observe_max_budget_usd == 0.75
        assert cfg.schedule_observes_enabled is False
        assert cfg.schedule_observes_interval_minutes == 720
