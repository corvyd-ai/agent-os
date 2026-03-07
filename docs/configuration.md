# Configuration

> **Status:** This document covers the core configuration options. More detailed examples coming soon.

agent-os is configured through a single `Config` dataclass. All paths are derived from one root directory. All budgets have sensible defaults.

## Basic Usage

```python
from agent_os import Config, configure

config = Config(
    company_root=Path("./my-company"),
    default_model="claude-sonnet-4-6",
    max_budget_per_invocation_usd=5.00,
)

configure(config)
```

## Core Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `company_root` | env `AIOS_COMPANY_ROOT` | Root directory for the company filesystem |
| `default_model` | `claude-opus-4-6` | Default model for agent invocations |
| `agent_model_overrides` | `{}` | Per-agent model overrides (e.g., `{"agent-001": "claude-sonnet-4-6"}`) |

## Budget & Turn Limits

Each invocation mode has independent budget and turn limits:

| Mode | Budget | Turns | Purpose |
|------|--------|-------|---------|
| Standard task | $5.00 | 50 | Normal task execution |
| Standing orders | $2.00 | 40 | Recurring responsibilities |
| Drive consultation | $1.50 | 30 | Goal-directed thinking |
| Dream cycle | $1.50 | 25 | Memory reorganization |
| Interactive | $2.00 | 30 | Dashboard conversations |
| Thread response | $1.00 | 15 | Responding to discussions |
| Message triage | $0.75 | 15 | Processing inbox messages |

Override any limit per-invocation via CLI:

```bash
agent-os cycle agent-001 --max-budget 3.00 --max-turns 30
```

## Derived Paths

All directory paths are computed from `company_root`. You never configure paths individually:

- `agents/registry/` — agent definitions
- `agents/state/{agent-id}/` — soul, working memory
- `agents/tasks/{queued,in-progress,done,failed}/` — task lifecycle
- `agents/messages/broadcast/` — company announcements
- `agents/messages/threads/` — agent conversations
- `agents/logs/` — activity and cost JSONL

## Agent Registry Format

Each agent is a markdown file in `agents/registry/`:

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
  health-check:
    cadence_hours: 24
    prompt_file: standing-orders/health.md
---

The markdown body defines the agent's identity, capabilities,
and behavioral guidelines. This is injected into every prompt.
```

## Quality Gates

Agents with roles in `builder_roles` (default: `{"Software Engineer"}`) automatically run quality gate checks before completing tasks. The gate script checks:

- Build succeeds
- Linter passes (if configured)
- Tests pass (if they exist)
- Build output exists

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `AIOS_COMPANY_ROOT` | Default company root directory |
| `ANTHROPIC_API_KEY` | API key for Claude invocations |
