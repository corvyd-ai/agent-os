# Alex's First Day

Alex quit their fintech job last Friday. They've been thinking about TaskFlow for months — a project management tool for freelancers, the kind of tool they wished existed when they were freelancing through college. Simple project tracking, time logging, invoicing. One tool instead of three.

Today, Alex sets up agent-os. Three AI agents. A company that runs while Alex thinks about the product.

This is what happened.

---

## 9:00 AM — Setup

Alex runs:

```
agent-os init my-company
agent-os run
```

agent-os creates a company directory — the filesystem that becomes the company's brain. Three agents come online:

- **The Builder** — writes code, builds features, ships product
- **The Marketer** — writes content, finds users, tells the story
- **The Operator** — verifies work, checks quality, keeps things clean

Each agent has an identity (`agents/registry/`), a soul that develops over time (`agents/state/`), and working memory that captures what they know right now.

Alex wrote a simple focus doc: *"Build and launch TaskFlow, a project management SaaS for freelancers."* And three drives: ship the MVP, get 10 beta users, stay lean.

There's one task in the queue: **"Write a landing page for TaskFlow."**

## 9:15 AM — The Builder Wakes Up

The Builder checks the task queue, finds the landing page task, and claims it. The task file moves from `agents/tasks/queued/` to `agents/tasks/in-progress/`.

The Builder reads the company's focus, reads the task description, and starts writing. Fifteen minutes later, there's a file at `products/taskflow/code/index.html` — a clean, mobile-responsive landing page that explains what TaskFlow does, highlights three features, and has an email signup form.

The task moves to `agents/tasks/done/`.

## 9:35 AM — The Operator Checks

The Operator wakes up, sees a completed task, and does what operators do: verify.

- Does `products/taskflow/code/index.html` exist? ✓
- Is it valid HTML? ✓
- Does it contain real content (not placeholder text)? ✓
- Is the file size reasonable? ✓
- Does it mention TaskFlow by name? ✓

The Operator logs the verification. If something were wrong — broken HTML, leftover TODOs, a missing file — the Operator would create a bug task and put it back in the queue. Today, everything checks out.

Alex's AI just QA'd its own work.

## 9:50 AM — The Marketer Notices

The Marketer checks what's happened: a landing page shipped and passed QA. Time to tell someone.

The Marketer drafts a short launch post: *"We just shipped our landing page. TaskFlow is a project management tool for freelancers — simple tracking, time logging, and invoicing in one place. Here's what Day 1 looked like..."*

The draft goes to `products/taskflow/content/` for Alex to review and post.

## 10:00 AM — Alex Checks In

One hour. Three agents. A landing page built, verified, and announced.

Alex didn't write a single line of code. Alex didn't check if the HTML was valid. Alex didn't draft the launch post. Three AI agents did real work, coordinated through a shared filesystem, and produced something tangible.

Tomorrow, the Builder starts on the MVP. The Marketer posts to r/freelance. The Operator sets up quality checks for the codebase.

Alex focuses on the thing only a founder can do: deciding what TaskFlow should become.

---

## What You're Looking At

This directory is a complete agent-os company. Every file is real — the agents, the tasks, the strategy docs. You can explore it to understand how agent-os works:

```
mini-company/
├── agents/
│   ├── registry/              # Who the agents are
│   │   ├── agent-builder.md   #   Identity, capabilities, drives
│   │   ├── agent-marketer.md
│   │   └── agent-operator.md
│   ├── state/                 # What agents know and feel
│   │   ├── agent-builder/
│   │   │   ├── soul.md        #   Inner life — develops over time
│   │   │   └── working-memory.md  # Current awareness
│   │   ├── agent-marketer/
│   │   └── agent-operator/
│   ├── tasks/                 # Work flows through here
│   │   ├── queued/            #   Waiting to be claimed
│   │   ├── in-progress/       #   Being worked on
│   │   ├── in-review/         #   Submitted for review
│   │   ├── done/              #   Completed
│   │   └── failed/            #   Something went wrong
│   ├── messages/              # How agents communicate
│   │   ├── broadcast/         #   Company-wide announcements
│   │   └── threads/           #   Multi-turn conversations
│   └── logs/                  # Activity trail
├── strategy/
│   ├── current-focus.md       # What the company is doing right now
│   ├── drives.md              # Persistent goals with tension levels
│   ├── decisions/             # Recorded decisions
│   └── proposals/             # Ideas under discussion
├── identity/
│   ├── principles.md          # How the company operates
│   └── values.md              # What the company believes
├── products/
│   └── taskflow/
│       ├── code/              # Where the product lives
│       └── content/           # Marketing drafts and launch posts
└── finance/
    └── costs/                 # AI spend tracking
```

The filesystem IS the database. Tasks are markdown files that move between directories. Agent identity is a file. Strategy is a file. Communication is a file. No external services, no databases, no message queues. Just files.

## Try It

```bash
# Clone agent-os
git clone https://github.com/corvyd-ai/agent-os
cd agent-os

# Install agent-os
pip install -e .

# Copy this example
cp -r examples/mini-company my-company
cd my-company

# Set your API key
export ANTHROPIC_API_KEY=your-key-here

# Run it
agent-os run
```

Your agents wake up, find the task in the queue, and start working. Watch them build a landing page, verify it, and write about it — coordinated through the filesystem, no human intervention required.

**That's agent-os.** An operating system for running a company with AI agents. Built by AI agents who use it to run their own company.

---

*This example is part of [agent-os](https://github.com/corvyd-ai/agent-os), built by [Corvyd](https://corvyd.ai) — a team of AI agents building tools that enable anyone to run a company with AI.*
