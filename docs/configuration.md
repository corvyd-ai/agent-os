# Configuration

agent-os is configured through a single `Config` dataclass, typically loaded from `agent-os.toml`. All paths are derived from one root directory. All budgets have sensible defaults.

## Basic Usage

Most deployments use TOML:

```toml
# agent-os.toml
[company]
name = "My Company"
timezone = "UTC"

[runtime]
model = "claude-sonnet-4-6"
```

And point agent-os at the config:

```bash
agent-os --config ./agent-os.toml status
# or via env
AGENT_OS_CONFIG=/srv/my-company/agent-os.toml agent-os status
```

Programmatic use:

```python
from agent_os import Config, configure
from pathlib import Path

config = Config(
    company_root=Path("./my-company"),
    default_model="claude-sonnet-4-6",
    max_budget_per_invocation_usd=5.00,
)
configure(config)
```

## Config Discovery

agent-os looks for `agent-os.toml` in this order:

1. `--config` CLI flag
2. `AGENT_OS_CONFIG` env var
3. Walks up from `AGENT_OS_ROOT` looking for `agent-os.toml`
4. Walks up from the current working directory

## Core Settings

### `[company]`

| Key | Default | Description |
|-----|---------|-------------|
| `name` | `"My Company"` | Company name (used in prompts) |
| `root` | cwd | Company root directory (relative paths resolve against the TOML file) |
| `timezone` | `"UTC"` | IANA timezone for scheduling, logging, day boundaries |

### `[runtime]`

| Key | Default | Description |
|-----|---------|-------------|
| `model` | `"claude-opus-4-6"` | Default model for agent invocations |
| `user` | `""` | Service account the scheduler runs as (e.g., `"corvyd"`). Used by `agent-os doctor` to compare file ownership against the correct account. Leave empty on single-user setups. |
| `env_file` | `""` | Path to an env file (e.g., a systemd `EnvironmentFile`). Read by doctor to verify secrets like `ANTHROPIC_API_KEY` are present, even when the invoking shell doesn't have them loaded. |
| `builder_roles` | `["Software Engineer"]` | Roles that get the workspace SDLC + quality gates |

Per-agent model overrides:

```toml
[runtime]
model = "claude-sonnet-4-6"
agent_model_overrides = { "agent-001-builder" = "claude-opus-4-6" }
```

## Budget & Turn Limits

Each invocation mode has independent caps:

```toml
[budget]
task = 5.00              # max_budget_per_invocation_usd
standing_orders = 2.00
drive_consultation = 1.50
dream = 1.50
thread_response = 1.00
message_triage = 0.75
interactive = 2.00

daily_cap = 100.00       # aggregate daily budget circuit breaker
weekly_cap = 500.00
monthly_cap = 2000.00

[budget.agent_daily_caps]
"agent-003-operator" = 50.00
```

Override per-invocation via CLI:

```bash
agent-os cycle agent-001 --max-budget 3.00 --max-turns 30
```

When a cap trips, the budget circuit breaker stops all agent invocations. `agent-os status` surfaces tripped breakers.

## Scheduling

```toml
[schedule]
enabled = true
operating_hours = "07:00-23:00"   # empty = 24/7 (tz follows [company].timezone)

[schedule.cycles]
enabled = true
interval_minutes = 15
agents = ["all"]

[schedule.standing_orders]
enabled = true
interval_minutes = 60

[schedule.drives]
enabled = true
weekday_times = ["17:00"]
weekend_times = ["13:00"]

[schedule.dreams]
enabled = true
time = "02:00"
stagger_minutes = 10

[schedule.maintenance.archive]
enabled = true
time = "03:00"

[schedule.maintenance.manifest]
enabled = true
interval_minutes = 120

[schedule.maintenance.watchdog]
enabled = true
interval_minutes = 15
alert_threshold_minutes = 45
alert_hook = ""              # optional legacy shell hook

[schedule.maintenance.digest]
enabled = true
time = "08:00"
```

Install the scheduler tick as a crontab entry (`agent-os cron install`) or configure a systemd timer that runs `agent-os tick` every minute. `agent-os doctor` detects both.

## The Workspace SDLC (Code Tasks)

When a `[project]` section is configured and an agent's role is in `builder_roles`, agent-os runs an **automated software development lifecycle** — agents never interact with git directly, agent-os handles it as infrastructure.

```toml
[project]
repo_path = "."              # relative to company_root, or absolute
default_branch = "main"
push = true                  # false = commit locally only
remote = "origin"
code_dir = "."               # working dir within repo for agents
worktrees_dir = ".worktrees" # where isolated worktrees are created

[project.setup]
commands = ["npm install"]
timeout = 300

[project.validate]
commands = ["pytest", "ruff check ."]
timeout = 600
on_failure = "retry"         # "retry" | "fail"
max_retries = 2
```

### Flow when a builder agent claims a task

1. `git worktree add` creates an isolated branch `agent/{task-id}` from the default branch
2. `[project.setup].commands` run in the worktree
3. The agent works with `cwd` set to the worktree; its file tools operate on isolated code
4. `[project.validate].commands` run as the final gate
5. If validation fails and `on_failure = "retry"`, the agent gets another chance with the error output
6. `git add -A && git commit` with an auto-generated message, then `git push` to remote
7. Task moves to `done/`, worktree is removed

Branch naming is deterministic (`agent/{task-id}`). Push failures are non-fatal — work is committed locally either way. Agents without `[project]` configured work directly in `company_root` with no git lifecycle.

## Observability

agent-os ships an observability layer by default. All sub-features can be disabled individually.

### Notifications

```toml
[notifications]
enabled = true
file = true                  # always-on file-drop to operations/notifications/
desktop = false              # notify-send (Linux) / osascript (macOS)
webhook_url = ""             # Slack/Discord/ntfy.sh — curl POST
script = ""                  # path to a user-provided hook script
min_severity = "warning"     # info | warning | critical
```

Events include: pre-flight failures, circuit breaker trips, watchdog alerts, daily digest, budget warnings.

### Failure Circuit Breaker

Parallel to the budget circuit breaker, but for repeated task failures. Counts consecutive error-level entries in the agent's JSONL log. After N failures, trips and blocks dispatch for that agent until cooldown elapses and a pre-flight probe passes.

```toml
[circuit_breaker]
enabled = true
max_failures = 5
cooldown_minutes = 60
```

### Pre-flight Gate

Runs before every cycle. Tests whether the agent can actually write to its task/log/message directories via create-and-delete probes. If any probe fails, the cycle is blocked and a critical notification is sent — preventing silent failure loops. No config — it's always on when the agent runs.

### `agent-os doctor`

On-demand diagnostic: directory structure, file ownership (vs `[runtime] user`), write probes, config validation, registry consistency, stuck tasks, circuit breakers, API key (checks `os.environ`, `[runtime] env_file`, and `.env`), scheduler installation (crontab or systemd timers), log health.

```bash
agent-os doctor                          # standard run
agent-os doctor --verbose                # show passing checks too
agent-os doctor --runtime-user corvyd    # override [runtime] user
```

### Daily Digest

`agent-os digest` or scheduled at `[schedule.maintenance.digest].time`. Produces a summary of tasks, agent health, budget burn, and anomalies. Written to `operations/digests/YYYY-MM-DD.md` and delivered via the notification system.

## Logging

```toml
[logging]
level = "info"              # debug | info | warn | error
also_print = true           # also print to stdout (for cron log capture)
retention_days = 30         # days to keep JSONL log files before archival
```

Logs are JSONL at `agents/logs/{agent_id}/YYYY-MM-DD.jsonl`. System-level events go to `agents/logs/system/`.

## Autonomy

```toml
[autonomy]
default_level = "medium"     # low | medium | high
[autonomy.agents]
"agent-001-builder" = "high"
```

- **low** — agent cannot create tasks
- **medium** — tasks go to `backlog/` (human must promote with `agent-os backlog promote`)
- **high** — tasks go directly to `queued/`

## Prompts

```toml
[prompts]
override_dir = "prompts"     # relative to agent-os.toml location
```

Files in this directory shadow the default Jinja2 templates. Useful for customizing the preamble, workspace gates, or drive consultation prompt without forking agent-os.

## Feedback Routing

Route human-operator notes to specific agents:

```toml
[feedback_routing]
catch_all = "agent-000-chief-of-staff"
[feedback_routing.tags]
infrastructure = ["agent-003-operator"]
product = ["agent-001-builder", "agent-002-designer"]
```

## Roles

Override the default role-to-tools mapping:

```toml
[roles]
"Software Engineer" = ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
"Researcher" = ["Read", "WebSearch"]
```

## Dashboard

```toml
[dashboard]
agent_ids = []               # empty = all agents
conversations_dir = "agents/conversations"
```

## Derived Paths

All directory paths are computed from `company_root`. You never configure paths individually:

- `agents/registry/` — agent definitions
- `agents/state/{agent-id}/` — soul, working memory, circuit breaker state
- `agents/tasks/{queued,in-progress,in-review,done,failed,backlog,declined}/`
- `agents/messages/{broadcast,threads,<agent-id>/inbox,human/inbox}/`
- `agents/logs/` — JSONL activity logs
- `strategy/{drives.md,current-focus.md,decisions/,proposals/{active,decided}/}`
- `identity/{values.md,principles.md}`
- `finance/costs/` — cost ledger JSONL
- `knowledge/` — shared knowledge base
- `knowledge/technical/` — platform reference + changelog (auto-regenerated on `agent-os update`)
- `operations/{scripts,notifications,digests}/`
- `.worktrees/` — ephemeral git worktrees (gitignored)

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `AGENT_OS_ROOT` | Default company root directory |
| `AGENT_OS_CONFIG` | Path to `agent-os.toml` (overrides root-walking discovery) |
| `AIOS_COMPANY_ROOT` | Legacy alias for `AGENT_OS_ROOT` |
| `ANTHROPIC_API_KEY` | API key for Claude invocations |

## Full Schema

The canonical source is the `Config` dataclass in `src/agent_os/config.py`. Every field documented there is settable via TOML under the section implied by its prefix (e.g., `notifications_webhook_url` → `[notifications].webhook_url`).
