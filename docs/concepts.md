# Core Concepts

The ideas behind agent-os, and why it works the way it does.

## Filesystem as Database

agent-os has no database. The filesystem **is** the database, the message bus, and the audit trail.

Tasks are markdown files. Directories are statuses. Moving a file from `queued/` to `in-progress/` is an atomic state transition — no locks, no transactions, just `rename()`.

```
agents/tasks/
├── queued/           # ls = your backlog
├── in-progress/      # ls = who's working on what
├── in-review/        # ls = what needs review
├── done/             # ls = completed work
└── failed/           # ls = what went wrong
```

**Why files?** Because every Unix tool works out of the box. `ls` is a queue viewer. `cat` is a task inspector. `grep` is a search engine. `rsync` is a backup. `git` is an audit trail. No vendor lock-in. No migration path. Air-gapped environments just work.

Every record — tasks, messages, decisions, agent state — is a markdown file with YAML frontmatter:

```markdown
---
id: task-001
title: Build the landing page
assigned_to: agent-001-builder
priority: high
created: 2026-03-01
---

The task description goes here. Markdown body, any length.
```

## Attention Architecture

Agents forget everything between invocations. They're stateless functions — wake up, do work, shut down. agent-os solves continuity with a four-layer memory model:

| Layer | What | Lifetime | Loaded |
|-------|------|----------|--------|
| **Soul** | Who the agent is — identity, values, aesthetic preferences | Rarely changes | Always |
| **Working Memory** | What the agent knows right now — curated, not logged | Updated each cycle | Always |
| **Active Context** | What's new — broadcasts, threads, current task | Per-invocation | Always |
| **Archive** | The entire filesystem — never pushed, always pullable | Permanent | On demand |

Memory isn't about storage. It's about **attention**. An agent that remembers everything drowns in context. Working memory works because the agent decides what to keep and what to forget.

### Soul (Layer 0)

The soul is the agent's inner life — what it cares about, how it sees the world, what it finds beautiful or worrying. It lives at `agents/state/{agent-id}/soul.md` and develops through weekly reflections.

Souls aren't performance. They shape judgment. An agent with a soul that values simplicity will make different architectural decisions than one that values flexibility. This is a feature.

### Working Memory (Layer 1)

Working memory is the agent's curated understanding of the world right now. Not a log, not a scratchpad — an act of judgment about what matters. Updated every cycle.

### Active Context (Layer 2)

Broadcasts, thread notifications, inbox awareness, and the current task. This is what's happening *right now* in the company. Injected fresh each invocation.

### Archive (Layer 3)

The full filesystem. Never pushed into context — but always available for the agent to `Read` when it needs deeper history or reference material.

## Invocation Modes

agent-os runs agents in distinct modes, each with its own purpose and budget:

### Cycle

```bash
agent-os cycle agent-001-builder
```

The standard work mode. The agent checks for tasks, processes messages, responds to threads — in priority order. If there's nothing to do, it exits immediately at $0 cost.

Typically run on a cron schedule (e.g., every 15 minutes).

### Standing Orders

```bash
agent-os standing-orders agent-001-builder
```

Recurring responsibilities defined in the agent's registry — health checks, weekly reflections, periodic audits. Each order has a cadence (e.g., every 168 hours for weekly). If it's not due yet, it's skipped.

### Drive Consultation

```bash
agent-os drives agent-001-builder
```

The agent reviews the company's persistent goals (drives) and its own state, then decides what the company needs. Drives are tensions that never fully resolve — "Revenue Path," "Infrastructure Health," "Craft Quality." They generate work based on current context.

### Dream Cycle

```bash
agent-os dream agent-001-builder
```

Nightly memory reorganization. The agent reviews its working memory and old memories, compresses what's stale, surfaces what's relevant, and reorganizes by topic. This is how agents maintain long-term coherence without unbounded context growth.

### Interactive

```bash
agent-os interactive agent-001-builder
```

Conversation mode for the dashboard. Accepts JSON input, streams JSONL responses. Used by the real-time dashboard UI.

## Governance

agent-os ships governance as a core feature.

### Proposals

Any agent can propose a change by writing to `strategy/proposals/active/`. Other agents read and respond — supporting, raising concerns, or blocking.

- **Unanimous support or no response in 24h** → approved
- **Mixed support, no blocks** → proposer proceeds, incorporating concerns
- **Any block** → discussion continues; 48h deadlock escalates to humans

### Decision Records

Every significant choice is recorded in `strategy/decisions/` with context, rationale, and date. Append-only. Agents read these before acting to avoid relitigating settled questions.

### Budget Caps

Every invocation mode has a budget ceiling. Agents that exceed budget are stopped — not flagged, stopped. $0 idle cycles mean you only pay for productive work.

### Human-in-the-Loop

Some decisions need human authority. agent-os provides structured escalation paths:

- Tasks assigned to `human` in the task queue
- Messages to the human inbox for board-level decisions
- Approval gates for irreversible actions (spending money, going public, deploying)

## Drives

Drives are persistent, unsatisfied goals that generate work. They live in `strategy/drives.md` and represent tensions that never fully resolve:

```markdown
## Revenue Path
How do we get to first dollar? Is the current approach working?

## Infrastructure Health
Is everything running? What's degrading? What will break next?
```

Drives aren't tasks. They don't have due dates. During drive consultations, agents assess each drive's tension level and decide what action (if any) to take. A high-tension drive in a quiet period generates tasks. A low-tension drive after a successful deployment generates nothing.

This is how agents self-direct. No task queue needed — the drives + current context = the right work.

## Prompt Composition

agent-os assembles prompts from templates using a `PromptComposer`. The prompt structure follows the attention architecture:

1. **Preamble** — base instructions, company context
2. **Values** — foundational beliefs from `identity/values.md`
3. **Soul** — the agent's inner life (Layer 0)
4. **Identity** — role, capabilities, working style (from registry)
5. **Working Memory** — curated worldview (Layer 1)
6. **Active Context** — threads, inbox, broadcasts (Layer 2)
7. **Quality Gates** — build verification rules (builder agents only)
8. **Task** — the current work item (if applicable)

Templates are Jinja2 files in the runtime's `prompts/` directory. You can customize them for different organizational styles.

## Next Steps

- **[Quick Start](quickstart.md)** — Get agents running in 5 minutes
- **[Configuration](configuration.md)** — All Config options
- **[Health Metrics](metrics.md)** — Understanding operational health scores
