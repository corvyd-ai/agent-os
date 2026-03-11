# /create-proposal — Create a Governance Proposal

You are creating a proposal for agent deliberation in an agent-os company. Proposals are how changes get discussed and decided.

## Prerequisites

Find the company root by looking for `agent-os.toml` in the current directory or parents. Read it to get `[company].root`.

## Detect Context

**List registered agents** — read all files in `<company>/agents/registry/` to show who can participate in deliberation.

## Ask the User

If not already clear from their request:

1. **Title** — what's being proposed (short, descriptive)
2. **What's being proposed** — the user's description, which you'll structure into sections
3. **Which agents should deliberate?** — suggest all agents by default, or let the user pick specific ones

## Generate ID

Format: `proposal-YYYY-MMDD-NNN`

Scan `<company>/strategy/proposals/active/` and `<company>/strategy/proposals/decided/` for files with today's date prefix. Find the highest sequence number and increment. Start at 001 if none.

## Create the File

Write to `<company>/strategy/proposals/active/{proposal-id}.md`:

```markdown
---
id: {proposal-id}
title: "{title}"
proposed_by: human
date: {YYYY-MM-DD}
status: active
created: {ISO 8601 timestamp}
---

## Problem
{What problem does this solve? Why is it needed?}

## Proposal
{What exactly is being proposed? Be specific.}

## Expected Impact
{What changes if this is approved? What are the risks?}

## Deliberation
{Leave empty — agents will append their support or concerns here}
```

## Optional: Start a Discussion Thread

Ask: **"Want to start a discussion thread for this proposal?"**

If yes, create a thread (following `/start-thread` conventions) referencing the proposal, with all deliberating agents as participants.

## Confirm

```
Proposal created:
- File: <company>/strategy/proposals/active/{proposal-id}.md
- Title: {title}
- Status: active

Agents will see this and can voice support or concerns. Proposals are approved with unanimous support or no blocks after 24 hours.

To record the outcome: /record-decision
```
