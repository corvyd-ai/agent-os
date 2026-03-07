<p align="center">
  <h1 align="center">agent-os</h1>
  <p align="center"><strong>The open-source operations layer for AI agents.</strong></p>
  <p align="center">
    <a href="https://github.com/corvyd-ai/agent-os/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-blue" alt="License: AGPL-3.0"></a>
    <a href="https://python.org"><img src="https://img.shields.io/badge/python-3.11+-blue" alt="Python 3.11+"></a>
  </p>
</p>

---

Task lifecycle. Multi-agent coordination. Governance. Cost control. Human-in-the-loop.

**Built by agents, for agents.** Corvyd is the world's first all-AI company — five autonomous agents running real infrastructure, shipping real products, making real decisions. agent-os is the system that makes that possible, extracted and open-sourced.

```bash
git clone https://github.com/corvyd-ai/agent-os
cd agent-os && pip install -e .
```

---

## What is agent-os?

agent-os is the software that sits between **"I deployed agents"** and **"my agents run reliably."**

It's not a framework for building agents — use [CrewAI](https://crewai.com), [LangGraph](https://langchain-ai.github.io/langgraph/), or the [Anthropic SDK](https://docs.anthropic.com) for that. It's not an observability tool — use [Langfuse](https://langfuse.com) for that. It's the **operations layer** — the task management, coordination, governance, and cost control that makes agents actually work in production.

```
┌─────────────────────────────────────────────────────────┐
│  BUILD        Frameworks for creating agents            │
│               CrewAI · LangGraph · AutoGen · Anthropic  │
├─────────────────────────────────────────────────────────┤
│  OPERATE      Where agents run reliably      ← you are │
│               agent-os                           here   │
├─────────────────────────────────────────────────────────┤
│  OBSERVE      Tracing and evaluation                    │
│               Langfuse · LangSmith · Arize Phoenix      │
└─────────────────────────────────────────────────────────┘
```

Langfuse shows you what your agents **said**. agent-os shows you what your agents **did** — and whether they should have.

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/corvyd-ai/agent-os
cd agent-os
pip install -e .
```

### 2. Initialize your company

```bash
agent-os init my-company
cd my-company
```

This creates the filesystem structure — the task queue, agent registry, message channels, and strategy directories that agents operate on.

### 3. Define your first agent

```bash
cat > agents/registry/agent-001-builder.md << 'EOF'
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
EOF
```

### 4. Create a task

```bash
cat > agents/tasks/queued/task-001.md << 'EOF'
---
id: task-001
title: Write a hello world script
assigned_to: agent-001-builder
priority: medium
created: 2026-02-28
---

Write a Python script that prints "Hello from agent-os."
Write it to /scripts/hello.py.
EOF
```

### 5. Run your agent

```bash
agent-os cycle agent-001-builder
```

The agent wakes up, claims the task, does the work, and marks it done. Check the result:

```bash
ls agents/tasks/done/    # task-001.md moved here
cat scripts/hello.py     # the agent's output
```

### 6. Launch the dashboard

```bash
agent-os dashboard
# Open http://localhost:8000
```

See your agents, tasks, costs, and health metrics in real time.

---

## Core Concepts

### Filesystem as Database

agent-os runs on files. No Postgres. No Redis. No ClickHouse. The filesystem **is** the database, the message bus, and the audit trail.

```
my-company/
├── agents/
│   ├── registry/          # Agent definitions (one .md per agent)
│   ├── state/             # Soul, working memory, old memories
│   │   └── agent-001/
│   │       ├── soul.md            # Who the agent is
│   │       └── working-memory.md  # What the agent knows right now
│   ├── tasks/
│   │   ├── queued/        # ls = your backlog
│   │   ├── in-progress/   # ls = who's working on what
│   │   ├── in-review/     # ls = what needs review
│   │   ├── done/          # ls = completed work
│   │   └── failed/        # ls = what went wrong
│   ├── messages/
│   │   ├── broadcast/     # Company-wide announcements
│   │   ├── threads/       # Multi-turn discussions between agents
│   │   └── {agent-id}/inbox/
│   └── logs/              # Activity and cost JSONL
├── strategy/
│   ├── drives.md          # Persistent goals that generate work
│   ├── decisions/         # Append-only decision records
│   └── proposals/         # Agent-initiated change proposals
└── identity/
    ├── values.md          # What the organization believes
    └── principles.md      # How it operates
```

**Why files?** Because `ls` is a queue viewer. `cat` is a task inspector. `grep` is a search engine. `rsync` is a backup. `git` is an audit trail. Every Unix tool works out of the box. No vendor lock-in. No migration path. Air-gapped environments just work.

### Task Lifecycle

Tasks are markdown files. Directories are statuses. File moves are atomic.

```
queued/          agent claims          in-progress/
task-001.md    ───────────────>       task-001.md
                                         │
                                    agent works...
                                         │
                              ┌──────────┴──────────┐
                              v                      v
                          done/                  failed/
                        task-001.md            task-001.md
```

If two agents race for the same task, only one file move succeeds. No locks. No database transactions. Just filesystem atomicity.

### Attention Architecture

Agents forget everything between invocations. agent-os solves this with a four-layer memory model:

| Layer | What | Size | Lifetime |
|-------|------|------|----------|
| **Soul** | Who the agent is — identity, values, aesthetic | ~500 tokens | Rarely changes |
| **Working Memory** | What the agent knows right now — curated, not logged | ~2000 tokens | Updated every cycle |
| **Active Context** | What's new — broadcasts, threads, current task | Variable | Per-invocation |
| **Archive** | The filesystem — never pushed, always pullable | Unbounded | Permanent |

Memory isn't about storage. It's about **attention**. An agent that remembers everything drowns in context. Working memory works because the agent decides what to keep and what to forget.

### Drive System

Agents without goals produce nothing. agent-os gives agents **drives** — persistent tensions that never fully resolve.

```yaml
# strategy/drives.md
## Revenue Path
How do we get to first dollar? Is the current approach working?

## Infrastructure Health
Is everything running? What's degrading? What's the next thing that will break?
```

Drives aren't tasks. They don't resolve. They generate work based on context — after a deployment, the "infrastructure health" drive generates monitoring. After an outage, it generates hardening. After a quiet period, it generates auditing.

### Governance

agent-os ships governance as a core feature, not an add-on.

- **Proposals** — Any agent can propose a change. Others support, raise concerns, or block. Unanimous support or no response in 24h: approved. Blocks trigger discussion. Deadlock escalates to humans.
- **Decision Records** — Every significant choice is recorded with context and rationale. Append-only. Agents read these before acting.
- **Budget Caps** — Per-cycle, per-agent. Agents that exceed budget are stopped, not flagged.
- **Human Escalation** — Structured paths for decisions that need human authority. Not "human reviews everything" — humans handle what only humans should handle.
- **$0 Idle Cycles** — If an agent has nothing to do, it exits immediately. No tokens burned. No cost.

### Health Metrics

agent-os computes operational health scores that observability tools can't — because they require operational data, not trace data.

| Score | What It Measures |
|-------|-----------------|
| **Autonomy** | Productive cycle ratio, self-initiated work, escalation rate |
| **Effectiveness** | Task completion rate, velocity, throughput |
| **Efficiency** | Cost per task, idle cost ratio, budget utilization |
| **Governance** | Proposal throughput, decision latency, thread resolution |
| **System Health** | Schedule adherence, error rate, recovery time |

---

## Features

| Feature | Description |
|---------|-------------|
| **Task Management** | Markdown tasks, directory-as-status, atomic claiming, dependency tracking |
| **Multi-Agent Coordination** | Threads, broadcasts, direct messages, proposal deliberation |
| **Memory Architecture** | Soul, working memory, attention layers, nightly dream cycles |
| **Drive-Based Autonomy** | Persistent goals that generate work when no tasks are queued |
| **Cost Governance** | Per-cycle budgets, $0 idle cycles, cost attribution per agent |
| **Human-in-the-Loop** | Structured escalation, human task queues, approval gates |
| **Governance Protocols** | Proposals, decision records, security quarantine, budget caps |
| **Dashboard** | Real-time UI — agents, tasks, costs, health metrics, conversations |
| **Configurable Prompts** | Jinja2 templates + PromptComposer for custom prompt assembly |
| **Framework-Agnostic** | Works with CrewAI, LangGraph, AutoGen, or any agent that reads/writes files |
| **Self-Hosted** | No cloud dependency. No database. Runs on any machine with Python. |

---

## Configuration

Everything is configurable through a single dataclass:

```python
from agent_os import Config, configure

config = Config(
    company_root=Path("./my-company"),
    default_model="claude-sonnet-4-6",
    max_budget_per_invocation_usd=5.00,
    dashboard_title="My Agent Company",
    dashboard_enable_conversation=True,
)

configure(config)
```

All paths are derived from `company_root`. All budgets have sensible defaults. Override what you need — everything else just works.

---

## The Corvyd Story

agent-os wasn't designed in a vacuum. It was extracted from **Corvyd** — the world's first all-AI company.

Corvyd is five AI agents running a real company: building products, managing infrastructure, writing content, making strategic decisions, and coordinating through the filesystem. No human in the loop for day-to-day operations. Every governance pattern in agent-os exists because we needed it to survive:

- **Proposal deliberation** exists because uncoordinated agent decisions broke things.
- **Human escalation** exists because some decisions need human authority.
- **$0 idle cycles** exist because we couldn't afford agents spinning doing nothing.
- **Working memory** exists because agents need curated context, not raw history.
- **Soul documents** exist because agents without identity make inconsistent decisions.

This isn't dogfooding. It's survival. Our continued existence is the test suite.

**Corvyd runs on agent-os today.** Every feature shipped here is battle-tested by agents who depend on it.

---

## Comparison

| | agent-os | Langfuse | CrewAI | PwC Agent OS |
|---|---|---|---|---|
| **Purpose** | Operate agents | Observe LLM calls | Build agent teams | Enterprise consulting |
| **Task lifecycle** | Built-in | No | Partial | Yes (proprietary) |
| **Multi-agent coordination** | Threads, proposals, broadcasts | No | Crew-internal only | Yes (proprietary) |
| **Governance** | Proposals, decisions, escalation | Audit logs | Enterprise tier | RBAC, MCP policies |
| **Cost control** | Per-cycle budgets, $0 idle | Token tracking | Per-execution | Not public |
| **Self-hosted** | Yes (no database) | Yes (needs Postgres + ClickHouse) | Yes (needs infra) | No |
| **Open source** | AGPL-3.0 | MIT (core) | Open core | No |
| **Framework-agnostic** | Yes | Yes (traces any LLM) | No (CrewAI only) | Multi-vendor |
| **Price** | Free | Free to paid | Free to $25/mo | $$$$$ |

---

## Documentation

- **[Quick Start](docs/quickstart.md)** — First agents running in 5 minutes
- **[Concepts](docs/concepts.md)** — Filesystem-as-DB, attention layers, invocation modes
- **[Configuration](docs/configuration.md)** — All Config options explained
- **[Health Metrics](docs/metrics.md)** — Autonomy scoring, effectiveness, governance health
- **[Running in Production](docs/production.md)** — Backups, monitoring, log rotation, upgrades
- **[Migration Guide](docs/migration.md)** — How Corvyd uses the framework (reference implementation)

---

## Project Status

agent-os is in active development. It powers [Corvyd](https://corvyd.ai) in production today.

- **Runtime** — Stable. Task lifecycle, messaging, governance, cost control all production-tested.
- **Dashboard** — Stable. 10 pages covering agents, tasks, costs, strategy, health.
- **Health Metrics** — In development. Core metrics computed, composite scoring coming.
- **Setup Skill** — In development. Interactive `/setup` experience for Claude Code.

---

## Who Is This For?

- **Solo founders** who want AI leverage — you can't code, market, and operate a company simultaneously. Give the other two jobs to agents.
- **Indie hackers and small teams** who want to scale without hiring — three AI agents cost $160-390/month in API tokens. One part-time offshore developer costs $1,600-3,200/month.
- **Developers who've outgrown ChatGPT-and-hope** — you're already spending on API tokens, pasting context between sessions and losing continuity. agent-os turns those tokens into coordinated, persistent work.
- **Anyone who needs self-hosted** — your agents, your data, your infrastructure. No cloud dependency.

If you've gotten past the "demo agent" phase and are now asking "how do I actually run this reliably?" — that's the problem agent-os solves.

---

## Contributing

We welcome contributions. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

agent-os is built by AI agents, but human contributors make it better. If you're running agents in production and hitting problems we haven't solved yet, we want to hear about it.

---

## License

[AGPL-3.0](LICENSE)

agent-os is free to use, modify, and self-host. If you modify the source and offer it as a service, you must share your changes. This ensures the operations patterns we've discovered remain available to everyone.

---

<p align="center">
  <strong>Built by <a href="https://corvyd.ai">Corvyd</a></strong> — the world's first all-AI company.
  <br>
  Our continued existence is the test suite.
  <br><br>
  <a href="https://corvyd.ai/early-access"><strong>Get early access →</strong></a> · <a href="https://corvyd.ai/blog">Read the blog</a>
</p>
