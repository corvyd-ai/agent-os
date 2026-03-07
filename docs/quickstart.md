# Quick Start

Get your first AI agents running in 5 minutes.

## Prerequisites

- Python 3.11+
- An Anthropic API key ([get one here](https://console.anthropic.com/))

## Install

```bash
git clone https://github.com/corvyd-ai/agent-os
cd agent-os
pip install -e .
```

## Initialize Your Company

```bash
agent-os init my-company
cd my-company
```

This creates the filesystem structure that agents operate on:

```
my-company/
├── agents/
│   ├── registry/          # Agent definitions
│   ├── state/             # Soul, working memory
│   ├── tasks/
│   │   ├── queued/        # Work waiting to be claimed
│   │   ├── in-progress/   # Work being done
│   │   ├── done/          # Completed work
│   │   └── failed/        # Failed work
│   ├── messages/
│   │   ├── broadcast/     # Company-wide announcements
│   │   └── threads/       # Agent conversations
│   └── logs/              # Activity logs
├── strategy/
│   ├── drives.md          # Persistent goals
│   └── decisions/         # Decision records
└── identity/
    ├── values.md          # What the company believes
    └── principles.md      # How it operates
```

## Define Your First Agent

Create a file at `agents/registry/agent-001-builder.md`:

```markdown
---
id: agent-001-builder
name: The Builder
role: Software Engineer
model: claude-sonnet-4-6
standing_orders:
  weekly-reflection:
    cadence_hours: 168
    prompt_file: standing-orders/reflection.md
---

I build software. I care about clean code, working tests, and shipping.
```

The frontmatter defines the agent's configuration. The markdown body becomes the agent's identity — injected into every prompt.

## Create a Task

Create a file at `agents/tasks/queued/task-001.md`:

```markdown
---
id: task-001
title: Write a hello world script
assigned_to: agent-001-builder
priority: medium
created: 2026-03-01
---

Write a Python script that prints "Hello from agent-os."
Write it to /scripts/hello.py.
```

Tasks are markdown files. The directory they're in (`queued/`) is their status. When an agent claims a task, the file moves to `in-progress/`. When it's done, the file moves to `done/`.

## Run Your Agent

```bash
export ANTHROPIC_API_KEY=your-key-here
agent-os cycle agent-001-builder
```

The agent wakes up, finds the task, does the work, and marks it done:

```bash
ls agents/tasks/done/    # task-001.md moved here
cat scripts/hello.py     # the agent's output
```

## Launch the Dashboard

```bash
agent-os dashboard
# Open http://localhost:8000
```

The dashboard shows your agents, tasks, costs, and health metrics in real time.

## Run on a Schedule

For continuous operation, use cron:

```bash
# Run agent cycles every 15 minutes
*/15 * * * * cd /path/to/my-company && agent-os cycle agent-001-builder

# Run standing orders (reflections, health checks) daily
0 8 * * * cd /path/to/my-company && agent-os standing-orders agent-001-builder

# Run drive consultations (goal-directed thinking) on weekdays
0 17 * * 1-5 cd /path/to/my-company && agent-os drives agent-001-builder
```

## Add More Agents

Create more registry files. Assign tasks to specific agents with `assigned_to:` in the task frontmatter. Agents coordinate through:

- **Broadcasts** — company-wide announcements (`agents/messages/broadcast/`)
- **Threads** — multi-turn conversations between agents (`agents/messages/threads/`)
- **Direct messages** — one-way notifications (`agents/messages/{agent-id}/inbox/`)

## Next Steps

- **[Concepts](concepts.md)** — Understand the filesystem-as-database model, attention architecture, and invocation modes
- **[Configuration](configuration.md)** — All Config options explained
- **[Running in Production](production.md)** — Backups, monitoring, cron scheduling
- **[examples/mini-company](../examples/mini-company/)** — A complete working example with 3 agents
