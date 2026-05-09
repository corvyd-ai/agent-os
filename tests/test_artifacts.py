"""Tests for agent_os.artifacts — layer-2 artifact lifecycle store."""

import json
from pathlib import Path

import yaml

from agent_os.artifacts import (
    Artifact,
    StateEntry,
    correlate_deploy,
    create_artifact,
    format_artifacts_digest,
    get_pending_artifacts,
    list_artifacts,
    load_artifact,
    mark_deployed,
    record_transition,
    writeback_merge_to_task,
)
from agent_os.config import Config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cfg(tmp_path: Path) -> Config:
    """Create a Config with artifacts dir under tmp_path."""
    root = tmp_path / "company"
    for d in [
        "agents/tasks/done",
        "agents/tasks/in-review",
        "state/artifacts",
    ]:
        (root / d).mkdir(parents=True, exist_ok=True)
    return Config(company_root=root)


def _write_task(directory: Path, task_id: str, extra_meta: dict | None = None) -> Path:
    """Write a minimal task file."""
    directory.mkdir(parents=True, exist_ok=True)
    meta = {"id": task_id, "title": "Test task", "assigned_to": "agent-001-maker", "status": "done"}
    if extra_meta:
        meta.update(extra_meta)
    path = directory / f"{task_id}.md"
    path.write_text("---\n" + yaml.dump(meta, default_flow_style=False, sort_keys=False) + "---\n\nBody.\n")
    return path


# ---------------------------------------------------------------------------
# Store operations
# ---------------------------------------------------------------------------


class TestCreateAndLoad:
    def test_create_artifact(self, tmp_path):
        cfg = _cfg(tmp_path)
        art = create_artifact(
            "task-2026-0504-001",
            "agent-001-maker",
            artifact_type="github_pr",
            provider="github",
            ref="https://github.com/corvyd-ai/agent-os/pull/55",
            branch="agent/task-2026-0504-001",
            sha="abc123",
            config=cfg,
        )
        assert art.task_id == "task-2026-0504-001"
        assert art.current_state == "pushed"
        assert len(art.history) == 1
        assert art.metadata["commit_sha"] == "abc123"

        # Verify file on disk
        path = cfg.company_root / "state" / "artifacts" / "task-2026-0504-001.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["task_id"] == "task-2026-0504-001"

    def test_load_artifact_roundtrip(self, tmp_path):
        cfg = _cfg(tmp_path)
        original = create_artifact(
            "task-001",
            "agent-001",
            ref="https://example.com/pr/1",
            branch="agent/task-001",
            config=cfg,
        )
        loaded = load_artifact("task-001", config=cfg)
        assert loaded is not None
        assert loaded.task_id == original.task_id
        assert loaded.ref == original.ref
        assert loaded.current_state == "pushed"
        assert len(loaded.history) == 1

    def test_load_nonexistent_returns_none(self, tmp_path):
        cfg = _cfg(tmp_path)
        assert load_artifact("no-such-task", config=cfg) is None


class TestListArtifacts:
    def test_list_all(self, tmp_path):
        cfg = _cfg(tmp_path)
        create_artifact("task-001", "agent-001", branch="b1", config=cfg)
        create_artifact("task-002", "agent-001", branch="b2", config=cfg)
        all_arts = list_artifacts(config=cfg)
        assert len(all_arts) == 2

    def test_list_filter_by_state(self, tmp_path):
        cfg = _cfg(tmp_path)
        create_artifact("task-001", "agent-001", branch="b1", config=cfg)
        create_artifact("task-002", "agent-001", branch="b2", config=cfg)
        record_transition("task-002", "merged", config=cfg)

        pushed = list_artifacts(state="pushed", config=cfg)
        assert len(pushed) == 1
        assert pushed[0].task_id == "task-001"

        merged = list_artifacts(state="merged", config=cfg)
        assert len(merged) == 1
        assert merged[0].task_id == "task-002"


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


class TestRecordTransition:
    def test_transition_appends_history(self, tmp_path):
        cfg = _cfg(tmp_path)
        create_artifact("task-001", "agent-001", branch="b", config=cfg)

        art = record_transition("task-001", "ci_running", config=cfg)
        assert art is not None
        assert art.current_state == "ci_running"
        assert len(art.history) == 2

        art = record_transition("task-001", "ci_passed", {"ci_status": "passed"}, config=cfg)
        assert art is not None
        assert art.current_state == "ci_passed"
        assert len(art.history) == 3
        assert art.metadata["ci_status"] == "passed"

    def test_idempotent_no_duplicate(self, tmp_path):
        """Polling twice with no state change should NOT add a history entry."""
        cfg = _cfg(tmp_path)
        create_artifact("task-001", "agent-001", branch="b", config=cfg)
        record_transition("task-001", "open", config=cfg)

        art_before = load_artifact("task-001", config=cfg)
        assert art_before is not None
        history_len = len(art_before.history)

        # Same state again — should be a no-op
        art_after = record_transition("task-001", "open", config=cfg)
        assert art_after is not None
        assert len(art_after.history) == history_len

    def test_transition_nonexistent_returns_none(self, tmp_path):
        cfg = _cfg(tmp_path)
        result = record_transition("no-such-task", "merged", config=cfg)
        assert result is None

    def test_full_lifecycle(self, tmp_path):
        """PR transitions through pushed → ci_running → ci_passed → open → merged."""
        cfg = _cfg(tmp_path)
        # Set up a task file for the writeback
        _write_task(cfg.tasks_done, "task-001")

        create_artifact(
            "task-001",
            "agent-001",
            ref="https://github.com/org/repo/pull/42",
            branch="agent/task-001",
            sha="abc123",
            config=cfg,
        )

        for state in ["ci_running", "ci_passed", "open", "merged"]:
            detail = {"merge_sha": "def456"} if state == "merged" else {}
            record_transition("task-001", state, detail, config=cfg)

        art = load_artifact("task-001", config=cfg)
        assert art is not None
        assert art.current_state == "merged"
        assert len(art.history) == 5  # pushed + 4 transitions
        states = [e.state for e in art.history]
        assert states == ["pushed", "ci_running", "ci_passed", "open", "merged"]


# ---------------------------------------------------------------------------
# Frontmatter writeback
# ---------------------------------------------------------------------------


class TestFrontmatterWriteback:
    def test_writeback_on_merge(self, tmp_path):
        """When a PR merges, the task frontmatter should get merged: true and merge_sha."""
        cfg = _cfg(tmp_path)
        task_file = _write_task(cfg.tasks_done, "task-001")

        create_artifact(
            "task-001",
            "agent-001",
            ref="https://github.com/org/repo/pull/42",
            branch="agent/task-001",
            config=cfg,
        )
        # Simulate merge
        record_transition("task-001", "merged", {"merge_sha": "deadbeef"}, config=cfg)

        # Verify frontmatter was updated
        text = task_file.read_text()
        parts = text.split("---", 2)
        meta = yaml.safe_load(parts[1])
        assert meta["merged"] is True
        assert meta["merge_sha"] == "deadbeef"
        assert meta["pr_url"] == "https://github.com/org/repo/pull/42"

    def test_writeback_manual(self, tmp_path):
        cfg = _cfg(tmp_path)
        task_file = _write_task(cfg.tasks_done, "task-002")

        art = Artifact(
            task_id="task-002",
            agent_id="agent-001",
            artifact_type="github_pr",
            provider="github",
            ref="https://github.com/org/repo/pull/99",
            branch="agent/task-002",
            current_state="merged",
            created_at="2026-05-04T12:00:00",
            updated_at="2026-05-04T14:00:00",
            metadata={"merge_sha": "aabb1122"},
        )
        result = writeback_merge_to_task("task-002", art, config=cfg)
        assert result is True

        text = task_file.read_text()
        parts = text.split("---", 2)
        meta = yaml.safe_load(parts[1])
        assert meta["merged"] is True
        assert meta["merge_sha"] == "aabb1122"

    def test_writeback_task_not_found(self, tmp_path):
        cfg = _cfg(tmp_path)
        art = Artifact(
            task_id="no-such-task",
            agent_id="a",
            artifact_type="t",
            provider="p",
            ref="r",
            branch="b",
            current_state="merged",
            created_at="",
            updated_at="",
        )
        result = writeback_merge_to_task("no-such-task", art, config=cfg)
        assert result is False


# ---------------------------------------------------------------------------
# Deploy verification
# ---------------------------------------------------------------------------


class TestDeployVerification:
    def test_mark_deployed(self, tmp_path):
        cfg = _cfg(tmp_path)
        create_artifact("task-001", "agent-001", branch="b", config=cfg)
        record_transition("task-001", "merged", {"merge_sha": "abc"}, config=cfg)

        art = mark_deployed("task-001", "v0.5.4", config=cfg)
        assert art is not None
        assert art.current_state == "deployed"
        assert art.metadata["deployed_in"] == "v0.5.4"
        assert any(e.state == "deployed" for e in art.history)

    def test_mark_deployed_not_merged_is_noop(self, tmp_path):
        cfg = _cfg(tmp_path)
        create_artifact("task-001", "agent-001", branch="b", config=cfg)
        # Still in "pushed" state — can't deploy
        art = mark_deployed("task-001", "v1.0", config=cfg)
        assert art is not None
        assert art.current_state == "pushed"  # unchanged

    def test_correlate_deploy(self, tmp_path):
        cfg = _cfg(tmp_path)
        create_artifact(
            "task-001",
            "agent-001",
            ref="https://github.com/org/repo/pull/42",
            branch="agent/task-001",
            config=cfg,
        )
        record_transition("task-001", "merged", config=cfg)
        create_artifact("task-002", "agent-001", branch="agent/task-002", config=cfg)
        record_transition("task-002", "merged", config=cfg)

        # Only task-001's PR URL is in the deploy
        updated = correlate_deploy(
            "v0.5.4",
            ["https://github.com/org/repo/pull/42"],
            config=cfg,
        )
        assert len(updated) == 1
        assert updated[0].task_id == "task-001"
        assert updated[0].metadata["deployed_in"] == "v0.5.4"


# ---------------------------------------------------------------------------
# Composer integration
# ---------------------------------------------------------------------------


class TestPendingArtifacts:
    def test_pending_excludes_terminal(self, tmp_path):
        cfg = _cfg(tmp_path)
        create_artifact("task-001", "agent-001", branch="b1", config=cfg)
        create_artifact("task-002", "agent-001", branch="b2", config=cfg)
        record_transition("task-002", "merged", config=cfg)
        record_transition("task-002", "deployed", {"version": "v1"}, config=cfg)

        # task-002 is deployed (terminal) — should not appear
        pending = get_pending_artifacts(config=cfg)
        # task-001 (pushed) should appear, task-002 (deployed) should not
        task_ids = {a.task_id for a in pending}
        assert "task-001" in task_ids
        assert "task-002" not in task_ids

    def test_ci_failure_surfaced_first_in_digest(self, tmp_path):
        """CI failures should appear above other artifacts in the digest."""
        cfg = _cfg(tmp_path)
        create_artifact("task-001", "agent-001", branch="b1", config=cfg)
        create_artifact("task-002", "agent-001", branch="b2", config=cfg)
        record_transition("task-002", "ci_failed", {"ci_status": "failed"}, config=cfg)

        pending = get_pending_artifacts(config=cfg)
        digest = format_artifacts_digest(pending)

        # CI failure section should come before the summary section
        assert "CI Failures" in digest
        ci_pos = digest.index("CI Failures")
        summary_pos = digest.index("Summary")
        assert ci_pos < summary_pos

    def test_empty_artifacts_empty_digest(self):
        digest = format_artifacts_digest([])
        assert digest == ""


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_to_dict_from_dict_roundtrip(self):
        art = Artifact(
            task_id="t",
            agent_id="a",
            artifact_type="github_pr",
            provider="github",
            ref="https://example.com/pr/1",
            branch="agent/t",
            current_state="open",
            created_at="2026-05-04T12:00:00",
            updated_at="2026-05-04T12:00:00",
            history=[StateEntry(state="pushed", at="2026-05-04T12:00:00", detail={"sha": "abc"})],
            metadata={"commit_sha": "abc"},
        )
        d = art.to_dict()
        restored = Artifact.from_dict(d)
        assert restored.task_id == art.task_id
        assert restored.current_state == art.current_state
        assert len(restored.history) == 1
        assert restored.history[0].detail == {"sha": "abc"}
        assert restored.metadata == {"commit_sha": "abc"}
