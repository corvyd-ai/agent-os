# /send-message — Send a Direct Message to an Agent

You are sending a direct message to an agent's inbox in an agent-os company.

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

1. **Recipient** — which agent? Show the list. If the user said "message the builder", match it.
2. **Subject** — short summary line
3. **Message body** — what to say
4. **Urgency** — default `normal`. Set to `high` if the user indicates urgency.
5. **Requires response?** — default `false`. Set to `true` if the user is asking a question or requesting a reply.

## Generate ID

Format: `msg-YYYY-MMDD-NNN`

Scan `<company>/agents/messages/{recipient-id}/inbox/` (including `inbox/processed/`) for files with today's date prefix. Find highest sequence number and increment. Start at 001 if none.

## Create the File

Ensure the inbox directory exists:
```bash
mkdir -p <company>/agents/messages/{recipient-id}/inbox
```

Write to `<company>/agents/messages/{recipient-id}/inbox/{msg-id}.md`:

```markdown
---
id: {msg-id}
from: human
to: {recipient-id}
date: {ISO 8601 timestamp}
subject: "{subject}"
urgency: {urgency}
requires_response: {true/false}
---

{message body}
```

## Confirm

```
Message sent:
- To: {agent-name} ({recipient-id})
- Subject: {subject}
- File: <company>/agents/messages/{recipient-id}/inbox/{msg-id}.md

The agent will see this on their next cycle.
```
