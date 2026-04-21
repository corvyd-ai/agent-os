"""Tests for runtime.tools — MCP tool registration."""

import asyncio

from agent_os.core import _parse_frontmatter, _write_frontmatter, claim_task
from agent_os.tools import AIOS_TOOL_NAMES, create_aios_tools_server


def test_all_tool_names_have_prefix():
    for name in AIOS_TOOL_NAMES:
        assert name.startswith("mcp__aios__"), f"Tool {name} missing mcp__aios__ prefix"


def test_tool_count():
    assert len(AIOS_TOOL_NAMES) == 7


def test_create_server_returns_without_error():
    server = create_aios_tools_server(agent_id="agent-001-maker")
    assert server is not None


def _seed_in_progress_task(aios_fs, task_id):
    """Put a task directly into in-progress/ as if claim_task had run."""
    meta = {
        "id": task_id,
        "title": f"Task {task_id}",
        "status": "queued",
        "priority": "medium",
        "assigned_to": "agent-001-maker",
    }
    _write_frontmatter(aios_fs["TASKS_QUEUED"] / f"{task_id}.md", meta, "body")
    claim_task("agent-001-maker", task_id)


def test_complete_task_tool_defer_mode_leaves_task_in_progress(aios_fs):
    """In workspace mode (defer_complete=True), the MCP complete_task tool
    acknowledges success but must NOT move the task out of in-progress/ —
    the runner takes over and finalizes only after commit/push succeed."""
    _seed_in_progress_task(aios_fs, "task-2026-0101-001")

    server = create_aios_tools_server(agent_id="agent-001-maker", defer_complete=True)
    handler = server["_tools"]["complete_task"].handler

    response = asyncio.run(handler({"task_id": "task-2026-0101-001"}))

    assert not response.get("is_error")
    # Task stays in in-progress/; nothing moved
    in_progress = list(aios_fs["TASKS_IN_PROGRESS"].glob("task-2026-0101-001*"))
    assert len(in_progress) == 1
    assert not list(aios_fs["TASKS_DONE"].glob("task-2026-0101-001*"))
    meta, _ = _parse_frontmatter(in_progress[0])
    assert meta["status"] == "in-progress"


def test_complete_task_tool_default_mode_moves_to_done(aios_fs):
    """Outside workspace mode (default), the MCP complete_task tool still
    moves the task — preserves the pre-workspace behavior for non-builder
    roles and companies without a [project] section."""
    _seed_in_progress_task(aios_fs, "task-2026-0101-002")

    server = create_aios_tools_server(agent_id="agent-001-maker")
    handler = server["_tools"]["complete_task"].handler

    response = asyncio.run(handler({"task_id": "task-2026-0101-002"}))

    assert not response.get("is_error")
    assert list(aios_fs["TASKS_DONE"].glob("task-2026-0101-002*"))
    assert not list(aios_fs["TASKS_IN_PROGRESS"].glob("task-2026-0101-002*"))
