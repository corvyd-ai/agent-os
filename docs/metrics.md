# Health Metrics

> **Status:** Core metrics are computed. Composite scoring and dashboard integration are in active development.

agent-os computes operational health scores that observability tools can't — because they require operational data, not trace data.

## Metric Categories

### Autonomy

How independently are agents operating?

| Metric | What It Measures |
|--------|-----------------|
| Productive cycle ratio | Cycles that did work vs. idle cycles |
| Self-initiated work | Tasks generated from drives vs. assigned by humans |
| Escalation rate | How often agents need human intervention |

High autonomy = agents generating and completing their own work. Low autonomy = agents waiting for instructions or escalating frequently.

### Effectiveness

Are agents getting things done?

| Metric | What It Measures |
|--------|-----------------|
| Task completion rate | Done tasks / (done + failed) |
| Velocity | Tasks completed per time period |
| Throughput | Total productive output volume |

### Efficiency

What does the work cost?

| Metric | What It Measures |
|--------|-----------------|
| Cost per task | Average API spend per completed task |
| Idle cost ratio | Spend on idle cycles vs. productive cycles |
| Budget utilization | Actual spend vs. allocated budget |

$0 idle cycles are a key efficiency feature — agents that have nothing to do exit immediately without burning tokens.

### Governance

Is the decision-making process healthy?

| Metric | What It Measures |
|--------|-----------------|
| Proposal throughput | Proposals created, decided, and implemented |
| Decision latency | Time from proposal to decision |
| Thread resolution | Active discussions resolved vs. stale |

### System Health

Is the infrastructure working?

| Metric | What It Measures |
|--------|-----------------|
| Schedule adherence | Cron jobs running on time |
| Error rate | Failed invocations and unhandled errors |
| Recovery time | Time from failure to resolution |

## Cost Tracking

Every invocation logs cost data to `finance/costs/`:

```jsonl
{"agent_id": "agent-001", "task_id": "task-042", "cost_usd": 1.23, "model": "claude-opus-4-6", "turns": 12, "duration_ms": 45000, "timestamp": "2026-03-01T10:00:00Z"}
```

The dashboard aggregates this into per-agent, per-day, and per-task cost views.

## Dashboard

The agent-os dashboard (`agent-os dashboard`) displays health metrics in real time:

- Agent status and recent activity
- Task pipeline (queued → in-progress → done)
- Cost breakdown by agent and time period
- Health scores across all five categories
- Active conversations and governance activity
