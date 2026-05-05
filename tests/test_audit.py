"""Tests for agent_os.audit — cross-reference filesystem state checks."""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from agent_os.audit import (
    check_budget,
    check_dispatch,
    check_freshness,
    check_prs,
    check_stale_tasks,
    check_worktrees,
    format_audit_json,
    format_audit_report,
    run_audit,
)
from agent_os.config import Config

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_agent_registry(config: Config, agent_id: str, role: str = "Software Engineer") -> None:
    """Create a minimal agent registry file."""
    reg_dir = config.registry_dir
    reg_dir.mkdir(parents=True, exist_ok=True)
    (reg_dir / f"{agent_id}.md").write_text(
        f"---\nid: {agent_id}\nname: Test Agent\nrole: {role}\nmodel: test\n---\nTest body.\n"
    )


def _write_task(directory: Path, task_id: str, assigned_to: str = "agent-001-maker") -> Path:
    """Create a minimal task file and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{task_id}.md"
    path.write_text(f"---\nid: {task_id}\ntitle: Test task\nassigned_to: {assigned_to}\nstatus: done\n---\nBody.\n")
    return path


def _write_log_entry(config: Config, agent_id: str, action: str, task_id: str | None = None) -> None:
    """Write a log entry for today."""
    log_dir = config.logs_dir / agent_id
    log_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(config.tz)
    date_str = now.strftime("%Y-%m-%d")
    log_file = log_dir / f"{date_str}.jsonl"

    entry = {
        "ts": now.isoformat(),
        "action": action,
        "refs": {},
    }
    if task_id:
        entry["refs"]["task"] = task_id

    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ---------------------------------------------------------------------------
# check_prs
# ---------------------------------------------------------------------------


class TestCheckPrs:
    def test_no_project_configured(self, aios_config):
        """When workspace SDLC is not configured, should pass."""
        result = check_prs(aios_config)
        assert result.status == "pass"
        assert "not configured" in result.summary.lower() or "not configured" in result.findings[0].message.lower()

    def test_no_done_tasks(self, aios_config):
        """With SDLC configured but no done tasks, should pass."""
        cfg = Config(
            company_root=aios_config.company_root,
            project_validate_commands=["pytest"],
        )
        result = check_prs(cfg)
        assert result.status == "pass"

    @patch("agent_os.audit.subprocess.run")
    def test_gh_not_installed(self, mock_run, aios_config):
        """When gh CLI is not available, should warn gracefully."""
        cfg = Config(
            company_root=aios_config.company_root,
            project_validate_commands=["pytest"],
        )
        _write_task(cfg.tasks_done, "task-2026-0503-001", "agent-001-maker")
        mock_run.side_effect = FileNotFoundError("gh not found")
        result = check_prs(cfg)
        assert result.status == "warn"
        assert any("not available" in f.message for f in result.findings)

    @patch("agent_os.audit.subprocess.run")
    def test_gh_not_authenticated(self, mock_run, aios_config):
        """When gh auth fails, should warn gracefully."""
        from unittest.mock import MagicMock

        cfg = Config(
            company_root=aios_config.company_root,
            project_validate_commands=["pytest"],
        )
        _write_task(cfg.tasks_done, "task-2026-0503-001", "agent-001-maker")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_run.return_value = mock_result
        result = check_prs(cfg)
        assert result.status == "warn"
        assert any("not authenticated" in f.message for f in result.findings)

    @patch("agent_os.audit.subprocess.run")
    def test_finds_missing_prs(self, mock_run, aios_config):
        """Tasks in done/ without matching PRs should be flagged."""
        from unittest.mock import MagicMock

        cfg = Config(
            company_root=aios_config.company_root,
            project_validate_commands=["pytest"],
        )

        _write_agent_registry(cfg, "agent-001-maker")
        _write_task(cfg.tasks_done, "task-2026-0503-001", "agent-001-maker")
        _write_task(cfg.tasks_done, "task-2026-0503-002", "agent-001-maker")

        # Mock gh auth status (success) and gh pr list
        auth_result = MagicMock()
        auth_result.returncode = 0
        pr_result = MagicMock()
        pr_result.returncode = 0
        pr_result.stdout = json.dumps(
            [
                {"headRefName": "agent/task-2026-0503-001", "state": "MERGED", "url": "https://github.com/test/pr/1"},
            ]
        )

        mock_run.side_effect = [auth_result, pr_result]

        result = check_prs(cfg)
        assert result.status == "warn"
        assert "1 verified" in result.summary
        assert "1 missing" in result.summary


# ---------------------------------------------------------------------------
# check_budget
# ---------------------------------------------------------------------------


class TestCheckBudget:
    def test_no_cost_files(self, aios_config):
        """When there are no cost files, should still produce a report."""
        result = check_budget(aios_config)
        assert result.status in ("pass", "warn")
        assert "$0.00" in result.summary

    def test_cost_matches_state(self, aios_config):
        """When JSONL and scheduler state agree, should pass."""
        # Write cost JSONL
        today = datetime.now(aios_config.tz).strftime("%Y-%m-%d")
        aios_config.costs_dir.mkdir(parents=True, exist_ok=True)
        cost_file = aios_config.costs_dir / f"{today}.jsonl"
        cost_file.write_text(
            json.dumps({"cost_usd": 1.50, "agent": "agent-001"})
            + "\n"
            + json.dumps({"cost_usd": 2.00, "agent": "agent-003"})
            + "\n"
        )

        # Write scheduler state
        aios_config.operations_dir.mkdir(parents=True, exist_ok=True)
        aios_config.scheduler_state_file.write_text(
            json.dumps(
                {
                    "budget": {"daily_spent": 3.50, "daily_cap": 100.0},
                }
            )
        )

        result = check_budget(aios_config)
        assert result.status == "pass"
        assert "$3.50" in result.summary

    def test_budget_discrepancy(self, aios_config):
        """When JSONL and scheduler state disagree, should warn."""
        today = datetime.now(aios_config.tz).strftime("%Y-%m-%d")
        aios_config.costs_dir.mkdir(parents=True, exist_ok=True)
        cost_file = aios_config.costs_dir / f"{today}.jsonl"
        cost_file.write_text(json.dumps({"cost_usd": 5.00}) + "\n")

        aios_config.operations_dir.mkdir(parents=True, exist_ok=True)
        aios_config.scheduler_state_file.write_text(
            json.dumps(
                {
                    "budget": {"daily_spent": 13.22, "daily_cap": 75.0},
                }
            )
        )

        result = check_budget(aios_config)
        assert result.status == "warn"
        assert any("discrepancy" in f.message.lower() for f in result.findings)

    def test_no_scheduler_state(self, aios_config):
        """When scheduler-state.json doesn't exist, should warn."""
        result = check_budget(aios_config)
        assert result.status == "warn"
        assert any("no scheduler-state" in f.message.lower() for f in result.findings)


# ---------------------------------------------------------------------------
# check_dispatch
# ---------------------------------------------------------------------------


class TestCheckDispatch:
    def test_no_agents(self, aios_config):
        result = check_dispatch(aios_config)
        assert result.status == "pass"

    def test_no_scheduler_state(self, aios_config):
        _write_agent_registry(aios_config, "agent-001-maker")
        result = check_dispatch(aios_config)
        assert result.status == "warn"

    def test_recent_dispatch(self, aios_config):
        _write_agent_registry(aios_config, "agent-001-maker")

        # Write scheduler state
        aios_config.operations_dir.mkdir(parents=True, exist_ok=True)
        aios_config.scheduler_state_file.write_text(json.dumps({"last_tick": "now"}))

        # Write a recent log entry
        _write_log_entry(aios_config, "agent-001-maker", "cycle_start")

        result = check_dispatch(aios_config)
        assert result.status == "pass"
        assert any("agent-001-maker" in f.message for f in result.findings)

    def test_stale_agent(self, aios_config):
        _write_agent_registry(aios_config, "agent-001-maker")

        # Write scheduler state
        aios_config.operations_dir.mkdir(parents=True, exist_ok=True)
        aios_config.scheduler_state_file.write_text(json.dumps({"last_tick": "now"}))

        # No log entries — agent should be flagged as stale
        result = check_dispatch(aios_config)
        assert result.status == "warn"
        assert any("no dispatch" in f.message.lower() for f in result.findings)


# ---------------------------------------------------------------------------
# check_freshness
# ---------------------------------------------------------------------------


class TestCheckFreshness:
    def test_no_agents(self, aios_config):
        result = check_freshness(aios_config)
        assert result.status == "pass"

    def test_fresh_working_memory(self, aios_config):
        _write_agent_registry(aios_config, "agent-001-maker")
        state_dir = aios_config.agents_state_dir / "agent-001-maker"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "working-memory.md").write_text("# Working Memory\nFresh.\n")

        result = check_freshness(aios_config)
        assert result.status == "pass"
        assert "fresh" in result.summary.lower() or result.pass_count > 0

    def test_stale_working_memory(self, aios_config):
        _write_agent_registry(aios_config, "agent-001-maker")
        state_dir = aios_config.agents_state_dir / "agent-001-maker"
        state_dir.mkdir(parents=True, exist_ok=True)
        wm_path = state_dir / "working-memory.md"
        wm_path.write_text("# Working Memory\nStale.\n")

        # Make it look 50 hours old
        old_time = time.time() - (50 * 3600)
        os.utime(wm_path, (old_time, old_time))

        result = check_freshness(aios_config)
        assert result.status == "warn"
        assert any("50h" in f.message or "50" in f.message for f in result.findings)

    def test_missing_working_memory(self, aios_config):
        _write_agent_registry(aios_config, "agent-001-maker")
        # Don't create working-memory.md
        result = check_freshness(aios_config)
        assert result.status == "warn"
        assert any("no working-memory" in f.message for f in result.findings)


# ---------------------------------------------------------------------------
# check_worktrees
# ---------------------------------------------------------------------------


class TestCheckWorktrees:
    def test_no_worktrees_dir(self, aios_config):
        result = check_worktrees(aios_config)
        assert result.status == "pass"

    def test_clean_worktrees(self, aios_config):
        """Worktrees that match in-progress tasks should pass."""
        wt_root = aios_config.worktrees_root
        (wt_root / "task-2026-0503-001").mkdir(parents=True, exist_ok=True)
        _write_task(aios_config.tasks_in_progress, "task-2026-0503-001")

        result = check_worktrees(aios_config)
        assert result.status == "pass"

    def test_dead_worktree(self, aios_config):
        """Worktrees without matching in-progress tasks should warn."""
        wt_root = aios_config.worktrees_root
        (wt_root / "task-2026-0503-001").mkdir(parents=True, exist_ok=True)
        # No matching in-progress task

        result = check_worktrees(aios_config)
        assert result.status == "warn"
        assert any("dead worktree" in f.message for f in result.findings)

    def test_archive_ignored(self, aios_config):
        """_archive directory should be ignored."""
        wt_root = aios_config.worktrees_root
        (wt_root / "_archive" / "old-task").mkdir(parents=True, exist_ok=True)

        result = check_worktrees(aios_config)
        assert result.status == "pass"


# ---------------------------------------------------------------------------
# check_stale_tasks
# ---------------------------------------------------------------------------


class TestCheckStaleTasks:
    def test_no_tasks(self, aios_config):
        result = check_stale_tasks(aios_config)
        assert result.status == "pass"

    def test_fresh_task(self, aios_config):
        """Recently created task should pass."""
        _write_task(aios_config.tasks_in_progress, "task-2026-0503-001")
        result = check_stale_tasks(aios_config, threshold_hours=6.0)
        assert result.status == "pass"

    def test_stale_task_no_activity(self, aios_config):
        """Old task with no log activity should warn."""
        task_path = _write_task(aios_config.tasks_in_progress, "task-2026-0503-001")

        # Make it look 8 hours old
        old_time = time.time() - (8 * 3600)
        os.utime(task_path, (old_time, old_time))

        result = check_stale_tasks(aios_config, threshold_hours=6.0)
        assert result.status == "warn"
        assert any("8h" in f.message or "no recent log" in f.message for f in result.findings)

    def test_old_task_with_activity(self, aios_config):
        """Old task with recent log activity should pass."""
        _write_agent_registry(aios_config, "agent-001-maker")
        task_path = _write_task(aios_config.tasks_in_progress, "task-2026-0503-001", "agent-001-maker")

        # Make task file look old
        old_time = time.time() - (8 * 3600)
        os.utime(task_path, (old_time, old_time))

        # But write a recent log entry referencing this task
        _write_log_entry(aios_config, "agent-001-maker", "task_progress", "task-2026-0503-001")

        result = check_stale_tasks(aios_config, threshold_hours=6.0)
        assert result.status == "pass"
        assert any("recent log activity" in f.message for f in result.findings)

    def test_custom_threshold(self, aios_config):
        """Custom threshold should be respected."""
        task_path = _write_task(aios_config.tasks_in_progress, "task-2026-0503-001")

        # Make it 2 hours old
        old_time = time.time() - (2 * 3600)
        os.utime(task_path, (old_time, old_time))

        # With 1h threshold, should warn
        result = check_stale_tasks(aios_config, threshold_hours=1.0)
        assert result.status == "warn"

        # With 3h threshold, should pass
        result = check_stale_tasks(aios_config, threshold_hours=3.0)
        assert result.status == "pass"


# ---------------------------------------------------------------------------
# run_audit
# ---------------------------------------------------------------------------


class TestRunAudit:
    def test_runs_all_checks(self, aios_config):
        """When no checks specified, runs all."""
        report = run_audit(config=aios_config)
        assert len(report.checks) == 6
        check_names = {c.name for c in report.checks}
        assert "Budget consistency" in check_names
        assert "Cognitive freshness" in check_names
        assert "Worktree hygiene" in check_names
        assert "Stale tasks" in check_names

    def test_runs_specific_checks(self, aios_config):
        """When specific checks requested, only runs those."""
        report = run_audit(config=aios_config, checks=["budget", "freshness"])
        assert len(report.checks) == 2
        check_names = {c.name for c in report.checks}
        assert "Budget consistency" in check_names
        assert "Cognitive freshness" in check_names

    def test_report_has_timestamp(self, aios_config):
        report = run_audit(config=aios_config, checks=["budget"])
        assert report.timestamp


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


class TestFormatAuditReport:
    def test_human_format(self, aios_config):
        report = run_audit(config=aios_config, checks=["budget"])
        output = format_audit_report(report, no_color=True)
        assert "agent-os audit" in output
        assert "Budget consistency" in output

    def test_no_color_has_no_escapes(self, aios_config):
        report = run_audit(config=aios_config, checks=["budget"])
        output = format_audit_report(report, no_color=True)
        assert "\033[" not in output

    def test_json_format(self, aios_config):
        report = run_audit(config=aios_config, checks=["budget"])
        output = format_audit_json(report)
        data = json.loads(output)
        assert "timestamp" in data
        assert "summary" in data
        assert "checks" in data
        assert len(data["checks"]) == 1
        assert data["checks"][0]["name"] == "Budget consistency"

    def test_json_structure(self, aios_config):
        report = run_audit(config=aios_config, checks=["budget", "freshness"])
        output = format_audit_json(report)
        data = json.loads(output)
        assert data["summary"]["pass"] + data["summary"]["warn"] + data["summary"]["fail"] == 2
        for check in data["checks"]:
            assert "name" in check
            assert "status" in check
            assert "summary" in check
            assert "findings" in check
            for finding in check["findings"]:
                assert "level" in finding
                assert "message" in finding
                assert finding["level"] in ("pass", "warn", "fail")


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


class TestCLIIntegration:
    def test_audit_parser_exists(self):
        """The audit subcommand should be registered."""
        from agent_os.cli import _build_parser

        parser = _build_parser()
        # Parse --all to verify the subcommand exists
        args = parser.parse_args(["audit", "--all"])
        assert args.command == "audit"
        assert args.all is True

    def test_audit_parser_check_flags(self):
        from agent_os.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["audit", "--check-prs", "--check-budget", "--json"])
        assert args.check_prs is True
        assert args.check_budget is True
        assert args.json is True
        assert args.check_dispatch is False

    def test_audit_parser_stale_hours(self):
        from agent_os.cli import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["audit", "--stale-hours", "12"])
        assert args.stale_hours == 12.0
