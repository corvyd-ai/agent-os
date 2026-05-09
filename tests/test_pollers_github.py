"""Tests for agent_os.pollers.github_pr — layer-3 GitHub PR poller."""

from unittest.mock import patch

from agent_os.artifacts import Artifact, StateEntry
from agent_os.pollers.github_pr import (
    _determine_state,
    _extract_detail,
    _match_pr,
    gh_available,
    poll_prs,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_artifact(
    task_id: str = "task-001",
    branch: str = "agent/task-001",
    current_state: str = "pushed",
    ref: str = "",
) -> Artifact:
    return Artifact(
        task_id=task_id,
        agent_id="agent-001-maker",
        artifact_type="github_pr",
        provider="github",
        ref=ref,
        branch=branch,
        current_state=current_state,
        created_at="2026-05-04T12:00:00",
        updated_at="2026-05-04T12:00:00",
        history=[StateEntry(state=current_state, at="2026-05-04T12:00:00")],
    )


def _make_gh_pr(
    branch: str = "agent/task-001",
    state: str = "OPEN",
    url: str = "https://github.com/org/repo/pull/42",
    number: int = 42,
    merge_commit: dict | None = None,
    checks: list | None = None,
) -> dict:
    pr: dict = {
        "headRefName": branch,
        "state": state,
        "url": url,
        "number": number,
        "mergeCommit": merge_commit,
        "statusCheckRollup": checks,
    }
    return pr


# ---------------------------------------------------------------------------
# _match_pr
# ---------------------------------------------------------------------------


class TestMatchPr:
    def test_matches_on_branch_name(self):
        art = _make_artifact(branch="agent/task-001")
        prs = [_make_gh_pr(branch="agent/task-001")]
        assert _match_pr(art, prs) is not None

    def test_no_match(self):
        art = _make_artifact(branch="agent/task-001")
        prs = [_make_gh_pr(branch="agent/task-999")]
        assert _match_pr(art, prs) is None

    def test_empty_prs(self):
        art = _make_artifact()
        assert _match_pr(art, []) is None


# ---------------------------------------------------------------------------
# _extract_detail
# ---------------------------------------------------------------------------


class TestExtractDetail:
    def test_basic_fields(self):
        pr = _make_gh_pr(number=55, url="https://github.com/org/repo/pull/55")
        detail = _extract_detail(pr)
        assert detail["pr_number"] == 55
        assert detail["pr_url"] == "https://github.com/org/repo/pull/55"

    def test_merge_commit(self):
        pr = _make_gh_pr(merge_commit={"oid": "deadbeef123"})
        detail = _extract_detail(pr)
        assert detail["merge_sha"] == "deadbeef123"

    def test_ci_passed(self):
        pr = _make_gh_pr(checks=[{"conclusion": "SUCCESS", "status": "COMPLETED"}])
        detail = _extract_detail(pr)
        assert detail["ci_status"] == "passed"

    def test_ci_failed(self):
        pr = _make_gh_pr(checks=[{"conclusion": "FAILURE", "status": "COMPLETED"}])
        detail = _extract_detail(pr)
        assert detail["ci_status"] == "failed"

    def test_ci_running(self):
        pr = _make_gh_pr(checks=[{"conclusion": "", "status": "IN_PROGRESS"}])
        detail = _extract_detail(pr)
        assert detail["ci_status"] == "running"

    def test_no_checks(self):
        pr = _make_gh_pr(checks=None)
        detail = _extract_detail(pr)
        assert "ci_status" not in detail


# ---------------------------------------------------------------------------
# _determine_state
# ---------------------------------------------------------------------------


class TestDetermineState:
    def test_merged(self):
        pr = _make_gh_pr(state="MERGED")
        assert _determine_state(pr, {}, "open") == "merged"

    def test_merged_idempotent(self):
        pr = _make_gh_pr(state="MERGED")
        assert _determine_state(pr, {}, "merged") is None

    def test_closed(self):
        pr = _make_gh_pr(state="CLOSED")
        assert _determine_state(pr, {}, "open") == "closed"

    def test_ci_failed(self):
        pr = _make_gh_pr(state="OPEN")
        assert _determine_state(pr, {"ci_status": "failed"}, "pushed") == "ci_failed"

    def test_ci_running(self):
        pr = _make_gh_pr(state="OPEN")
        assert _determine_state(pr, {"ci_status": "running"}, "pushed") == "ci_running"

    def test_ci_passed(self):
        pr = _make_gh_pr(state="OPEN")
        assert _determine_state(pr, {"ci_status": "passed"}, "ci_running") == "ci_passed"

    def test_open_no_ci(self):
        pr = _make_gh_pr(state="OPEN")
        assert _determine_state(pr, {}, "pushed") == "open"

    def test_no_change(self):
        pr = _make_gh_pr(state="OPEN")
        assert _determine_state(pr, {"ci_status": "passed"}, "ci_passed") is None


# ---------------------------------------------------------------------------
# poll_prs (integration with mocked subprocess)
# ---------------------------------------------------------------------------


class TestPollPrs:
    def test_empty_input(self):
        results = poll_prs([])
        assert results == []

    @patch("agent_os.pollers.github_pr._query_prs")
    def test_detects_merge(self, mock_query):
        mock_query.return_value = (
            [
                _make_gh_pr(
                    branch="agent/task-001",
                    state="MERGED",
                    merge_commit={"oid": "abc123"},
                )
            ],
            None,
        )
        art = _make_artifact(current_state="open")
        results = poll_prs([art])
        assert len(results) == 1
        assert results[0].new_state == "merged"
        assert results[0].detail["merge_sha"] == "abc123"

    @patch("agent_os.pollers.github_pr._query_prs")
    def test_no_state_change(self, mock_query):
        mock_query.return_value = (
            [_make_gh_pr(branch="agent/task-001", state="OPEN")],
            None,
        )
        art = _make_artifact(current_state="open")
        results = poll_prs([art])
        assert len(results) == 1
        assert results[0].new_state is None

    @patch("agent_os.pollers.github_pr._query_prs")
    def test_pr_not_found(self, mock_query):
        mock_query.return_value = ([], None)
        art = _make_artifact()
        results = poll_prs([art])
        assert len(results) == 1
        assert results[0].new_state is None
        assert results[0].error is None

    @patch("agent_os.pollers.github_pr._query_prs")
    def test_query_error(self, mock_query):
        mock_query.return_value = ([], "gh CLI not installed")
        art = _make_artifact()
        results = poll_prs([art])
        assert len(results) == 1
        assert results[0].error == "gh CLI not installed"

    @patch("agent_os.pollers.github_pr._query_prs")
    def test_ci_failure_detected(self, mock_query):
        mock_query.return_value = (
            [
                _make_gh_pr(
                    branch="agent/task-001",
                    state="OPEN",
                    checks=[{"conclusion": "FAILURE", "status": "COMPLETED"}],
                )
            ],
            None,
        )
        art = _make_artifact(current_state="pushed")
        results = poll_prs([art])
        assert len(results) == 1
        assert results[0].new_state == "ci_failed"
        assert results[0].detail["ci_status"] == "failed"

    @patch("agent_os.pollers.github_pr._query_prs")
    def test_updates_ref_when_missing(self, mock_query):
        mock_query.return_value = (
            [_make_gh_pr(branch="agent/task-001", url="https://github.com/org/repo/pull/42")],
            None,
        )
        art = _make_artifact(ref="", current_state="pushed")
        results = poll_prs([art])
        assert len(results) == 1
        assert results[0].detail.get("update_ref") == "https://github.com/org/repo/pull/42"


# ---------------------------------------------------------------------------
# gh_available
# ---------------------------------------------------------------------------


class TestGhAvailable:
    @patch("agent_os.pollers.github_pr.subprocess.run")
    def test_available(self, mock_run):
        mock_run.return_value = type("Result", (), {"returncode": 0})()
        assert gh_available() is True

    @patch("agent_os.pollers.github_pr.subprocess.run")
    def test_not_authenticated(self, mock_run):
        mock_run.return_value = type("Result", (), {"returncode": 1})()
        assert gh_available() is False

    @patch("agent_os.pollers.github_pr.subprocess.run", side_effect=FileNotFoundError)
    def test_not_installed(self, mock_run):
        assert gh_available() is False
