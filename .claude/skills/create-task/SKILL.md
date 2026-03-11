# /create-task — Create a Task for an Agent

You are creating a task in an agent-os company. Tasks are markdown files with YAML frontmatter, placed in the `agents/tasks/queued/` directory.

## Prerequisites

Find the company root by looking for `agent-os.toml` in the current directory or parents. Read it to get `[company].root`. If no config found, ask the user where their company directory is.

## Detect Context

1. **List registered agents** — read all files in `<company>/agents/registry/` and show them:
   ```
   Available agents:
   - agent-001-builder (The Builder) — Software Engineer
   - agent-003-operator (The Operator) — Operations
   ```

2. **Check existing tasks today** — scan `<company>/agents/tasks/` (all subdirectories: queued, in-progress, in-review, done, failed, backlog, declined) for files matching today's date prefix to determine the next sequence number.

## Ask the User

If not already clear from their request:

1. **What needs to be done?** — Get a title and description. If the user gave a short description, expand it into a clear task with "What to Do" and "What Done Looks Like" sections.

2. **Which agent?** — Show the list from above. If only one agent exists, default to it. If unassigned, use `assigned_to: ""`.

3. **Priority** — Default to `medium`. Only ask if the context suggests it matters.
   - `critical` — Drop everything
   - `high` — Do this next
   - `medium` — Normal queue order
   - `low` — When you get to it

## Generate ID

Format: `task-YYYY-MMDD-NNN`

Use today's date. Scan ALL task subdirectories (queued, in-progress, in-review, done, failed, backlog, declined) for files with today's date prefix. Find the highest sequence number and increment. If none exist, start at 001.

## Create the File

Write to `<company>/agents/tasks/queued/{task-id}.md`:

```markdown
---
id: {task-id}
title: "{title}"
created: {ISO 8601 timestamp with timezone}
created_by: human
assigned_to: {agent-id}
priority: {priority}
status: queued
tags: [{relevant tags}]
---

## What to Do
{Clear description of what the agent should do}

## What "Done" Looks Like
{Acceptance criteria — what success means}

## Context
{Any background, links, or related information. Omit section if none.}
```

## Confirm

```
Created task:
- File: <company>/agents/tasks/queued/{task-id}.md
- Assigned to: {agent-name} ({agent-id})
- Priority: {priority}

The agent will pick this up on their next cycle. To run immediately:
  agent-os task {agent-id} {task-id} --config agent-os.toml
```
