"""Tests for runtime.tools — MCP tool registration."""

from agent_os.tools import AIOS_TOOL_NAMES, create_aios_tools_server


def test_all_tool_names_have_prefix():
    for name in AIOS_TOOL_NAMES:
        assert name.startswith("mcp__aios__"), f"Tool {name} missing mcp__aios__ prefix"


def test_tool_count():
    assert len(AIOS_TOOL_NAMES) == 6


def test_create_server_returns_without_error():
    server = create_aios_tools_server(agent_id="agent-001-maker")
    assert server is not None
