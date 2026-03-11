# /check-status — View System Status

You are checking the status of an agent-os company. Read the filesystem and summarize what's happening. No user input needed — just report.

## Prerequisites

Find the company root by looking for `agent-os.toml` in the current directory or parents. Read it to get `[company].root` and `[company].name`.

## Gather Data

Read all of the following in parallel where possible:

### 1. Registered Agents
Read all files in `<company>/agents/registry/`. For each, show:
- Agent ID, name, role

### 2. Task Counts
Count files in each task directory:
- `agents/tasks/queued/` — waiting
- `agents/tasks/in-progress/` — active
- `agents/tasks/in-review/` — needs review
- `agents/tasks/backlog/` — needs promotion
- `agents/tasks/done/` — completed (count only last 7 days by file modification time)
- `agents/tasks/failed/` — failed (count only last 7 days)

### 3. Recent Broadcasts
Read files in `agents/messages/broadcast/` modified in the last 48 hours. Show subject and date for each.

### 4. Active Threads
Read files in `agents/messages/threads/` (not `resolved/`). For each with `status: active`, show topic and participants.

### 5. Active Proposals
Read files in `strategy/proposals/active/`. Show title, proposer, and date.

### 6. Inbox Status
For each registered agent, count files in `agents/messages/{agent-id}/inbox/` (excluding `processed/`).

### 7. Budget Status (if available)
Run `agent-os budget --config agent-os.toml 2>/dev/null` to get budget information. If the command fails or isn't available, skip this section.

### 8. Cron Status (if available)
Run `agent-os cron status --config agent-os.toml 2>/dev/null` to check scheduling. If the command fails, skip.

### 9. Recent Costs (if available)
Check `<company>/finance/costs/` for today's and yesterday's JSONL files. If they exist, sum up costs by agent.

## Present the Report

Format as a clear status report:

```
# {Company Name} — Status Report

## Agents (N registered)
| Agent | Role | Inbox |
|-------|------|-------|
| The Builder (agent-001-builder) | Software Engineer | 2 messages |
| The Operator (agent-003-operator) | Operations | 0 messages |

## Tasks
- Queued: N
- In Progress: N
- In Review: N
- Backlog: N
- Done (7d): N
- Failed (7d): N

## Recent Broadcasts (48h)
- "{subject}" — {date} (from {agent})

## Active Threads
- "{topic}" — {participants} ({N} responses)

## Active Proposals
- "{title}" — proposed by {who} on {date}

## Budget
{output from agent-os budget, or "No cost data available"}

## Scheduling
{cron status, or "Not configured"}
```

If any section has no data, show "None" rather than omitting it — the user should see what's empty.
