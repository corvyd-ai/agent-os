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
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Config:
    """Immutable agent-os configuration.

    All paths are derived from company_root. Budget/turn limits and model
    settings are configurable per invocation mode.
    """

    # Root of the agent-os filesystem
    company_root: Path = field(
        default_factory=lambda: Path(os.environ.get("AGENT_OS_ROOT", os.environ.get("AIOS_COMPANY_ROOT", ".")))
    )

    # Company name (used in generic templates)
    company_name: str = "My Company"

    # Timezone for all scheduling, logging, and day boundaries (IANA name)
    timezone: str = "UTC"

    def __post_init__(self):
        # Coerce company_root to Path if a string was passed
        if isinstance(self.company_root, str):
            object.__setattr__(self, "company_root", Path(self.company_root))

    @property
    def tz(self) -> ZoneInfo:
        """Return the configured timezone as a ZoneInfo object."""
        return ZoneInfo(self.timezone)

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

    # Dashboard settings
    dashboard_agent_ids: list[str] = field(default_factory=list)
    conversations_dir: Path | None = None

    # --- Logging ---
    log_level: str = "info"  # debug, info, warn, error
    log_also_print: bool = True  # also print to stdout (for cron log capture)
    log_retention_days: int = 30  # days to keep JSONL log files before archival

    # --- Aggregate budget caps (circuit breaker) ---
    daily_budget_cap_usd: float = 100.00
    weekly_budget_cap_usd: float = 500.00
    monthly_budget_cap_usd: float = 2000.00
    agent_daily_caps: dict[str, float] = field(default_factory=dict)

    # --- Autonomy model ---
    autonomy_default: str = "medium"
    autonomy_agents: dict[str, str] = field(default_factory=dict)

    # --- Schedule config ---
    schedule_enabled: bool = True
    schedule_operating_hours: str = ""  # e.g. "07:00-23:00" in configured timezone, empty = 24/7
    schedule_cycles_enabled: bool = True
    schedule_cycles_interval_minutes: int = 15
    schedule_cycles_agents: list[str] = field(default_factory=lambda: ["all"])
    schedule_standing_orders_enabled: bool = True
    schedule_standing_orders_interval_minutes: int = 60
    schedule_drives_enabled: bool = True
    schedule_drives_weekday_times: list[str] = field(default_factory=lambda: ["17:00"])
    schedule_drives_weekend_times: list[str] = field(default_factory=lambda: ["13:00"])
    schedule_drives_stagger_minutes: int = 10
    schedule_dreams_enabled: bool = True
    schedule_dreams_time: str = "02:00"
    schedule_dreams_stagger_minutes: int = 10
    # Maintenance sub-schedules
    schedule_archive_enabled: bool = True
    schedule_archive_time: str = "03:00"
    schedule_manifest_enabled: bool = True
    schedule_manifest_interval_minutes: int = 120
    schedule_watchdog_enabled: bool = True
    schedule_watchdog_interval_minutes: int = 15
    schedule_watchdog_alert_threshold_minutes: int = 45
    schedule_watchdog_alert_hook: str = ""

    # Digest
    schedule_digest_enabled: bool = True
    schedule_digest_time: str = "08:00"

    # --- Notifications ---
    notifications_enabled: bool = True
    notifications_desktop: bool = False  # opt-in (noisy if unintended)
    notifications_webhook_url: str = ""  # empty = disabled
    notifications_script: str = ""  # path to notification script
    notifications_file: bool = True  # always-on file-drop (default)
    notifications_min_severity: str = "warning"  # info, warning, critical
    # Per-event-type min-severity overrides. Keys are event_type strings
    # (see notifications.KNOWN_EVENT_TYPES). Values override the global
    # min_severity for that event_type only.
    notifications_event_overrides: dict[str, str] = field(default_factory=dict)

    # --- Failure circuit breaker ---
    circuit_breaker_enabled: bool = True
    circuit_breaker_max_failures: int = 5
    circuit_breaker_cooldown_minutes: int = 60

    # --- Runtime user (for systemd/service deployments) ---
    # Username the scheduler runs as (e.g., "corvyd"). When set, tools like
    # `agent-os doctor` compare file ownership against this user instead of
    # the invoking user — useful when a human SSHes in as root to diagnose
    # a service that actually runs as a different account.
    # Empty = use the invoking user (the traditional default).
    runtime_user: str = ""

    # Path to an env file (e.g., systemd EnvironmentFile). Read by doctor to
    # verify secrets like ANTHROPIC_API_KEY are configured even when the
    # invoking shell doesn't have them loaded. Empty = only check os.environ.
    runtime_env_file: str = ""

    # --- Project (SDLC) ---
    project_repo_path: str = "."  # relative to company_root, or absolute
    project_default_branch: str = "main"
    project_push: bool = True
    project_remote: str = "origin"
    project_code_dir: str = "."  # working dir within repo for agents
    project_worktrees_dir: str = ".worktrees"  # where worktrees are created
    project_setup_commands: list[str] = field(default_factory=list)
    project_setup_timeout: int = 300
    project_validate_commands: list[str] = field(default_factory=list)
    project_validate_timeout: int = 600
    project_validate_on_failure: str = "retry"  # "fail" or "retry"
    project_validate_max_retries: int = 2

    # Commit identity — injected inline (`git -c user.email=... commit ...`) so
    # workspace commits succeed on runtimes where `git config --global
    # user.email` was never set. Empty strings mean "fall through to whatever
    # the runtime's git config happens to provide" (legacy behavior).
    # Per-agent override lets commit history distinguish work by specific
    # agents: {"agent-001-maker": {"email": "...", "name": "..."}}.
    project_commit_author_email: str = ""
    project_commit_author_name: str = ""
    project_agent_commit_authors: dict[str, dict[str, str]] = field(default_factory=dict)

    # Worktree archive — on cleanup we move the worktree to
    # {worktrees_root}/_archive/{task-id}__{status}__{timestamp}/ instead of
    # deleting. Keeps last N; older are pruned. Gives humans forensic material
    # after a failure and lets agents inspect prior attempts.
    project_archive_enabled: bool = True
    project_archive_keep_last: int = 10

    # --- Budget & turn limits (per-invocation) ---

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
        if "timezone" in company:
            kwargs["timezone"] = company["timezone"]
        if "root" in company:
            root = Path(company["root"])
            kwargs["company_root"] = root if root.is_absolute() else toml_dir / root

        # [runtime]
        runtime = data.get("runtime", {})
        if "model" in runtime:
            kwargs["default_model"] = runtime["model"]
        if "builder_roles" in runtime:
            kwargs["builder_roles"] = frozenset(runtime["builder_roles"])

        # [budget] — per-invocation limits
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

        # [budget] — aggregate caps (circuit breaker)
        if "daily_cap" in budget:
            kwargs["daily_budget_cap_usd"] = float(budget["daily_cap"])
        if "weekly_cap" in budget:
            kwargs["weekly_budget_cap_usd"] = float(budget["weekly_cap"])
        if "monthly_cap" in budget:
            kwargs["monthly_budget_cap_usd"] = float(budget["monthly_cap"])
        agent_caps = budget.get("agent_daily_caps", {})
        if agent_caps:
            kwargs["agent_daily_caps"] = {k: float(v) for k, v in agent_caps.items()}

        # [autonomy]
        autonomy = data.get("autonomy", {})
        if "default_level" in autonomy:
            kwargs["autonomy_default"] = autonomy["default_level"]
        agent_autonomy = autonomy.get("agents", {})
        if agent_autonomy:
            kwargs["autonomy_agents"] = dict(agent_autonomy)

        # [schedule]
        schedule = data.get("schedule", {})
        if "enabled" in schedule:
            kwargs["schedule_enabled"] = bool(schedule["enabled"])
        if "operating_hours" in schedule:
            kwargs["schedule_operating_hours"] = schedule["operating_hours"]

        # [schedule.cycles]
        cycles = schedule.get("cycles", {})
        if "enabled" in cycles:
            kwargs["schedule_cycles_enabled"] = bool(cycles["enabled"])
        if "interval_minutes" in cycles:
            kwargs["schedule_cycles_interval_minutes"] = int(cycles["interval_minutes"])
        if "agents" in cycles:
            kwargs["schedule_cycles_agents"] = list(cycles["agents"])

        # [schedule.standing_orders]
        so = schedule.get("standing_orders", {})
        if "enabled" in so:
            kwargs["schedule_standing_orders_enabled"] = bool(so["enabled"])
        if "interval_minutes" in so:
            kwargs["schedule_standing_orders_interval_minutes"] = int(so["interval_minutes"])

        # [schedule.drives]
        drives = schedule.get("drives", {})
        if "enabled" in drives:
            kwargs["schedule_drives_enabled"] = bool(drives["enabled"])
        if "weekday_times" in drives:
            kwargs["schedule_drives_weekday_times"] = list(drives["weekday_times"])
        if "weekend_times" in drives:
            kwargs["schedule_drives_weekend_times"] = list(drives["weekend_times"])
        if "stagger_minutes" in drives:
            kwargs["schedule_drives_stagger_minutes"] = int(drives["stagger_minutes"])

        # [schedule.dreams]
        dreams = schedule.get("dreams", {})
        if "enabled" in dreams:
            kwargs["schedule_dreams_enabled"] = bool(dreams["enabled"])
        if "time" in dreams:
            kwargs["schedule_dreams_time"] = dreams["time"]
        if "stagger_minutes" in dreams:
            kwargs["schedule_dreams_stagger_minutes"] = int(dreams["stagger_minutes"])

        # [schedule.maintenance]
        maint = schedule.get("maintenance", {})
        archive = maint.get("archive", {})
        if "enabled" in archive:
            kwargs["schedule_archive_enabled"] = bool(archive["enabled"])
        if "time" in archive:
            kwargs["schedule_archive_time"] = archive["time"]
        manifest = maint.get("manifest", {})
        if "enabled" in manifest:
            kwargs["schedule_manifest_enabled"] = bool(manifest["enabled"])
        if "interval_minutes" in manifest:
            kwargs["schedule_manifest_interval_minutes"] = int(manifest["interval_minutes"])
        watchdog = maint.get("watchdog", {})
        if "enabled" in watchdog:
            kwargs["schedule_watchdog_enabled"] = bool(watchdog["enabled"])
        if "interval_minutes" in watchdog:
            kwargs["schedule_watchdog_interval_minutes"] = int(watchdog["interval_minutes"])
        if "alert_threshold_minutes" in watchdog:
            kwargs["schedule_watchdog_alert_threshold_minutes"] = int(watchdog["alert_threshold_minutes"])
        if "alert_hook" in watchdog:
            kwargs["schedule_watchdog_alert_hook"] = watchdog["alert_hook"]
        digest = maint.get("digest", {})
        if "enabled" in digest:
            kwargs["schedule_digest_enabled"] = bool(digest["enabled"])
        if "time" in digest:
            kwargs["schedule_digest_time"] = digest["time"]

        # [notifications]
        notif = data.get("notifications", {})
        if "enabled" in notif:
            kwargs["notifications_enabled"] = bool(notif["enabled"])
        if "desktop" in notif:
            kwargs["notifications_desktop"] = bool(notif["desktop"])
        if "webhook_url" in notif:
            kwargs["notifications_webhook_url"] = notif["webhook_url"]
        if "script" in notif:
            kwargs["notifications_script"] = notif["script"]
        if "file" in notif:
            kwargs["notifications_file"] = bool(notif["file"])
        if "min_severity" in notif:
            kwargs["notifications_min_severity"] = notif["min_severity"]
        # [notifications.events] — per-event-type min_severity overrides
        events_overrides = notif.get("events", {})
        if isinstance(events_overrides, dict) and events_overrides:
            kwargs["notifications_event_overrides"] = {str(k): str(v) for k, v in events_overrides.items()}

        # [circuit_breaker]
        cb = data.get("circuit_breaker", {})
        if "enabled" in cb:
            kwargs["circuit_breaker_enabled"] = bool(cb["enabled"])
        if "max_failures" in cb:
            kwargs["circuit_breaker_max_failures"] = int(cb["max_failures"])
        if "cooldown_minutes" in cb:
            kwargs["circuit_breaker_cooldown_minutes"] = int(cb["cooldown_minutes"])

        # [runtime]  (user/env_file — keep alongside existing [runtime] keys)
        if "user" in runtime:
            kwargs["runtime_user"] = runtime["user"]
        if "env_file" in runtime:
            kwargs["runtime_env_file"] = runtime["env_file"]

        # [roles]
        roles = data.get("roles", {})
        if roles:
            kwargs["role_tools"] = dict(roles)

        # [prompts]
        prompts = data.get("prompts", {})
        if "override_dir" in prompts:
            override = Path(prompts["override_dir"])
            kwargs["prompts_override_dir"] = override if override.is_absolute() else toml_dir / override

        # [dashboard]
        dashboard = data.get("dashboard", {})
        if "agent_ids" in dashboard:
            kwargs["dashboard_agent_ids"] = list(dashboard["agent_ids"])
        if "conversations_dir" in dashboard:
            conv_dir = Path(dashboard["conversations_dir"])
            kwargs["conversations_dir"] = conv_dir if conv_dir.is_absolute() else toml_dir / conv_dir

        # [logging]
        logging_cfg = data.get("logging", {})
        if "level" in logging_cfg:
            kwargs["log_level"] = logging_cfg["level"]
        if "also_print" in logging_cfg:
            kwargs["log_also_print"] = bool(logging_cfg["also_print"])
        if "retention_days" in logging_cfg:
            kwargs["log_retention_days"] = int(logging_cfg["retention_days"])

        # [feedback_routing]
        fr = data.get("feedback_routing", {})
        if fr:
            kwargs["feedback_routing"] = dict(fr)

        # [project]
        project = data.get("project", {})
        if "repo_path" in project:
            kwargs["project_repo_path"] = project["repo_path"]
        if "default_branch" in project:
            kwargs["project_default_branch"] = project["default_branch"]
        if "push" in project:
            kwargs["project_push"] = bool(project["push"])
        if "remote" in project:
            kwargs["project_remote"] = project["remote"]
        if "code_dir" in project:
            kwargs["project_code_dir"] = project["code_dir"]
        if "worktrees_dir" in project:
            kwargs["project_worktrees_dir"] = project["worktrees_dir"]

        # [project.setup]
        setup = project.get("setup", {})
        if "commands" in setup:
            kwargs["project_setup_commands"] = list(setup["commands"])
        if "timeout" in setup:
            kwargs["project_setup_timeout"] = int(setup["timeout"])

        # [project.validate]
        validate = project.get("validate", {})
        if "commands" in validate:
            kwargs["project_validate_commands"] = list(validate["commands"])
        if "timeout" in validate:
            kwargs["project_validate_timeout"] = int(validate["timeout"])
        if "on_failure" in validate:
            kwargs["project_validate_on_failure"] = validate["on_failure"]
        if "max_retries" in validate:
            kwargs["project_validate_max_retries"] = int(validate["max_retries"])

        # [project.commit]
        commit = project.get("commit", {})
        if "author_email" in commit:
            kwargs["project_commit_author_email"] = str(commit["author_email"])
        if "author_name" in commit:
            kwargs["project_commit_author_name"] = str(commit["author_name"])
        agent_authors = commit.get("agent_authors", {})
        if agent_authors:
            kwargs["project_agent_commit_authors"] = {agent_id: dict(v) for agent_id, v in agent_authors.items()}

        # [project.archive]
        archive_cfg = project.get("archive", {})
        if "enabled" in archive_cfg:
            kwargs["project_archive_enabled"] = bool(archive_cfg["enabled"])
        if "keep_last" in archive_cfg:
            kwargs["project_archive_keep_last"] = int(archive_cfg["keep_last"])

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

    @property
    def tasks_backlog(self) -> Path:
        return self.tasks_dir / "backlog"

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

    # Operations
    @property
    def operations_dir(self) -> Path:
        return self.company_root / "operations"

    @property
    def scheduler_state_file(self) -> Path:
        return self.operations_dir / "scheduler-state.json"

    # Strategy
    @property
    def strategy_dir(self) -> Path:
        return self.company_root / "strategy"

    @property
    def decisions_dir(self) -> Path:
        return self.strategy_dir / "decisions"

    # Human inbox
    @property
    def human_inbox(self) -> Path:
        return self.messages_dir / "human" / "inbox"

    # Dashboard conversations
    @property
    def conversations_dir_resolved(self) -> Path:
        return self.conversations_dir or (self.company_root / "agents" / "conversations")

    # Quality gate script
    @property
    def pre_done_checks_script(self) -> Path:
        return self.operations_dir / "scripts" / "pre-done-checks.sh"

    # Project (SDLC) derived paths
    @property
    def project_enabled(self) -> bool:
        """True if [project] section was configured with actionable commands."""
        return bool(self.project_validate_commands or self.project_setup_commands)

    @property
    def repo_root(self) -> Path:
        """Absolute path to the git repository root."""
        p = Path(self.project_repo_path)
        return p if p.is_absolute() else self.company_root / p

    @property
    def worktrees_root(self) -> Path:
        """Absolute path to the worktrees directory."""
        p = Path(self.project_worktrees_dir)
        return p if p.is_absolute() else self.company_root / p

    @property
    def worktrees_archive_root(self) -> Path:
        """Absolute path to the worktree archive directory.

        Preserved worktrees from completed/failed/salvaged tasks land here
        so the active worktree path is never blocked by leftover state.
        """
        return self.worktrees_root / "_archive"


# --- Singleton ---

_config: Config | None = None


def get_config() -> Config:
    """Return the global Config singleton, creating it on first access.

    On first creation, attempts to discover and load an ``agent-os.toml``
    using the same rules as the CLI (``AGENT_OS_CONFIG`` env var, then
    walking up from cwd). If found, the Config is built from the TOML so
    programmatic callers see the same ``company_root`` and other settings
    the CLI does — without that, a caller running from any cwd would land
    a default Config with ``company_root="."`` and quietly write to the
    wrong tree.

    Falls back to a default ``Config()`` when no TOML is discovered. To
    bypass discovery entirely (e.g. in tests), call ``configure(Config())``
    before the first ``get_config()`` call.
    """
    global _config
    if _config is None:
        toml_path = Config.discover_toml()
        if toml_path is not None:
            _config = Config.from_toml(toml_path)
        else:
            _config = Config()
    return _config


def configure(config: Config) -> None:
    """Replace the global Config singleton. Typically used in tests."""
    global _config
    _config = config


def load_dotenv(root: Path) -> None:
    """Load a .env file from the project root into os.environ.

    Only sets variables that are not already in the environment (env vars
    take precedence over .env values). Supports KEY=VALUE lines, quoted
    values, comments, and blank lines. No external dependencies.
    """
    env_file = root / ".env"
    if not env_file.exists():
        return

    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip matching quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        # Don't override existing env vars
        if key not in os.environ:
            os.environ[key] = value


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
    "TASKS_BACKLOG": "tasks_backlog",
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
