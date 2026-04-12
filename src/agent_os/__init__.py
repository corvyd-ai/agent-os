"""agent-os — The open-source operations layer for AI agents."""

try:
    from ._version import __version__
except ImportError:  # editable install without build
    from importlib.metadata import version as _v

    __version__ = _v("agent-os")

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
