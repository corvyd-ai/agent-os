"""Tests for agent_os.audit.check_artifacts — artifact lifecycle audit check."""

from pathlib import Path

from agent_os.artifacts import create_artifact, record_transition
from agent_os.audit import check_artifacts
from agent_os.config import Config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(tmp_path: Path, *, project: bool = True) -> Config:
    """Create a Config; optionally enable project/SDLC."""
    root = tmp_path / "company"
    for d in [
        "agents/tasks/done",
        "agents/tasks/in-review",
        "state/artifacts",
    ]:
        (root / d).mkdir(parents=True, exist_ok=True)
    kwargs: dict = {"company_root": root}
    if project:
        kwargs["project_validate_commands"] = ["pytest -q"]
    return Config(**kwargs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCheckArtifacts:
    def test_no_sdlc_configured(self, tmp_path):
        cfg = _cfg(tmp_path, project=False)
        result = check_artifacts(cfg)
        assert result.status == "pass"
        assert "not configured" in result.summary.lower() or "n/a" in result.summary.lower()

    def test_no_artifacts_directory(self, tmp_path):
        cfg = _cfg(tmp_path)
        # Remove the artifacts directory
        import shutil

        art_dir = cfg.company_root / "state" / "artifacts"
        if art_dir.exists():
            shutil.rmtree(art_dir)
        result = check_artifacts(cfg)
        assert result.status == "pass"

    def test_empty_artifacts(self, tmp_path):
        cfg = _cfg(tmp_path)
        result = check_artifacts(cfg)
        assert result.status == "pass"
        assert "No artifacts" in result.summary

    def test_all_consistent(self, tmp_path):
        cfg = _cfg(tmp_path)
        create_artifact("task-001", "agent-001", branch="b1", config=cfg)
        record_transition("task-001", "merged", config=cfg)

        result = check_artifacts(cfg)
        assert result.status == "pass"
        assert "1 artifacts tracked" in result.summary

    def test_flags_stale(self, tmp_path):
        """Artifacts older than threshold and not in terminal state get flagged."""
        cfg = _cfg(tmp_path)
        art = create_artifact("task-001", "agent-001", branch="b1", config=cfg)
        # Backdate the created_at to make it stale
        art.created_at = "2026-01-01T00:00:00"
        from agent_os.artifacts import save_artifact

        save_artifact(art, config=cfg)

        result = check_artifacts(cfg, stale_threshold_hours=1.0)
        assert result.status == "warn"
        assert "stale" in result.summary

    def test_terminal_not_flagged_stale(self, tmp_path):
        cfg = _cfg(tmp_path)
        art = create_artifact("task-001", "agent-001", branch="b1", config=cfg)
        record_transition("task-001", "merged", config=cfg)
        # Even if old, merged artifacts are terminal
        art = create_artifact("task-002", "agent-001", branch="b2", config=cfg)
        art.created_at = "2026-01-01T00:00:00"
        from agent_os.artifacts import save_artifact

        save_artifact(art, config=cfg)

        result = check_artifacts(cfg, stale_threshold_hours=1.0)
        # task-002 is stale (pushed, old), task-001 is not (merged = terminal)
        stale_findings = [f for f in result.findings if f.level == "warn"]
        assert len(stale_findings) == 1
        assert "task-002" in stale_findings[0].message
