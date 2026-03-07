"""agent-os — The open-source operations layer for AI agents."""

__version__ = "0.1.0"

from .composer import PromptComposer
from .config import Config, configure, get_config
from .registry import AgentConfig, list_agents, load_agent

__all__ = [
    "AgentConfig",
    "Config",
    "PromptComposer",
    "__version__",
    "configure",
    "get_config",
    "list_agents",
    "load_agent",
]
