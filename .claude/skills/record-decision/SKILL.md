# /record-decision — Record a Decision

You are recording a decision in the append-only decision log. Decisions are permanent records — they are never edited after creation.

## Prerequisites

Find the company root by looking for `agent-os.toml` in the current directory or parents. Read it to get `[company].root`.

## Detect Context

Check `<company>/strategy/proposals/active/` for any related proposals. If there's an active proposal that this decision resolves, note it and offer to move it to `decided/`.

## Ask the User

If not already clear from their request:

1. **Title** — what was decided (short, descriptive)
2. **What was decided** — the decision itself
3. **Context** — why was this decision made? What problem does it solve?
4. **Who decided** — default to `human` unless the user specifies otherwise

## Generate ID

Format: `decision-YYYY-MMDD-NNN`

Scan `<company>/strategy/decisions/` for files with today's date prefix. Find the highest sequence number and increment. Start at 001 if none.

## Create the File

Write to `<company>/strategy/decisions/{decision-id}.md`:

```markdown
---
id: {decision-id}
title: "{title}"
decided_by: {who}
date: {YYYY-MM-DD}
status: decided
created: {ISO 8601 timestamp}
---

## Decision
{What was decided — clear, unambiguous statement}

## Context
{Why this decision was made. What problem it solves.}

## Rationale
{Why this approach over alternatives}

## Impact
{What changes as a result of this decision}
```

## Move Related Proposal

If a related active proposal was found, ask: **"Move proposal {proposal-id} to decided?"**

If yes, move the file from `strategy/proposals/active/` to `strategy/proposals/decided/` and update its `status` frontmatter to `approved` (or `rejected` if the decision goes against it).

## Confirm

```
Decision recorded:
- File: <company>/strategy/decisions/{decision-id}.md
- Title: {title}
- Decided by: {who}

Decisions are append-only — this record is permanent.
```
