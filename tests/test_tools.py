"""Tests for runtime.tools — MCP tool registration."""

import asyncio
import json

from agent_os.core import _parse_frontmatter, _write_frontmatter, claim_task
from agent_os.tools import AIOS_TOOL_NAMES, build_aios_tools, create_aios_tools_server


def test_all_tool_names_have_prefix():
    for name in AIOS_TOOL_NAMES:
        assert name.startswith("mcp__aios__"), f"Tool {name} missing mcp__aios__ prefix"


def test_tool_count():
    assert len(AIOS_TOOL_NAMES) == 7


def test_create_server_returns_without_error():
    server = create_aios_tools_server(agent_id="agent-001-maker")
    assert server is not None


def test_server_dict_is_json_safe_shape(aios_fs):
    """Regression: every SDK invocation dies with "Object of type SdkMcpTool
    is not JSON serializable" if we attach extra tool references to the
    server dict. The SDK JSON-encodes this dict when handing mcp_servers to
    the CLI subprocess, so only the canonical `{type, name, instance}` keys
    from `create_sdk_mcp_server` are allowed — nothing else.
    """
    server = create_aios_tools_server(agent_id="agent-001-maker")
    # Canonical shape from claude_agent_sdk.create_sdk_mcp_server — do not
    # add keys here, even for "test convenience".
    assert set(server.keys()) == {"type", "name", "instance"}
    # The metadata subset (everything except the opaque `instance` object)
    # must JSON-encode without raising. This is what the SDK actually does
    # when spawning the CLI: instance is handled specially, the rest is
    # serialized.
    metadata = {k: v for k, v in server.items() if k != "instance"}
    json.dumps(metadata)  # must not raise


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


def _handler(tools, name):
    for t in tools:
        if t.name == name:
            return t.handler
    raise KeyError(name)


def test_complete_task_tool_defer_mode_leaves_task_in_progress(aios_fs):
    """In workspace mode (defer_complete=True), the MCP complete_task tool
    acknowledges success but must NOT move the task out of in-progress/ —
    the runner takes over and finalizes only after commit/push succeed."""
    _seed_in_progress_task(aios_fs, "task-2026-0101-001")

    tools = build_aios_tools(agent_id="agent-001-maker", defer_complete=True)
    response = asyncio.run(_handler(tools, "complete_task")({"task_id": "task-2026-0101-001"}))

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

    tools = build_aios_tools(agent_id="agent-001-maker")
    response = asyncio.run(_handler(tools, "complete_task")({"task_id": "task-2026-0101-002"}))

    assert not response.get("is_error")
    assert list(aios_fs["TASKS_DONE"].glob("task-2026-0101-002*"))
    assert not list(aios_fs["TASKS_IN_PROGRESS"].glob("task-2026-0101-002*"))
