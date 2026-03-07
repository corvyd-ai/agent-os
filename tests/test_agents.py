"""Tests for agent_os.registry — agent registry parsing and tool mapping."""

import pytest

from agent_os.core import _write_frontmatter
from agent_os.registry import (
    DEFAULT_TOOLS,
    ROLE_TOOLS,
    load_agent,
)


def _create_agent_file(registry_dir, agent_id, name, role):
    """Helper: write a minimal agent registry file."""
    meta = {
        "id": agent_id,
        "name": name,
        "role": role,
    }
    body = f"You are {name}, the {role}."
    path = registry_dir / f"{agent_id}.md"
    _write_frontmatter(path, meta, body)
    return path


def test_load_agent_basic(aios_fs):
    _create_agent_file(aios_fs["REGISTRY_DIR"], "agent-001-maker", "The Maker", "Software Engineer")
    config = load_agent("agent-001-maker")
    assert config.agent_id == "agent-001-maker"
    assert config.name == "The Maker"
    assert config.role == "Software Engineer"
    assert "The Maker" in config.system_body


def test_load_agent_role_tools(aios_fs):
    _create_agent_file(aios_fs["REGISTRY_DIR"], "agent-001-maker", "The Maker", "Software Engineer")
    config = load_agent("agent-001-maker")
    expected_tools = ROLE_TOOLS["Software Engineer"]
    assert config.allowed_tools == expected_tools
    assert "Bash" in config.allowed_tools
    assert "Edit" in config.allowed_tools


def test_load_agent_default_tools(aios_fs):
    _create_agent_file(aios_fs["REGISTRY_DIR"], "agent-099-unknown", "The Unknown", "Some Unlisted Role")
    config = load_agent("agent-099-unknown")
    assert config.allowed_tools == DEFAULT_TOOLS


def test_load_agent_short_id(aios_fs):
    _create_agent_file(aios_fs["REGISTRY_DIR"], "agent-001-maker", "The Maker", "Software Engineer")
    config = load_agent("agent-001")
    assert config.agent_id == "agent-001-maker"


def test_load_agent_full_id(aios_fs):
    _create_agent_file(aios_fs["REGISTRY_DIR"], "agent-006-strategist", "The Strategist", "PM / PMM")
    config = load_agent("agent-006-strategist")
    assert config.agent_id == "agent-006-strategist"
    assert "WebSearch" in config.allowed_tools


def test_load_agent_not_found(aios_fs):
    with pytest.raises(FileNotFoundError, match="No registry file found"):
        load_agent("agent-999-ghost")
