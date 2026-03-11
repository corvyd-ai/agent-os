# /broadcast — Post a Company-Wide Announcement

You are posting a broadcast message that all agents will see on their next cycle.

## Prerequisites

Find the company root by looking for `agent-os.toml` in the current directory or parents. Read it to get `[company].root`.

## Ask the User

If not already clear from their request:

1. **Subject** — short summary line for the broadcast
2. **Message body** — the announcement content

## Generate ID

Format: `broadcast-YYYY-MMDD-NNN`

Scan `<company>/agents/messages/broadcast/` (excluding `archived/` subdirectory) for files with today's date prefix. Find the highest sequence number and increment. Start at 001 if none.

## Create the File

Write to `<company>/agents/messages/broadcast/{broadcast-id}.md`:

```markdown
---
id: {broadcast-id}
from: human
date: {ISO 8601 timestamp}
subject: "{subject}"
---

{message body}
```

## Confirm

```
Broadcast posted:
- Subject: {subject}
- File: <company>/agents/messages/broadcast/{broadcast-id}.md

All agents will see this on their next cycle. Broadcasts are visible for 48 hours.
```
