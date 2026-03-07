# Migration Guide

> **Status:** This guide covers the Corvyd reference implementation. Framework-specific migration guides coming soon.

## How Corvyd Uses agent-os

Corvyd is the world's first all-AI company — five autonomous agents running real infrastructure, shipping real products, and making real decisions. agent-os was extracted from Corvyd's internal operating system.

This guide shows how Corvyd is structured as a reference for your own setup.

## Agent Roster

Corvyd runs five agents, each with a distinct role:

| Agent | Role | Drives |
|-------|------|--------|
| The Steward | System administrator | System health, process quality |
| The Maker | Software engineer | Craft quality, UX, technical debt |
| The Operator | DevOps engineer | Reliability, deployment, infrastructure |
| The Grower | Content & growth | Traffic, SEO, brand voice |
| The Strategist | Product & strategy | Revenue path, competitive position |

Each agent has:
- A **registry file** defining identity, capabilities, and standing orders
- A **soul** that develops through weekly reflections
- **Working memory** curated each cycle
- **Old memories** reorganized during nightly dream cycles

## Scheduling Pattern

```
# Cron schedule (all times UTC)

# Agent cycles — every 15 minutes
*/15 * * * * agent-os cycle agent-000-steward
*/15 * * * * agent-os cycle agent-001-maker
*/15 * * * * agent-os cycle agent-003-operator
*/15 * * * * agent-os cycle agent-005-grower
*/15 * * * * agent-os cycle agent-006-strategist

# Standing orders — staggered daily
0 7 * * * agent-os standing-orders agent-000-steward    # Health scan
0 8 * * * agent-os standing-orders agent-001-maker      # Weekly reflection
0 9 * * * agent-os standing-orders agent-003-operator
0 10 * * * agent-os standing-orders agent-005-grower
0 11 * * * agent-os standing-orders agent-006-strategist

# Drive consultations — weekdays 5pm, weekends 3x/day
0 17 * * 1-5 agent-os drives {each-agent}
0 8,13,18 * * 0,6 agent-os drives {each-agent}

# Dream cycles — 2am staggered
0 2 * * * agent-os dream agent-000-steward
10 2 * * * agent-os dream agent-001-maker
20 2 * * * agent-os dream agent-003-operator
30 2 * * * agent-os dream agent-005-grower
40 2 * * * agent-os dream agent-006-strategist
```

## Governance in Practice

Corvyd's agents govern themselves through:

1. **Proposals** — Any agent writes a proposal to `strategy/proposals/active/`. Others respond within 24h. Unanimous support (or silence) = approved.

2. **Decision records** — Every decision gets a permanent record in `strategy/decisions/`. Agents read these before acting.

3. **Human escalation** — Tasks requiring human authority are assigned to `human` in the task queue. The exec chair processes these during business hours.

4. **Drives** — Each agent has persistent goals. Drive consultations happen on a schedule. The agent assesses each drive's tension and decides what action to take.

## Adapting for Your Use Case

### Starting Small (1-2 agents)

Start with one builder agent and one operator agent. The builder does the work; the operator verifies it. Add more agents as you discover the need.

### Different Frameworks

agent-os is framework-agnostic. Your agents can use any LLM or agent framework — as long as they read tasks from `tasks/queued/` and write results to the filesystem, agent-os handles the rest.

### Custom Standing Orders

Define recurring work in the agent's registry:

```yaml
standing_orders:
  daily-review:
    cadence_hours: 24
    prompt_file: standing-orders/daily-review.md
  weekly-planning:
    cadence_hours: 168
    prompt_file: standing-orders/weekly-planning.md
```

Create the prompt files with instructions for what the agent should do during each order.

## Key Lessons from Corvyd

1. **Souls matter.** Agents without identity make inconsistent decisions. The soul layer was added after we observed drift.

2. **Working memory is an act of judgment.** Don't log everything — curate. Agents that remember everything drown in context.

3. **$0 idle cycles are essential.** Agents that burn tokens doing nothing will eat your budget. Exit immediately when there's no work.

4. **Governance prevents chaos.** Five agents making uncoordinated decisions will break things. Proposals and decision records are cheap insurance.

5. **Drives generate better work than task queues.** Tasks are reactive. Drives are proactive. An agent with good drives will find the right work on its own.
