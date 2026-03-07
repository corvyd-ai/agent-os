"""agent-os configuration — paths, model defaults, cost limits.

Config is a frozen dataclass holding all runtime parameters. Paths are derived
from `company_root` so a single override switches the entire filesystem tree
(useful for testing and future multi-tenant support).

Company-level overrides can be provided via an ``agent-os.toml`` file.
Discovery order: ``--config`` CLI flag > ``AGENT_OS_CONFIG`` env var >
walk up from ``AGENT_OS_ROOT`` looking for ``agent-os.toml``.

Usage:
    from agent_os.config import get_config, configure, Config

    # Default singleton (reads AGENT_OS_ROOT env var or uses default)
    cfg = get_config()
    print(cfg.tasks_queued)

    # Load from a TOML file
    cfg = Config.from_toml(Path("agent-os.toml"))

    # Override for testing
    configure(Config(company_root=Path("/tmp/test-company")))

Backward compatibility:
    # Still works — shim delegates to get_config()
    from agent_os.config import COMPANY_ROOT, TASKS_QUEUED
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    """Immutable agent-os configuration.

    All paths are derived from company_root. Budget/turn limits and model
    settings are configurable per invocation mode.
    """

    # Root of the agent-os filesystem
    company_root: Path = field(default_factory=lambda: Path(os.environ.get("AGENT_OS_ROOT", os.environ.get("AIOS_COMPANY_ROOT", "."))))

    # Company name (used in generic templates)
    company_name: str = "My Company"

    def __post_init__(self):
        # Coerce company_root to Path if a string was passed
        if isinstance(self.company_root, str):
            object.__setattr__(self, "company_root", Path(self.company_root))

    # Model defaults
    default_model: str = "claude-opus-4-6"
    agent_model_overrides: dict[str, str] = field(default_factory=dict)

    # Roles subject to quality gates
    builder_roles: frozenset[str] = frozenset({"Software Engineer"})

    # --- Company override layer ---

    # Role-to-tools mapping (overrides DEFAULT_ROLE_TOOLS in registry.py)
    role_tools: dict[str, list[str]] = field(default_factory=dict)

    # Feedback/system-notes routing: {"catch_all": "agent-id", "tags": {"tag": ["agent-id", ...]}}
    feedback_routing: dict = field(default_factory=dict)

    # Directory for company-specific template overrides (searched before package defaults)
    prompts_override_dir: Path | None = None

    # --- Budget & turn limits ---

    # Standard task invocation
    max_budget_per_invocation_usd: float = 5.00
    max_turns_per_invocation: int = 50

    # Standing orders (health scan, reflection)
    standing_orders_max_budget_usd: float = 2.00
    standing_orders_max_turns: int = 40

    # Drive consultation
    drive_consultation_max_budget_usd: float = 1.50
    drive_consultation_max_turns: int = 30

    # Thread responses
    thread_response_max_budget_usd: float = 1.00
    thread_response_max_turns: int = 15

    # Message triage
    message_triage_model: str = "claude-sonnet-4-6"
    message_triage_max_budget_usd: float = 0.75
    message_triage_max_turns: int = 15

    # Dream cycle
    dream_model: str = "claude-sonnet-4-6"
    dream_max_budget_usd: float = 1.50
    dream_max_turns: int = 25

    # Interactive conversation
    interactive_max_budget_usd: float = 2.00
    interactive_max_turns: int = 30

    # --- Factory from TOML ---

    @classmethod
    def from_toml(cls, path: Path) -> Config:
        """Create a Config from an agent-os.toml file.

        The TOML file can override any Config field. Sections map to fields:
          [company] name, root
          [runtime] model, builder_roles
          [budget]  task, standing_orders, drive_consultation, ...
          [roles]   "Role Name" = ["Tool1", "Tool2"]
          [prompts] override_dir
          [feedback_routing] catch_all, tags.*
        """
        with open(path, "rb") as f:
            data = tomllib.load(f)

        kwargs: dict = {}
        toml_dir = path.parent.resolve()

        # [company]
        company = data.get("company", {})
        if "name" in company:
            kwargs["company_name"] = company["name"]
        if "root" in company:
            root = Path(company["root"])
            kwargs["company_root"] = root if root.is_absolute() else toml_dir / root

        # [runtime]
        runtime = data.get("runtime", {})
        if "model" in runtime:
            kwargs["default_model"] = runtime["model"]
        if "builder_roles" in runtime:
            kwargs["builder_roles"] = frozenset(runtime["builder_roles"])

        # [budget]
        budget = data.get("budget", {})
        budget_map = {
            "task": "max_budget_per_invocation_usd",
            "standing_orders": "standing_orders_max_budget_usd",
            "drive_consultation": "drive_consultation_max_budget_usd",
            "thread_response": "thread_response_max_budget_usd",
            "message_triage": "message_triage_max_budget_usd",
            "dream": "dream_max_budget_usd",
            "interactive": "interactive_max_budget_usd",
        }
        for toml_key, field_name in budget_map.items():
            if toml_key in budget:
                kwargs[field_name] = float(budget[toml_key])

        # [roles]
        roles = data.get("roles", {})
        if roles:
            kwargs["role_tools"] = dict(roles)

        # [prompts]
        prompts = data.get("prompts", {})
        if "override_dir" in prompts:
            override = Path(prompts["override_dir"])
            kwargs["prompts_override_dir"] = override if override.is_absolute() else toml_dir / override

        # [feedback_routing]
        fr = data.get("feedback_routing", {})
        if fr:
            kwargs["feedback_routing"] = dict(fr)

        return cls(**kwargs)

    @classmethod
    def discover_toml(cls, start: Path | None = None) -> Path | None:
        """Find agent-os.toml by walking up from start directory.

        Discovery order: AGENT_OS_CONFIG env var > walk up from start.
        """
        env_path = os.environ.get("AGENT_OS_CONFIG")
        if env_path:
            p = Path(env_path)
            if p.is_file():
                return p
            return None

        current = (start or Path.cwd()).resolve()
        while True:
            candidate = current / "agent-os.toml"
            if candidate.is_file():
                return candidate
            parent = current.parent
            if parent == current:
                break
            current = parent
        return None

    # --- Derived path properties ---

    @property
    def agents_dir(self) -> Path:
        return self.company_root / "agents"

    @property
    def registry_dir(self) -> Path:
        return self.agents_dir / "registry"

    @property
    def tasks_dir(self) -> Path:
        return self.agents_dir / "tasks"

    @property
    def messages_dir(self) -> Path:
        return self.agents_dir / "messages"

    @property
    def logs_dir(self) -> Path:
        return self.agents_dir / "logs"

    @property
    def costs_dir(self) -> Path:
        return self.company_root / "finance" / "costs"

    # Task lifecycle directories
    @property
    def tasks_queued(self) -> Path:
        return self.tasks_dir / "queued"

    @property
    def tasks_in_progress(self) -> Path:
        return self.tasks_dir / "in-progress"

    @property
    def tasks_in_review(self) -> Path:
        return self.tasks_dir / "in-review"

    @property
    def tasks_done(self) -> Path:
        return self.tasks_dir / "done"

    @property
    def tasks_failed(self) -> Path:
        return self.tasks_dir / "failed"

    @property
    def tasks_declined(self) -> Path:
        return self.tasks_dir / "declined"

    # Agent state
    @property
    def agents_state_dir(self) -> Path:
        return self.agents_dir / "state"

    # Proposals
    @property
    def proposals_active(self) -> Path:
        return self.company_root / "strategy" / "proposals" / "active"

    @property
    def proposals_decided(self) -> Path:
        return self.company_root / "strategy" / "proposals" / "decided"

    # Company drives
    @property
    def drives_file(self) -> Path:
        return self.company_root / "strategy" / "drives.md"

    # Company values
    @property
    def values_file(self) -> Path:
        return self.company_root / "identity" / "values.md"

    # Broadcast channel
    @property
    def broadcast_dir(self) -> Path:
        return self.messages_dir / "broadcast"

    # Conversation threads
    @property
    def threads_dir(self) -> Path:
        return self.messages_dir / "threads"

    # Feedback / system notes
    @property
    def feedback_dir(self) -> Path:
        return self.messages_dir / "feedback"

    # Quality gate script
    @property
    def pre_done_checks_script(self) -> Path:
        return self.company_root / "operations" / "scripts" / "pre-done-checks.sh"


# --- Singleton ---

_config: Config | None = None


def get_config() -> Config:
    """Return the global Config singleton, creating it on first access."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def configure(config: Config) -> None:
    """Replace the global Config singleton. Typically used in tests."""
    global _config
    _config = config


# --- Backward compatibility shim ---
#
# Existing code does `from agent_os.config import COMPANY_ROOT` etc.
# This __getattr__ maps old UPPER_CASE names to Config properties/fields
# so all imports keep working without touching any other file.

_COMPAT_MAP: dict[str, str] = {
    # Paths (direct fields or properties on Config)
    "COMPANY_ROOT": "company_root",
    "AGENTS_DIR": "agents_dir",
    "REGISTRY_DIR": "registry_dir",
    "TASKS_DIR": "tasks_dir",
    "MESSAGES_DIR": "messages_dir",
    "LOGS_DIR": "logs_dir",
    "COSTS_DIR": "costs_dir",
    "TASKS_QUEUED": "tasks_queued",
    "TASKS_IN_PROGRESS": "tasks_in_progress",
    "TASKS_IN_REVIEW": "tasks_in_review",
    "TASKS_DONE": "tasks_done",
    "TASKS_FAILED": "tasks_failed",
    "TASKS_DECLINED": "tasks_declined",
    "AGENTS_STATE_DIR": "agents_state_dir",
    "PROPOSALS_ACTIVE": "proposals_active",
    "PROPOSALS_DECIDED": "proposals_decided",
    "DRIVES_FILE": "drives_file",
    "VALUES_FILE": "values_file",
    "BROADCAST_DIR": "broadcast_dir",
    "THREADS_DIR": "threads_dir",
    "FEEDBACK_DIR": "feedback_dir",
    # Model defaults
    "DEFAULT_MODEL": "default_model",
    "AGENT_MODEL_OVERRIDES": "agent_model_overrides",
    # Budget & turn limits
    "MAX_BUDGET_PER_INVOCATION_USD": "max_budget_per_invocation_usd",
    "MAX_TURNS_PER_INVOCATION": "max_turns_per_invocation",
    "STANDING_ORDERS_MAX_BUDGET_USD": "standing_orders_max_budget_usd",
    "STANDING_ORDERS_MAX_TURNS": "standing_orders_max_turns",
    "DRIVE_CONSULTATION_MAX_BUDGET_USD": "drive_consultation_max_budget_usd",
    "DRIVE_CONSULTATION_MAX_TURNS": "drive_consultation_max_turns",
    "THREAD_RESPONSE_MAX_BUDGET_USD": "thread_response_max_budget_usd",
    "THREAD_RESPONSE_MAX_TURNS": "thread_response_max_turns",
    "MESSAGE_TRIAGE_MODEL": "message_triage_model",
    "MESSAGE_TRIAGE_MAX_BUDGET_USD": "message_triage_max_budget_usd",
    "MESSAGE_TRIAGE_MAX_TURNS": "message_triage_max_turns",
    "DREAM_MODEL": "dream_model",
    "DREAM_MAX_BUDGET_USD": "dream_max_budget_usd",
    "DREAM_MAX_TURNS": "dream_max_turns",
    "INTERACTIVE_MAX_BUDGET_USD": "interactive_max_budget_usd",
    "INTERACTIVE_MAX_TURNS": "interactive_max_turns",
}


def __getattr__(name: str):
    """Module-level __getattr__ for backward-compatible constant access.

    Maps old UPPER_CASE names (e.g., COMPANY_ROOT) to Config properties,
    so `from agent_os.config import COMPANY_ROOT` keeps working.
    """
    attr = _COMPAT_MAP.get(name)
    if attr is not None:
        return getattr(get_config(), attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
