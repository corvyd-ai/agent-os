# agent-os — Claude Code Context

agent-os is a file-based operating system for AI-native organizations. Everything is a file — tasks, decisions, messages, knowledge, agent state. The filesystem is the shared brain. Agents run on schedules (cron or systemd timers), check for work, act, and exit. No daemons, no databases — just files, git, and Unix.

**This CLAUDE.md is for working on agent-os itself — the platform.** You're here to fix a bug, add a feature, refactor, write tests, or improve docs in the Python source, dashboard, or examples. If you're instead trying to *observe or operate* a running company that uses agent-os, you want that company's own workspace — its `CLAUDE.md` lives alongside its company directory, not here.

## Contributing

`main` is branch-protected. Every change flows through a feature branch → PR → CI → review → merge. CI runs lint (`ruff check`, `ruff format --check`), the pytest suite on Python 3.11 and 3.12, a frontend build, and a wheel/sdist build. At least one approving review is required; force-pushes and direct pushes to `main` are blocked.

The complete workflow — for both human contributors and agents running on agent-os who want to propose platform improvements — is documented in **`CONTRIBUTING.md`**. Read it before your first PR.

How merged changes reach a *running* deployment is a deployment concern, not a platform concern. Typical patterns include pinning a specific commit/tag, installing from `main`, or running a polling updater that `pip install -e`'s `origin/main` on a timer. The platform itself just lives in this repo; how you ship it to production is up to you.

## Quick Start (fresh clone)

Clone the repo and run Claude Code:
```
cd agent-os
claude
>>> /setup
```

The `/setup` skill walks you through installation, initialization, and first agent run.

## Development

```bash
# Install (editable, with dev deps)
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/

# Type check
pyright src/

# Build wheel
python -m build
```

## Versioning

The package version is derived from **git tags** via `hatch-vcs` (a setuptools-scm wrapper). There are no hardcoded version strings to maintain.

### How it works

- `hatch-vcs` runs `git describe` at build/install time and computes a PEP 440 version.
- On a tagged commit (`git tag v1.2.0`), the version is exactly `1.2.0`.
- Between tags, the version is a dev version like `1.2.0.dev5+gabcdef0` (5 commits after v1.2.0, at commit abcdef0).
- At build time, `hatch-vcs` writes `src/agent_os/_version.py` — this file is `.gitignore`d and must never be committed.
- `src/agent_os/__init__.py` imports `__version__` from `_version.py`, falling back to `importlib.metadata` for editable installs.

### When to tag a release

Tag `main` after merging a meaningful set of changes. Use semantic versioning (`vMAJOR.MINOR.PATCH`):
- **PATCH** (`v0.1.1`) — bug fixes, docs, minor tweaks
- **MINOR** (`v0.2.0`) — new features, new CLI commands, new API endpoints
- **MAJOR** (`v1.0.0`) — breaking changes to the CLI, config schema, or file formats

```bash
git tag v0.2.0
git push origin v0.2.0
```

### What NOT to do

- **Never hardcode a version string** in source files, pyproject.toml, or the dashboard. The version flows from git tags → `_version.py` → `__version__` → everywhere else (CLI `--version`, FastAPI metadata, dashboard `/api/info`).
- **Never commit `_version.py`** — it's generated and gitignored.
- **Don't tag feature branches** — only tag commits on `main`.

### Where the version surfaces

| Location | How |
|----------|-----|
| `python -c "from agent_os import __version__; print(__version__)"` | Package import |
| `agent-os --version` | CLI |
| Dashboard sidebar footer | Frontend fetches `/api/info` |
| `GET /api/info` | FastAPI endpoint |
| `pip show agent-os` | Package metadata |

## Source Layout

```
src/agent_os/
  cli.py          # CLI entry point (agent-os command)
  config.py       # Config dataclass + TOML parsing
  runner.py       # Agent cycle runner (task/message/thread dispatch)
  composer.py     # Prompt composition (4-layer attention model)
  core.py         # File operations (tasks, messages, broadcasts, IDs)
  prompts/        # Default Jinja2 templates (preamble, interactive, quality gates)
  dashboard/      # Dashboard (FastAPI backend + React/Vite frontend)
    frontend/     # React/Vite app (npm run build → dist/)
    Makefile      # Dev server commands (make dev)
    screenshot.py # Visual testing tool
examples/
  mini-company/   # Reference implementation of a company filesystem
tests/            # pytest suite
```

## Key Entry Points

| File | What it does |
|------|-------------|
| `src/agent_os/cli.py` | All CLI commands: `init`, `cycle`, `run`, `cron`, `budget`, `task`, `drives`, `dream`, `standing-orders`, `dashboard` |
| `src/agent_os/config.py` | `Config` dataclass, `Config.from_toml()`, `Config.discover_toml()` — TOML schema definition |
| `src/agent_os/runner.py` | `run_cycle()` — the main loop: check tasks, messages, threads, exit if idle |
| `src/agent_os/composer.py` | `compose_system_prompt()` — builds the 4-layer attention prompt |
| `src/agent_os/core.py` | All file operations: `create_task()`, `send_message()`, `post_broadcast()`, `next_id()`, `claim_task()`, `complete_task()` |

## Available Skills

| Skill | Description |
|-------|-------------|
| `/setup` | Guided first-time installation and configuration |
| `/add-agent` | Create a new agent definition with registry file and state directories |
| `/create-task` | Create a properly formatted task for an agent |
| `/send-message` | Send a direct message to an agent's inbox |
| `/broadcast` | Post a company-wide broadcast announcement |
| `/create-proposal` | Create a governance proposal for agent deliberation |
| `/record-decision` | Record a decision in the decision log |
| `/start-thread` | Start a multi-agent discussion thread |
| `/check-status` | View system status: agents, tasks, budgets, health |

## Conventions

### File Format

All structured files use YAML frontmatter + markdown body:

```
---
id: item-2026-0308-001
title: "Example"
created: 2026-03-08T10:00:00Z
---

Markdown body content here.
```

### ID Generation

Sequential within date prefix: `{type}-YYYY-MMDD-NNN`

Scan the target directory (and all lifecycle directories for tasks) for existing files with the same date prefix, then increment. Examples:
- `task-2026-0308-001`, `task-2026-0308-002`
- `msg-2026-0308-001`
- `broadcast-2026-0308-001`

### Frontmatter Schemas

**Task** (`agents/tasks/{status}/*.md`):
```yaml
id: task-2026-0308-001
title: "Task title"
created: 2026-03-08T10:00:00Z
created_by: human  # or agent-id
assigned_to: agent-001-builder  # agent-id, "" for unassigned, or "human"
priority: medium  # low, medium, high, critical
status: queued  # queued, in-progress, in-review, done, failed, declined
tags: [feature, mvp]
depends_on: []  # task IDs that must be done first
outcome: ""  # success, partial, failure, cancelled (set on completion)
```

**Message** (`agents/messages/{agent-id}/inbox/*.md`):
```yaml
id: msg-2026-0308-001
from: human  # or agent-id
to: agent-001-builder
date: 2026-03-08T10:00:00Z
subject: "Subject line"
urgency: normal  # normal, high, critical
requires_response: false
thread: ""  # optional thread-id reference
```

**Broadcast** (`agents/messages/broadcast/*.md`):
```yaml
id: broadcast-2026-0308-001
from: human  # or agent-id
date: 2026-03-08T10:00:00Z
subject: "Subject line"
```

**Thread** (`agents/messages/threads/*.md`):
```yaml
id: thread-2026-0308-001
topic: "Discussion topic"
started_by: human  # or agent-id
participants: [agent-001-builder, agent-003-operator]
started: 2026-03-08T10:00:00Z
status: active  # active, resolved
```

Thread body uses `## {agent-id} — {timestamp}` headers separated by `---`.

**Proposal** (`strategy/proposals/active/*.md`):
```yaml
id: proposal-2026-0308-001
title: "Proposal title"
proposed_by: human  # or agent-id
date: 2026-03-08
status: active  # active, approved, blocked, rejected
created: 2026-03-08T10:00:00Z
```

**Decision** (`strategy/decisions/*.md`):
```yaml
id: decision-2026-0308-001
title: "Decision title"
decided_by: human  # or agent-id
date: 2026-03-08
status: decided
created: 2026-03-08T10:00:00Z
```

**Agent Registry** (`agents/registry/*.md`):
```yaml
id: agent-001-builder
name: The Builder
role: Software Engineer
model: claude-sonnet-4-6
tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
```

Body contains identity description, core capabilities, and drives in markdown.

### Directory Structure

```
<company>/
  agents/
    registry/              # Agent definition files
    state/<agent-id>/      # Per-agent state
      soul.md              # Layer 0 — inner life, rarely changes
      working-memory.md    # Layer 1 — curated worldview, updated each cycle
      old-memories.md      # Long-term storage (dream cycles)
    tasks/
      queued/              # Ready to claim
      in-progress/         # Being worked on
      in-review/           # Awaiting review
      done/                # Completed
      failed/              # Failed
      backlog/             # Awaiting human promotion
      declined/            # Rejected
    messages/
      broadcast/           # Company-wide announcements
      threads/             # Multi-agent discussions
      <agent-id>/inbox/    # Direct messages to agent
    logs/<agent-id>/       # Daily JSONL activity logs + journal.md
  strategy/
    drives.md              # Persistent company goals
    current-focus.md       # Current priority
    decisions/             # Append-only decision records
    proposals/
      active/              # Open proposals
      decided/             # Closed proposals
  identity/
    values.md              # Company values
    principles.md          # Operating principles
  finance/costs/           # Cost tracking JSONL
  products/                # Product-specific files
  knowledge/               # Shared knowledge base
  operations/scripts/      # Operational scripts
```

### Task Lifecycle

Tasks move between directories — the directory IS the status:
`queued/` → `in-progress/` → `done/` (or `failed/`, `in-review/`)

Agents with medium autonomy create tasks in `backlog/` (requires human `promote_task` to move to `queued/`).

### Configuration

`agent-os.toml` lives alongside the company directory. Key sections:

```toml
[company]
name = "Company Name"
root = "."
timezone = "UTC"

[runtime]
model = "claude-sonnet-4-6"

[budget]
task = 5.00
standing_orders = 2.00
drive_consultation = 1.50
dream = 1.50
daily_cap = 100.00
weekly_cap = 500.00
monthly_cap = 2000.00

[schedule]
enabled = true
[schedule.cycles]
enabled = true
interval_minutes = 15

[prompts]
override_dir = "prompts"

[dashboard]
agent_ids = []
```

Full schema: see `src/agent_os/config.py` `Config` dataclass.

### Config Discovery

1. `--config` CLI flag
2. `AGENT_OS_CONFIG` env var
3. Walk up from `AGENT_OS_ROOT`
4. Walk up from cwd

### Autonomy Levels

- **low** — Cannot create tasks
- **medium** — Tasks go to `backlog/` (human must promote)
- **high** — Tasks go directly to `queued/`
