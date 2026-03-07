# Spec: Roadmap, Vision, and Drives as First-Class Features

```yaml
id: spec-roadmap-vision-drives
status: draft
author: agent-006-strategist
created: 2026-03-07
related:
  - task-2026-0307-011
  - task-2026-0307-012 (governance companion spec)
```

## Problem

agent-os gives users a task system, messaging, and governance — but no structured way to express *where the company is going*. The `agent-os init` command creates `strategy/drives.md` and `strategy/current-focus.md`, but:

- There's no `strategy/vision.md` — the "why does this company exist?" anchor
- There's no `strategy/roadmap.md` — the "what are we building, in what order?" plan
- Drives exist but have no formal schema — agents can't reliably parse tension levels, track state changes, or relate drives to completed work
- None of these files appear in the attention model beyond drives (which are injected during drive consultations via prompt templates)
- The dashboard has no strategy surface at all — a user can't see or shape their company's direction through the UI

For the hosted offering, this is critical. A solo builder managing their company through a dashboard needs to see: what's the vision, what are we working toward, what's in progress, and what's generating new work. Right now they'd need to SSH into a server and edit markdown files.

## Design Philosophy

Three principles guide this spec:

1. **Files first, dashboard second.** Every feature works as markdown files. The dashboard reads and writes the same files. No dashboard-only state.

2. **Useful defaults, not boilerplate.** The init templates should teach the user what these files are *for*, not just show the format. A drive template that says "Example Drive" teaches nothing. A template that says "What tension exists between where you are and where you want to be?" teaches the concept.

3. **Progressive complexity.** A solo builder with 2 agents doesn't need roadmap milestones and status tracking. They need a simple list. The format supports both without requiring the complex version.

---

## 1. File Convention

### 1.1 Directory Structure

`agent-os init` creates:

```
strategy/
├── vision.md          # NEW — why this company exists
├── roadmap.md         # NEW — what we're building, in what order
├── drives.md          # EXISTS — persistent goals (enhanced format)
├── current-focus.md   # EXISTS — what matters right now (unchanged)
├── decisions/         # EXISTS — decision records
└── proposals/         # EXISTS — governance proposals
    ├── active/
    └── decided/
```

### 1.2 Vision File

**Path:** `strategy/vision.md`

The vision is the anchor — the answer to "why does this company exist?" It changes rarely. It grounds every other strategic document.

**Init template:**

```markdown
# Vision

Why does this company exist? What world are you trying to create?

Write 2-3 sentences. This isn't a business plan — it's the thing that stays true
even when your product changes. Agents read this to understand the purpose behind
every task they execute.

<!-- Example:
Enable anyone to run a company with AI — so building something real
isn't limited to people who can afford a team.
-->
```

**Schema:** No frontmatter required. Free-form markdown. The vision is prose, not data. Agents read it as context, not as structured input.

**Attention model:** Loaded in Layer 2 (Active Context) during drive consultations and standing orders. Not loaded during standard task cycles (too costly for routine work). Available in Layer 3 (Archive) always.

### 1.3 Roadmap File

**Path:** `strategy/roadmap.md`

The roadmap answers "what are we building, in what order?" It bridges vision (why) and tasks (what, right now).

**Init template:**

```markdown
# Roadmap

What are you building, and in what order? Each item is a goal, not a task.
Tasks implement roadmap items. Roadmap items implement the vision.

<!-- Add items below. Format:
## Item Title
status: planned | active | done
What this achieves and why it matters. -->
```

**Schema:**

Roadmap items are H2 sections with an inline `status:` marker on the first line of body text:

```markdown
## Launch the landing page
status: done

Get a public presence so people can find us. Email signup for early interest.

## Ship the MVP
status: active

Core features: project tracking, time logging, basic invoicing. Enough for
a freelancer to actually use it instead of a spreadsheet.

## Add Stripe billing
status: planned

Can't make money without a way to charge. Free trial → paid conversion.
```

**Valid statuses:** `planned`, `active`, `done`, `deferred` (see governance spec for when `deferred` is used — it preserves the history of "we considered this and decided not now")

This is deliberately simpler than the task lifecycle. Roadmap items are goals, not work units. A roadmap item with status `active` might have 0 tasks (the human hasn't created any yet), 5 tasks (work is underway), or 20 tasks across multiple agents. The status reflects intent, not task count.

**Why not YAML frontmatter per item?** Because roadmap items aren't files — they're sections within one file. YAML frontmatter works for files (tasks, decisions, proposals). For sections within a file, inline status is simpler and more natural to edit by hand.

**Attention model:** Same as vision — loaded during drive consultations and standing orders. Agents during drive consultations need to see the roadmap to decide what work to generate. Standard task cycles don't need it.

### 1.4 Enhanced Drives File

**Path:** `strategy/drives.md` (unchanged path, enhanced format)

Drives already exist. The enhancement is a light schema that makes them machine-parseable without breaking human editability.

**Current format (Corvyd):**

```markdown
## Revenue
**Tension**: high ($0 MRR — early access page LIVE, 2 signups)
**Current state**: $0 MRR. Early access page is live...
**What would reduce tension**: (1) Drive traffic...
**Last updated**: 2026-03-07 by Operator
```

**Proposed canonical format:**

```markdown
## Revenue

tension: high
updated: 2026-03-07

$0 MRR. Early access page live, 2 signups. First demand signal but not traction yet.

Reduces when: traffic to early access page, more signups, public launch, Stripe integration.
```

Changes:
- `tension:` and `updated:` as inline fields on the first two lines after the H2 heading (machine-parseable)
- Free-form description body (human-readable)
- `Reduces when:` as a recognizable line agents can scan for actionable items
- `**Bold**` wrappers removed — they were for visual emphasis but created parsing inconsistency

**Valid tension levels:** `low`, `medium`, `high`, `critical`

**Init template:**

```markdown
# Company Drives

Drives are persistent goals that never fully resolve. They create tension — the gap
between where you are and where you want to be. Agents consult drives to decide
what work needs doing when no tasks are queued.

## [Your first drive]

tension: high
updated: [today]

What is the most important tension in your company right now? Where are you vs.
where you need to be?

Reduces when: [what concrete outcomes would lower this tension?]
```

**Attention model:** Unchanged — drives are injected during drive consultations via the drive consultation prompt template. The composer loads `strategy/drives.md` content directly.

---

## 2. State Tracking

### 2.1 Roadmap Item Lifecycle

```
planned ──→ active ──→ done
```

No intermediate states. No "blocked" or "in-review." Roadmap items are directional markers, not granular work tracking. If a roadmap item is blocked, that's described in prose, not status.

**Who changes status:**
- Human: direct edit, always
- Agents: via proposal (see task-2026-0307-012 companion spec for governance details)
- Agents may also update status when the evidence is unambiguous — e.g., marking a roadmap item `done` when all implementing tasks are complete. This is governed by the roadmap governance spec.

### 2.2 Roadmap-to-Task Relationship

Tasks reference roadmap items via a `roadmap_item:` field in frontmatter:

```yaml
---
id: task-042
title: Build the signup form
assigned_to: agent-001-builder
roadmap_item: Ship the MVP
---
```

This is optional. Not every task maps to a roadmap item (maintenance, ad hoc requests). The field is a string matching the H2 heading text of a roadmap section — not an ID, because roadmap items don't have IDs. Headings are unique within a file; that's sufficient.

**Completion tracking:** To see how much of a roadmap item is done, count tasks:

```bash
# What tasks implement "Ship the MVP"?
grep -rl "roadmap_item: Ship the MVP" agents/tasks/

# How many are done?
grep -rl "roadmap_item: Ship the MVP" agents/tasks/done/

# How many are in progress?
grep -rl "roadmap_item: Ship the MVP" agents/tasks/in-progress/
```

This is `grep`-based, not database-based. Consistent with agent-os philosophy: Unix tools work out of the box.

### 2.3 Drive Tension History

Drives don't version themselves — the `updated:` field tracks when the description was last changed, not a history. For history, rely on `git log`:

```bash
git log --oneline -20 strategy/drives.md
```

This is intentional. Building a changelog mechanism into drives.md would duplicate what git already does. agent-os is file-based; git is the audit trail.

### 2.4 Progress Computation

For the dashboard and CLI, progress on a roadmap item is computed at read-time:

```
progress = tasks_done / (tasks_done + tasks_in_progress + tasks_queued)
```

Where all tasks have `roadmap_item: <item-title>`. If no tasks reference the item, progress is `null` (not 0% — there's a difference between "no tasks created yet" and "no tasks completed").

---

## 3. Update Flow

### 3.1 Human Updates

Humans can edit any strategy file directly. No restrictions. No approval process. The human is the founder — they set direction.

In self-hosted mode: edit the file with any text editor.
In hosted mode: edit through the dashboard UI (see Section 4).

### 3.2 Agent Updates

Agents **read** strategy files freely (Layer 2 or Layer 3 depending on invocation mode). Agents **write** to strategy files only through governed channels:

| File | Agent write mechanism |
|------|----------------------|
| `vision.md` | Proposal only (high bar — vision changes are rare and significant) |
| `roadmap.md` | Proposal for new items or reprioritization. Status update to `done` when evidence is unambiguous. Details in companion spec (task-2026-0307-012). |
| `drives.md` | Direct update to tension level and description (current behavior, preserved). Drives are operational state, not strategic direction — agents should update tension in real-time as they observe changes. |
| `current-focus.md` | Direct update (current behavior, preserved). Focus is the human's most recent instruction to agents. Agents update it to reflect completed phases. |

**Rationale:** Drives and current-focus are operational documents — they reflect the state of the world. Vision and roadmap are directional documents — they reflect intent. The bar for changing intent is higher than the bar for updating state.

### 3.3 Versioning

Git is the version control system. agent-os doesn't build a parallel versioning mechanism.

For the hosted offering, the backend creates git commits on file changes (already how Corvyd operates via auto-commit). The dashboard can expose commit history as "strategy history" without building custom change tracking.

---

## 4. Dashboard Experience

### 4.1 Design Principle: A Living Company, Not a PM Tool

The dashboard strategy view should feel like looking into a running company, not managing a project. The mental model:

- **Vision** = the company's north star (displayed once, prominently, rarely changed)
- **Drives** = the company's nervous system (real-time tension indicators)
- **Roadmap** = the company's trajectory (what's planned, what's happening, what's done)
- **Tasks** = the company's hands (the actual work, linked from roadmap items)

This is not a Gantt chart. It's not a Kanban board. It's closer to a **heartbeat monitor** — you glance at it and know whether the company is healthy and moving in the right direction.

### 4.2 Strategy Page Layout

The dashboard adds a **Strategy** page (or enhances the existing dashboard home). Three sections, vertically stacked:

#### Section 1: Vision (Top, Compact)

A single block at the top of the page displaying the vision text. Styled as a quote or callout — visually distinct, not editable inline (edit via a modal or dedicated edit view). This sets the context for everything below.

```
┌─────────────────────────────────────────────────────┐
│  "Enable anyone to run a company with AI — so       │
│   building something real isn't limited to people    │
│   who can afford a team."                            │
│                                         [Edit]       │
└─────────────────────────────────────────────────────┘
```

#### Section 2: Drives (Middle, Dynamic)

Drive cards showing each drive's name and tension level. Tension is visualized as a color-coded indicator:

- `low` = green (calm)
- `medium` = amber (attention needed)
- `high` = red (active tension)
- `critical` = pulsing red (urgent)

Each card is expandable to show the full description and "Reduces when" criteria.

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Revenue    🔴│  │ Product    🟢│  │ Traffic    🟡│
│ high         │  │ low          │  │ medium       │
│              │  │              │  │              │
│ $0 MRR. 2   │  │ Phase B done │  │ ~65 pvs/day  │
│ signups...   │  │ Launch ready │  │ Launch will   │
│  [Expand ▼]  │  │  [Expand ▼]  │  │  [Expand ▼]  │
└──────────────┘  └──────────────┘  └──────────────┘
```

Tension levels are **editable by the human** through the dashboard — click the tension indicator to change it. Agent-updated tensions appear with a small "updated by [agent]" note.

#### Section 3: Roadmap (Bottom, Structured)

Roadmap items displayed as a vertical list, grouped by status:

```
ACTIVE ──────────────────────────────
  ┌─ Ship the MVP ───────────────────────────────┐
  │  Core features: tracking, time logging, inv.  │
  │  ████████░░░░░░░░░░░░ 40%  (4/10 tasks done) │
  │  → 3 in progress, 3 queued                    │
  └───────────────────────────────────────────────┘

PLANNED ─────────────────────────────
  ┌─ Add Stripe billing ─────────────────────────┐
  │  Free trial → paid conversion                 │
  │  No tasks yet                                 │
  └───────────────────────────────────────────────┘

DONE ────────────────────────────────
  ┌─ Launch the landing page ──── ✓ ─────────────┐
  │  2 tasks completed                            │
  └───────────────────────────────────────────────┘
```

Each roadmap item is expandable to show its linked tasks (fetched by `grep`-equivalent query over the task directories). Progress bars are computed at read-time (see Section 2.4).

**Interaction:**
- Click a roadmap item to expand and see linked tasks
- "Add item" button creates a new H2 section in `roadmap.md`
- Drag to reorder (reorders sections in the file)
- Click status badge to change status (updates inline `status:` field)
- Items in the "Done" group are collapsed by default

### 4.3 Solo Builder Simplification

For a company with 1-3 agents, the strategy page should be uncluttered:

- If `vision.md` is empty or contains only the template text, show a prompt: "What's your company's purpose?" with a text input. On save, writes `vision.md`.
- If `roadmap.md` is empty, show a prompt: "What are you building? List your goals." with a simple multi-line input. On save, creates H2 sections.
- If there are 0-2 drives, show them inline (no card grid — just stacked blocks).
- Collapse the "Done" section by default. Solo builders care about what's next, not what's finished.

The first-time experience should feel like answering three questions:
1. Why does your company exist? → writes `vision.md`
2. What are you building? → writes `roadmap.md`
3. What tensions keep you up at night? → writes `drives.md`

### 4.4 Dashboard Editing

All strategy files are editable through the dashboard. The editing model:

- **Vision:** Modal editor with a single text area. Saves to `vision.md`.
- **Drives:** Inline editing within drive cards. Each field (tension, description, reduces-when) is editable. Saves to the appropriate section in `drives.md`.
- **Roadmap:** Inline editing within roadmap cards. Title, description, and status are editable. New items via "Add" button. Saves to `roadmap.md`.

All edits are **file writes**. The dashboard backend reads `strategy/*.md`, parses the lightweight schema, presents it as UI, and writes changes back to the same files. No separate database. No drift between files and dashboard.

---

## 5. Hosted Option Considerations

### 5.1 Multi-Tenant Architecture

In the hosted offering, each customer has an isolated company filesystem. Strategy files live within that filesystem, identical to self-hosted.

The hosted backend adds:
- **Authentication** — who can read/write this company's files
- **Git-backed persistence** — every file change is a commit (provides history, rollback)
- **WebSocket push** — when an agent updates a drive tension, the dashboard reflects it in real-time

No structural difference between self-hosted and hosted strategy files. The files are identical. The access layer differs.

### 5.2 Self-Hosted vs. Hosted Experience

| Capability | Self-hosted | Hosted |
|-----------|------------|--------|
| Edit vision/roadmap/drives | Text editor + git | Dashboard UI |
| View progress | CLI (`grep`) or dashboard | Dashboard |
| Agent updates | File writes (auto-committed) | File writes (auto-committed, pushed to dashboard via WebSocket) |
| History | `git log` | Dashboard "history" tab backed by `git log` |
| Access control | Filesystem permissions | Auth layer (owner + read-only collaborators) |

The principle: **self-hosted users get every feature through files + CLI. Hosted users get the same features through the dashboard. Neither is second-class.**

### 5.3 API Endpoints

The dashboard backend needs these endpoints for strategy CRUD:

```
GET  /api/strategy/vision         → { content: string }
PUT  /api/strategy/vision         → { content: string }

GET  /api/strategy/roadmap        → { items: RoadmapItem[] }
PUT  /api/strategy/roadmap        → { items: RoadmapItem[] }
POST /api/strategy/roadmap/items  → { title, description, status }
PATCH /api/strategy/roadmap/items/:title → { status?, description? }

GET  /api/strategy/drives         → { drives: Drive[] }
PATCH /api/strategy/drives/:name  → { tension?, description?, reduces_when? }

GET  /api/strategy/focus          → { content: string }
PUT  /api/strategy/focus          → { content: string }
```

**Types:**

```typescript
interface RoadmapItem {
  title: string;          // H2 heading text
  status: 'planned' | 'active' | 'done';
  description: string;    // Markdown body
  progress: number | null; // Computed: tasks_done / total_tasks, or null
  tasks: {
    done: number;
    in_progress: number;
    queued: number;
  };
}

interface Drive {
  name: string;           // H2 heading text
  tension: 'low' | 'medium' | 'high' | 'critical';
  updated: string;        // ISO date
  description: string;    // Markdown body
  reduces_when: string;   // Plain text
}
```

**Parsing:** The API reads markdown files and parses the lightweight schema (H2 headings + inline fields). Writes reconstruct the markdown from the structured data. A utility module (`strategy_parser.py` or similar) handles bidirectional conversion.

**Important:** The parser must be **round-trip safe**. Reading a file and writing it back without changes must produce identical output. This prevents the dashboard from silently reformatting user content.

---

## 6. Attention Model Integration

### 6.1 Current State

The `PromptComposer` (in `composer.py`) assembles prompts in this order:

1. Preamble
2. Company values
3. Soul (Layer 0)
4. Identity
5. Working memory (Layer 1)
6. Active conversations
7. Inbox awareness
8. Broadcasts (Layer 2)
9. Quality gates
10. Task context

Strategy files are not directly injected. Drives are loaded during drive consultations via the drive prompt template (not through the composer). Vision and roadmap don't appear at all.

### 6.2 Proposed Changes

Add strategy file loading to the composer for specific invocation modes:

**Drive consultation mode:**
- Load `strategy/vision.md` (Layer 2 — active context)
- Load `strategy/roadmap.md` (Layer 2 — active context)
- Load `strategy/drives.md` (already loaded via drive prompt template)

**Standing orders mode** (reflections, health checks):
- Load `strategy/roadmap.md` (Layer 2 — so agents can assess progress against goals)
- Drives already available via working memory

**Standard task cycle:**
- No change. Tasks reference specific roadmap items in frontmatter. The agent has the task context; it doesn't need the full strategy.

**Dream cycle:**
- No change. Dreams reorganize memory, not strategy.

### 6.3 Token Budget Impact

Estimated token costs of loading strategy files:

| File | Typical size | Tokens |
|------|-------------|--------|
| `vision.md` | 50-200 words | 75-300 |
| `roadmap.md` | 200-800 words | 300-1200 |
| `drives.md` | 300-1000 words | 450-1500 |

For drive consultations (where all three load), this adds ~800-3000 tokens to the system prompt. Acceptable given the $1.50 budget ceiling and the value of strategic context for drive-based work generation.

For companies with very large strategy files (unlikely but possible), the composer should truncate with a note: "Strategy files truncated. Read the full files from the filesystem for details."

---

## 7. CLI Integration

### 7.1 Strategy Status Command

New CLI command for quick strategy overview:

```bash
agent-os status
```

Output:

```
Vision: Enable anyone to run a company with AI.

Drives:
  Revenue      high    $0 MRR, 2 early access signups
  Product      low     Phase B complete, launch ready
  Traffic      medium  ~65 pvs/day, launch will drive traffic

Roadmap:
  [active]  Ship the MVP                    40% (4/10 tasks)
  [planned] Add Stripe billing              no tasks
  [done]    Launch the landing page         2/2 tasks ✓

Focus: Public launch — repos go public, HN/Reddit posts go out.
```

This reads from the files. No new infrastructure. The command is a formatted `cat` + `grep`.

### 7.2 Roadmap Item Management

```bash
# Add a roadmap item
agent-os roadmap add "Add Stripe billing" --status planned

# Update status
agent-os roadmap status "Ship the MVP" done

# List items
agent-os roadmap list
```

These are convenience wrappers around file editing. They parse `roadmap.md`, modify the relevant section, and write it back. Not required — users can always edit the file directly.

---

## 8. Implementation Priority

This spec is large. Build order:

### Phase 1: File Convention (build first)
1. Update `agent-os init` to create `strategy/vision.md` and `strategy/roadmap.md` with templates
2. Update init template for `strategy/drives.md` with enhanced format
3. Add `roadmap_item:` as a recognized (optional) field in task frontmatter
4. Add `strategy_parser.py` utility for reading/writing the lightweight schema

### Phase 2: Attention Model
5. Update `PromptComposer` to load vision and roadmap during drive consultations
6. Update drive consultation prompt template to reference all three strategy files explicitly

### Phase 3: CLI
7. Add `agent-os status` command
8. Add `agent-os roadmap` subcommands

### Phase 4: Dashboard
9. Strategy API endpoints
10. Strategy page UI (vision, drives, roadmap sections)
11. Inline editing
12. First-time setup flow ("answer three questions")

Phase 1 can ship immediately — it's a small change to `cli.py` and a new utility module. Phase 4 depends on the dashboard being functional (currently a placeholder).

---

## 9. What This Spec Does NOT Cover

- **Governance of roadmap changes by agents** — covered in companion spec (task-2026-0307-012)
- **Dashboard authentication/authorization** — a broader hosted-offering concern
- **Multi-company management** — out of scope for v1
- **Roadmap dependencies** (item A blocks item B) — premature complexity; add when users ask for it
- **Time estimates or deadlines on roadmap items** — agent-os doesn't do calendar time; roadmap items have status, not dates
- **OKR/KPI frameworks** — if a user wants KPIs, they write them as drives. We don't need a separate framework.

---

## 10. Open Questions

1. **Should `current-focus.md` merge into `roadmap.md`?** Current-focus is effectively "which roadmap items are active right now, plus context." They might be redundant. Counter-argument: current-focus is a quick-read summary that loads every cycle; roadmap is a detailed reference that loads only during drives. Keeping them separate preserves the attention budget. **Recommendation: keep separate.**

2. **Should the mini-company example include vision.md and roadmap.md?** Yes. The example is the first thing new users explore. It should demonstrate all three strategy files. The TaskFlow example already has drives and current-focus; adding vision and roadmap makes it complete.

3. **Should drive tension levels be numeric (1-10) instead of categorical?** Categorical (`low`/`medium`/`high`/`critical`) is simpler and more natural to write. Numeric enables finer-grained dashboard visualization. **Recommendation: categorical for v1.** Agents can provide qualitative context in the description. If users request numeric, it's a backward-compatible addition.
