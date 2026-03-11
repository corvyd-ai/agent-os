# /start-thread — Start a Multi-Agent Discussion

You are starting a discussion thread that multiple agents can participate in. Threads are how agents have conversations — each agent appends their response on their next cycle.

## Prerequisites

Find the company root by looking for `agent-os.toml` in the current directory or parents. Read it to get `[company].root`.

## Detect Context

**List registered agents** — read all files in `<company>/agents/registry/`:
```
Available agents:
- agent-001-builder (The Builder) — Software Engineer
- agent-003-operator (The Operator) — Operations
```

## Ask the User

If not already clear from their request:

1. **Topic** — what's the discussion about?
2. **Participants** — which agents should participate? Default to all agents.
3. **Opening message** — what kicks off the discussion? This is posted as the first entry from `human`.

## Generate ID

Format: `thread-YYYY-MMDD-NNN`

Scan `<company>/agents/messages/threads/` (excluding `resolved/` subdirectory) for files with today's date prefix. Find the highest sequence number and increment. Start at 001 if none.

## Create the File

Write to `<company>/agents/messages/threads/{thread-id}.md`:

```markdown
---
id: {thread-id}
topic: "{topic}"
started_by: human
participants: [{comma-separated agent IDs}]
started: {ISO 8601 timestamp}
status: active
---

## human — {YYYY-MM-DD HH:MM UTC}

{opening message}
```

## Confirm

```
Thread started:
- File: <company>/agents/messages/threads/{thread-id}.md
- Topic: {topic}
- Participants: {list of agent names}

Each participant will see this thread and can respond on their next cycle. Responses are appended as new sections separated by ---.
```
