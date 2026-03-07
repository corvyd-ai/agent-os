"""Agent registry parser — reads agent .md files and maps capabilities to SDK tools.

Every public function accepts an optional ``config: Config | None`` parameter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import Config, get_config


@dataclass
class AgentConfig:
    agent_id: str
    name: str
    role: str
    model: str
    allowed_tools: list[str]
    registry_path: Path
    system_body: str  # The markdown body (role description, capabilities, etc.)
    meta: dict = field(default_factory=dict)


# Default role-to-tools mapping. Companies can override via Config.role_tools.
DEFAULT_ROLE_TOOLS: dict[str, list[str]] = {
    "PM / PMM": ["Read", "Write", "Glob", "Grep", "WebSearch", "WebFetch"],
    "Software Engineer": ["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    "DevOps / Infrastructure": ["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    "Board Secretary / Human Interface": ["Read", "Write", "Glob", "Grep"],
    "Content Writer": ["Read", "Write", "Glob", "Grep", "WebSearch", "WebFetch"],
}

# Backward compat alias
ROLE_TOOLS = DEFAULT_ROLE_TOOLS

# Fallback: default tools for any agent
DEFAULT_TOOLS = ["Read", "Write", "Glob", "Grep"]


def _parse_frontmatter(path: Path) -> tuple[dict, str]:
    """Parse YAML frontmatter + markdown body from a file."""
    text = path.read_text()
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = yaml.safe_load(parts[1]) or {}
    body = parts[2].lstrip("\n")
    return meta, body


def load_agent(agent_id: str, *, config: Config | None = None) -> AgentConfig:
    """Load an agent's configuration from its registry file.

    agent_id can be either the short form (e.g. "agent-006")
    or the full slug (e.g. "agent-006-product-manager").
    """
    cfg = config or get_config()

    # Find the registry file
    registry_file = _find_registry_file(agent_id, registry_dir=cfg.registry_dir)
    if not registry_file:
        raise FileNotFoundError(f"No registry file found for agent '{agent_id}' in {cfg.registry_dir}")

    meta, body = _parse_frontmatter(registry_file)
    full_id = meta.get("id", agent_id)
    role = meta.get("role", "")

    # Determine model
    model = cfg.agent_model_overrides.get(full_id, cfg.default_model)

    # Determine tools from role: config overrides take priority
    role_tools = cfg.role_tools if cfg.role_tools else DEFAULT_ROLE_TOOLS
    tools = role_tools.get(role, DEFAULT_TOOLS)

    return AgentConfig(
        agent_id=full_id,
        name=meta.get("name", agent_id),
        role=role,
        model=model,
        allowed_tools=tools,
        registry_path=registry_file,
        system_body=body,
        meta=meta,
    )


def _find_registry_file(
    agent_id: str, *, registry_dir: Path | None = None, config: Config | None = None
) -> Path | None:
    """Find registry file by agent_id prefix."""
    if registry_dir is None:
        cfg = config or get_config()
        registry_dir = cfg.registry_dir
    if not registry_dir.exists():
        return None
    for f in registry_dir.iterdir():
        if f.name.startswith(agent_id) and f.name.endswith(".md"):
            return f
    return None


def list_agents(*, config: Config | None = None) -> list[AgentConfig]:
    """List all registered agents."""
    cfg = config or get_config()
    agents = []
    if not cfg.registry_dir.exists():
        return agents
    for f in sorted(cfg.registry_dir.iterdir()):
        if not f.name.endswith(".md"):
            continue
        try:
            agents.append(load_agent(f.stem, config=cfg))
        except FileNotFoundError:
            continue
    return agents
