"""TDD tests for `agent-os tasks list` and `agent-os tasks show`.

Uses the `tasks` (plural) subcommand to avoid colliding with the existing
`agent-os task <agent> <id>` runner command.
"""

from __future__ import annotations

import json

from agent_os.config import Config


def _write_task(directory, task_id: str, *, title: str = "The task", body: str = "body", **fm) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"id: {task_id}", f'title: "{title}"']
    for k, v in fm.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    lines.append(body)
    (directory / f"{task_id}.md").write_text("\n".join(lines))


# --- task list -------------------------------------------------------------


def test_render_task_list_empty(aios_config: Config):
    from agent_os.task_cmd import render_task_list

    out = render_task_list(aios_config)
    assert "no tasks" in out.lower() or out.strip() != ""


def test_render_task_list_includes_all_statuses(aios_config: Config):
    from agent_os.task_cmd import render_task_list

    _write_task(aios_config.tasks_queued, "task-q-1", title="Queue one", assigned_to="agent-001")
    _write_task(aios_config.tasks_done, "task-d-1", title="Done one", assigned_to="agent-001")
    _write_task(aios_config.tasks_failed, "task-f-1", title="Failed one", assigned_to="agent-001")

    out = render_task_list(aios_config)
    assert "task-q-1" in out
    assert "task-d-1" in out
    assert "task-f-1" in out


def test_render_task_list_status_filter(aios_config: Config):
    from agent_os.task_cmd import render_task_list

    _write_task(aios_config.tasks_queued, "task-q-1", title="Queue one")
    _write_task(aios_config.tasks_done, "task-d-1", title="Done one")

    out = render_task_list(aios_config, status="queued")
    assert "task-q-1" in out
    assert "task-d-1" not in out


def test_render_task_list_agent_filter(aios_config: Config):
    from agent_os.task_cmd import render_task_list

    _write_task(aios_config.tasks_queued, "task-q-1", title="Queue one", assigned_to="agent-001-maker")
    _write_task(aios_config.tasks_queued, "task-q-2", title="Queue two", assigned_to="agent-002-writer")

    out = render_task_list(aios_config, agent="agent-001-maker")
    assert "task-q-1" in out
    assert "task-q-2" not in out


def test_render_task_list_json(aios_config: Config):
    from agent_os.task_cmd import render_task_list_json

    _write_task(aios_config.tasks_queued, "task-q-1", title="Queue one", assigned_to="agent-001")
    parsed = json.loads(render_task_list_json(aios_config))
    assert isinstance(parsed, list)
    assert any(t["id"] == "task-q-1" for t in parsed)


# --- task show -------------------------------------------------------------


def test_render_task_show_missing(aios_config: Config):
    from agent_os.task_cmd import render_task_show

    out = render_task_show(aios_config, "task-does-not-exist")
    assert "not found" in out.lower()


def test_render_task_show_returns_body_and_metadata(aios_config: Config):
    from agent_os.task_cmd import render_task_show

    _write_task(
        aios_config.tasks_in_progress,
        "task-2026-0419-001",
        title="Fix the bug",
        body="## Repro steps\n\nA body paragraph.",
        assigned_to="agent-001-maker",
        priority="high",
    )

    out = render_task_show(aios_config, "task-2026-0419-001")
    assert "task-2026-0419-001" in out
    assert "Fix the bug" in out
    assert "in-progress" in out.lower()  # status derived from the directory
    assert "A body paragraph" in out


# --- CLI wiring ------------------------------------------------------------


def test_cli_registers_tasks_subparser():
    from agent_os.cli import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["tasks", "list"])
    assert args.command == "tasks"
    assert args.tasks_action == "list"

    args = parser.parse_args(["tasks", "show", "task-001"])
    assert args.tasks_action == "show"
    assert args.task_id == "task-001"
