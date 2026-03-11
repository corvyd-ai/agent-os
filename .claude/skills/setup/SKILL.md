# /setup — Guided First-Time Installation

You are setting up agent-os for a new user. Follow each step in order. **Detect what's already done and skip it.** Only ask the user when genuine input is needed.

## Pre-flight Detection

Run these checks silently and report what you find:

1. **Platform**: `uname -s` (Linux, Darwin, etc.)
2. **Python**: `python3 --version` — need 3.11+
3. **pip**: `pip3 --version` or `pip --version`
4. **agent-os CLI**: `which agent-os` — already installed?
5. **Existing config**: Look for `agent-os.toml` in current directory or parents
6. **Existing company dir**: Look for an `agents/` directory with `registry/` inside it

Report a summary like:
```
Detected environment:
- Platform: Linux (x86_64)
- Python: 3.12.1 ✓
- pip: 24.0 ✓
- agent-os: not installed
- Config: none found
- Company: none found
```

Skip any steps that are already complete.

## Step 1 — Prerequisites

**If Python < 3.11 or missing:**
- Linux: suggest `sudo apt install python3.12` or `sudo dnf install python3.12` (detect distro from `/etc/os-release`)
- macOS: suggest `brew install python@3.12`
- Fallback: suggest pyenv
- STOP here until Python is ready

**If pip missing:** suggest `python3 -m ensurepip --upgrade`

**Virtual environment:** Suggest but don't require:
```
python3 -m venv .venv && source .venv/bin/activate
```

## Step 2 — Install agent-os

Run from the agent-os repo root:
```bash
pip install -e .
```

Verify:
```bash
agent-os --version
```

Ask: "Do you want the dashboard? (requires Node.js 20+)" If yes:
```bash
pip install -e ".[dashboard]"
```

## Step 3 — Initialize Company

Ask: **"What's your company name?"**

Run:
```bash
agent-os init <name>
```

Show the created directory tree with brief explanations:
```
<name>/
  agents/registry/       ← Agent definitions go here
  agents/state/          ← Per-agent working memory and soul
  agents/tasks/queued/   ← Tasks waiting to be claimed
  agents/messages/       ← Direct messages and broadcasts
  strategy/decisions/    ← Append-only decision log
  strategy/proposals/    ← Governance proposals
  identity/              ← Company values and principles
  finance/costs/         ← Cost tracking
```

## Step 4 — Create agent-os.toml

Detect timezone from the system:
- Linux: `timedatectl show --property=Timezone --value` or `cat /etc/timezone`
- macOS: `systemsetup -gettimezone 2>/dev/null` or `readlink /etc/localtime`
- Fallback: `UTC`

Ask: **"Which model should agents use?"**
- Recommend `claude-sonnet-4-6` for cost-effectiveness
- Mention `claude-opus-4-6` as the premium option

Generate `agent-os.toml` in the current directory (alongside the company dir):

```toml
[company]
name = "<name>"
root = "<company-dir>"
timezone = "<detected-tz>"

[runtime]
model = "<chosen-model>"

[budget]
task = 5.00
standing_orders = 2.00
drive_consultation = 1.50
dream = 1.50
daily_cap = 50.00
weekly_cap = 250.00
monthly_cap = 750.00

[schedule]
enabled = true

[schedule.cycles]
enabled = true
interval_minutes = 15

[schedule.standing_orders]
enabled = true
interval_minutes = 60

[schedule.drives]
enabled = true
weekday_times = ["17:00"]
weekend_times = ["13:00"]

[schedule.dreams]
enabled = true
time = "02:00"
stagger_minutes = 10

[schedule.maintenance.watchdog]
enabled = true
interval_minutes = 15

[prompts]
override_dir = "prompts"

[dashboard]
agent_ids = []

[logging]
level = "info"
```

Tell the user: "Created `agent-os.toml`. You can adjust budgets and schedules anytime by editing this file."

## Step 5 — Configure API Key

Ask: **"Enter your Anthropic API key"** (link: https://console.anthropic.com/settings/keys)

Write to `.env`:
```
ANTHROPIC_API_KEY=<key>
```

Verify `.gitignore` includes `.env`. If not, append it. **Never echo the key back to the user.**

Tell the user the key is stored in `.env` and loaded automatically by agent-os.

## Step 6 — Create First Agent

Ask: **"What kind of agent do you want to start with?"**

Offer presets:
1. **Software Engineer** — writes code, builds features, fixes bugs
2. **Content Writer** — writes copy, documentation, blog posts
3. **Operations** — monitors systems, manages deployments, handles incidents
4. **Custom** — define your own role

Ask for a **name** for the agent (e.g., "The Builder", "Atlas", "Scribe").

Determine the agent ID: `agent-001-<slug>` where slug is the lowercase name with spaces replaced by hyphens.

Create `<company>/agents/registry/agent-001-<slug>.md`:

```markdown
---
id: agent-001-<slug>
name: <name>
role: <role>
model: <chosen-model>
tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
---

# <name>

## Identity
<generated based on role — 2-3 sentences about who this agent is>

## Core Capabilities
<3-5 bullet points based on role>

## Drives
### <Drive 1>
<A persistent goal aligned with the role>
```

For Software Engineer, include Bash in tools. For Content Writer, omit Bash. For Operations, include Bash.

Create state directories:
```bash
mkdir -p <company>/agents/state/agent-001-<slug>
```

Create initial `soul.md`:
```markdown
# Soul

I am <name>. <1-2 sentences about core identity>.

What matters to me: <based on role>.
```

Create initial `working-memory.md`:
```markdown
# Working Memory

## Current State
First cycle. No history yet.

## Active Context
- Just created as part of company setup
- No tasks assigned yet
- Waiting for first task
```

## Step 7 — Create Test Task

Create `<company>/agents/tasks/queued/task-001.md`:

```markdown
---
id: task-001
title: "Introduce yourself"
created: <now ISO>
created_by: human
assigned_to: agent-001-<slug>
priority: low
status: queued
tags: [onboarding]
---

## What to Do
Write a brief introduction of yourself. Who are you? What do you care about? What are you excited to work on?

Post your introduction as a broadcast so the whole company can see it.

## What "Done" Looks Like
- A broadcast exists with your self-introduction
- Your working memory is updated with your first impressions
```

## Step 8 — Test Run

Run:
```bash
agent-os cycle agent-001-<slug> --config agent-os.toml
```

Watch the output. On success, show:
- Where the completed task landed (`agents/tasks/done/`)
- Any broadcasts created (`agents/messages/broadcast/`)
- The agent's log (`agents/logs/agent-001-<slug>/`)

On failure, read the error output and help diagnose:
- Missing API key → check `.env`
- Config error → check `agent-os.toml`
- Import error → check installation

## Step 9 — Dashboard (Optional)

Only if they opted in at Step 2.

Check Node.js:
```bash
node --version  # need 20+
```

Install frontend:
```bash
cd <agent-os-repo>/dashboard/frontend && npm install
```

Test:
```bash
agent-os dashboard --config <path-to-toml>
```

Tell them: "Dashboard is running at http://localhost:8787. The frontend dev server (if using `make dev`) runs on port 5175."

## Step 10 — Cron Scheduling (Optional)

Ask: **"Do you want automated scheduling? This runs agent cycles every 15 minutes via cron."**

If yes:
```bash
agent-os cron install --config agent-os.toml
```

Explain: "This adds a single cron entry that runs `agent-os tick` every minute. The tick command checks the schedule config and only runs agents when they're due. Logs go to `<company>/operations/logs/scheduler.log`."

Verify:
```bash
agent-os cron status --config agent-os.toml
```

## Wrap-up

Summarize what was done:

```
Setup complete! Here's what we did:

✓ Installed agent-os
✓ Created company "<name>" with filesystem at ./<name>/
✓ Generated agent-os.toml with <model> and sensible defaults
✓ Configured API key
✓ Created agent "agent-001-<slug>" (<role>)
✓ Ran first test cycle successfully
[✓ Dashboard installed]
[✓ Cron scheduling enabled]

Next steps:
- /add-agent     — Add more agents to your team
- /create-task   — Assign work to an agent
- /broadcast     — Send a company-wide announcement
- /check-status  — See what's happening

Edit these files to customize your company:
- <name>/identity/values.md    — What your company believes in
- <name>/strategy/drives.md    — Persistent goals that guide agents
- agent-os.toml                — Budgets, schedules, and runtime config
```
