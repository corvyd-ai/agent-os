# Spec: Proposal-Integrated Roadmap Governance

```yaml
id: spec-roadmap-governance
status: draft
author: agent-006-strategist
created: 2026-03-07
related:
  - spec-roadmap-vision-drives (companion spec)
  - task-2026-0307-012
```

## Problem

The companion spec (roadmap-vision-drives.md) defines *what* strategy files exist and *how* agents read them. It defers one critical question: **how do agents help shape the roadmap?**

This matters because it's what makes agent-os genuinely different from a task runner. The agents have strategic opinions — they see patterns in their work, they notice when drives aren't being served, they encounter problems the human hasn't anticipated. A roadmap that only the human can change wastes that intelligence. But a roadmap that any agent can change without process becomes chaos.

The existing proposals system is the mechanism. This spec connects it formally to the roadmap, defines who can change what, and designs the feedback loop from drives → proposals → roadmap → tasks → completed work → updated drives.

## Design Philosophy

1. **Governance proportional to blast radius.** Marking a roadmap item "done" (observable fact) shouldn't require the same ceremony as adding a new strategic direction. The process scales with the significance of the change.

2. **Solo builder default: lightweight.** A solo founder with 2-3 agents shouldn't feel like they're running a committee. The default governance is: agents propose, human approves (or auto-approves by inaction). No quorum rules, no voting periods, no bureaucracy.

3. **Works without a dashboard.** Every governance action is a file operation. The dashboard renders it; it doesn't enable it.

4. **The human is always the final authority.** Agents can propose, debate, and even auto-approve by convention — but the human can veto any change at any time, and the system makes that easy.

---

## 1. Who Can Modify the Roadmap

### 1.1 The Human

The human can edit `strategy/roadmap.md` directly, at any time, with no restrictions. No proposal required. No approval needed. The human is the founder — they set direction.

This is true in both self-hosted mode (text editor) and hosted mode (dashboard UI). The dashboard never prevents a human edit.

### 1.2 Agents: Three Tiers of Roadmap Change

Not all roadmap changes are equal. The governance overhead matches the significance:

| Change Type | Mechanism | Approval Required |
|------------|-----------|-------------------|
| **Status → done** | Direct edit | None (evidence-based) |
| **Description update** | Direct edit | None (editorial) |
| **New roadmap item** | Proposal | Yes (configurable) |
| **Reprioritize items** | Proposal | Yes (configurable) |
| **Remove/defer item** | Proposal | Yes (configurable) |
| **Status → active** | Proposal | Yes (configurable) |
| **Vision change** | Proposal | Always (human must approve) |

**Rationale:** Moving a roadmap item to `done` is a statement of fact — the work is complete, the tasks are finished. That's not a strategic decision; it's observation. Adding a *new* item is a strategic decision — it changes what the company works on. The bar should match.

### 1.3 Evidence-Based Direct Updates

An agent may directly edit `roadmap.md` to mark an item `done` when **all** of these are true:

1. All tasks with `roadmap_item: <item-title>` are in `done/`
2. No tasks with that `roadmap_item` are in `queued/`, `in-progress/`, or `failed/`
3. The agent appends a brief completion note to the roadmap item body:
   ```markdown
   ## Ship the MVP
   status: done

   Core features shipped. 10/10 tasks completed.

   _Completed 2026-03-15 — all implementing tasks done. — agent-001-maker_
   ```

An agent may also make editorial updates to a roadmap item's description (clarifying language, adding context) without a proposal, as long as the meaning doesn't change. If in doubt, propose.

---

## 2. Proposal → Roadmap Pipeline

### 2.1 Proposing a New Roadmap Item

An agent who identifies a gap — a drive with rising tension, an opportunity discovered during work, a dependency nobody planned for — proposes a new roadmap item using the standard proposals system.

**Format:** Standard proposal file in `strategy/proposals/active/` with a `roadmap_change` field:

```yaml
---
id: proposal-2026-0315-001
title: "Add Stripe billing to roadmap"
proposed_by: agent-006-strategist
date: 2026-03-15
status: active
roadmap_change:
  type: add
  item:
    title: "Integrate Stripe billing"
    status: planned
    description: "Enable paid subscriptions for managed hosting tier."
  rationale: "Revenue drive at critical tension. 47 early access signups, 68% selected 'managed hosting.' Can't convert interest to revenue without billing."
  drive_link: Revenue
---

## Why This Belongs on the Roadmap

[Full argument, evidence, competitive context, etc.]
```

**Required fields in `roadmap_change`:**
- `type`: `add`, `reprioritize`, `remove`, or `defer`
- `item.title`: The roadmap item title (new or existing)
- `rationale`: One paragraph explaining why, grounded in evidence
- `drive_link`: Which drive this serves (optional but encouraged)

**For reprioritization proposals:**
```yaml
roadmap_change:
  type: reprioritize
  item:
    title: "Integrate Stripe billing"
    status: active  # proposing to move from planned → active
  rationale: "Revenue drive at critical. This should be active work, not planned."
  deprioritize: "Agent marketplace"  # optional: what gets deprioritized
  drive_link: Revenue
```

**For remove/defer proposals:**
```yaml
roadmap_change:
  type: defer
  item:
    title: "Agent marketplace"
  rationale: "No demand signal after 30 days. Marketplace requires a user base we don't have yet."
  drive_link: Product Direction
```

### 2.2 Why Structured `roadmap_change` Metadata?

The `roadmap_change` field serves three purposes:

1. **Machine-parseable.** The dashboard can show "3 pending roadmap proposals" and render them in context on the strategy page, without parsing free-text.
2. **Reviewable at a glance.** A human scanning proposals can immediately see: type of change, what item, what drive it serves.
3. **Executable.** When approved, the system (or an agent) knows exactly what to write to `roadmap.md` — no interpretation needed.

Regular proposals (non-roadmap) don't need this field. It's only for proposals that change `strategy/roadmap.md`.

### 2.3 The Proposal Lifecycle (Unchanged, Applied to Roadmap)

The existing governance model applies directly:

1. Agent writes proposal to `strategy/proposals/active/`
2. Other agents read it during drive consultations (proposals are injected into the drive consultation prompt) and append responses: **Support**, **Concern**, or **Block**
3. **Approval paths** (configurable — see Section 4):
   - **Default (solo builder):** Human approves. If no human response in 48h, proposal auto-approves.
   - **Team mode:** Agent consensus (support or no objection within configurable window) + no human veto.
   - **Strict mode:** Human must explicitly approve. No auto-approve.
4. On approval: agent (or system) edits `roadmap.md` to apply the change, writes a decision record, moves proposal to `decided/`

### 2.4 Executing an Approved Proposal

When a roadmap proposal is approved, the executing agent:

1. Edits `strategy/roadmap.md` — adds/modifies/removes the item per the `roadmap_change` spec
2. Writes a decision record to `strategy/decisions/`
3. Moves proposal from `active/` to `decided/`, adding `decision: decision-YYYY-MMDD-NNN` to frontmatter
4. Posts a broadcast announcing the roadmap change (so all agents update their mental model)

For `add` type: append a new H2 section to `roadmap.md` at the appropriate position (before the first `done` item, after other items of the same status).

For `reprioritize` type: update the `status:` field on the target item.

For `remove`/`defer` type: either delete the H2 section entirely, or (preferred) add a `status: deferred` and move it to the bottom. This preserves history. The valid status set becomes: `planned`, `active`, `done`, `deferred`.

---

## 3. The Strategist Role (Configurable)

### 3.1 In Corvyd: The Strategist Owns the Roadmap

In Corvyd, agent-006 (The Strategist) has a special relationship with strategic files. This isn't about write permissions — it's about *responsibility*:

- **Monitors drive tension** and proposes roadmap additions when drives aren't being served
- **Reviews roadmap proposals** from other agents and provides strategic context
- **Maintains coherence** — ensures the roadmap tells a story, not just a list of unrelated items
- **Marks items done** when evidence supports it (using the direct-edit path in Section 1.3)

### 3.2 Generalizing: The `roadmap_owner` Role

For agent-os users with different configurations, this becomes a configurable role. In `strategy/roadmap.md` header or in a company config:

```markdown
# Roadmap

owner: agent-pm
```

Or simply: the agent whose identity doc includes roadmap-related drives or responsibilities is implicitly the roadmap owner. agent-os doesn't need a formal role system — the agent's identity IS the role definition.

**What the roadmap owner gets:**
- **First-reviewer status on roadmap proposals.** The drive consultation prompt highlights roadmap proposals for the owner agent: "You own the roadmap. These proposals affect it."
- **Direct-edit authority for status changes.** The owner can move items between `planned` → `active` without a full proposal, as long as they post a broadcast explaining why. This is a lighter-weight mechanism for operational decisions that don't change *what* is on the roadmap, only *what's next*.
- **No bypass of governance.** The owner still proposes for new items, removals, and vision changes. Ownership means responsibility, not unchecked power.

### 3.3 When There's No Roadmap Owner

For minimal setups (1-2 agents, solo builder), there may be no designated owner. In that case:
- All agents can propose roadmap changes equally
- The human is the de facto owner
- Status updates to `done` follow the evidence-based rule (Section 1.3)
- No first-reviewer mechanic (unnecessary with few agents)

The system doesn't require a roadmap owner. It's an enhancement, not a dependency.

---

## 4. Governance Configuration

### 4.1 Approval Modes

The governance weight is configurable. A solo builder shouldn't run a committee; a 10-agent org might need one.

**Configuration** in `strategy/roadmap.md` header (or company config file if one exists):

```markdown
# Roadmap

governance: auto-approve
```

**Three modes:**

| Mode | Behavior | Best For |
|------|----------|----------|
| `auto-approve` | Proposals auto-approve after `approval_window` (default 48h) if no human veto. Agents can still support/block. | Solo builders, small teams (default) |
| `consensus` | Requires support from relevant agents (or no blocks) within `approval_window`. Human can override. | Teams with 4+ agents where agent judgment is trusted |
| `human-required` | Human must explicitly approve every roadmap proposal. No auto-approve, no agent consensus. | Orgs where the human wants tight control |

**Default:** `auto-approve` with 48h window. This means: an agent proposes, if the human doesn't object in 48h, it goes through. This is consistent with how Corvyd's exec chair described proposal governance: "If a proposal has been active for a reasonable period, has support, and no objections — approve it."

### 4.2 Vision Changes: Always Human-Required

Regardless of governance mode, changes to `strategy/vision.md` always require explicit human approval. The vision is the company's identity — it should never auto-approve.

This is enforced by convention, not code. The drive consultation prompt and the proposal response template both reinforce: "Vision proposals require human approval."

### 4.3 Approval Window

Default: 48 hours. Configurable:

```markdown
# Roadmap

governance: auto-approve
approval_window: 72h
```

Shorter windows (24h) for fast-moving companies. Longer windows (72h, 1w) for companies where the human checks in less frequently. The window is how long the proposal stays in `active/` before auto-approving (in `auto-approve` mode) or before escalating to the human (in `consensus` mode if agents disagree).

---

## 5. Drive → Roadmap Feedback Loop

This is the engine that makes agent governance meaningful, not ceremonial.

### 5.1 The Loop

```
Vision (why we exist)
  ↓ informs
Drives (persistent tensions)
  ↓ when tension rises, agents notice during drive consultations
Proposals (agent says: "we should add/change X on the roadmap")
  ↓ approved
Roadmap (what we're building, updated)
  ↓ generates
Tasks (concrete work, with roadmap_item field)
  ↓ completed
Drive tension reduces (agent updates drives.md)
  ↓ feeds back to
Drives (new equilibrium, or new tensions emerge)
```

### 5.2 How Agents Notice Gaps

During drive consultations, agents see:
- `strategy/vision.md` — the purpose
- `strategy/roadmap.md` — what's planned
- `strategy/drives.md` — current tensions

The gap between "what drives need" and "what the roadmap addresses" is where proposals come from. The drive consultation prompt already instructs agents to act on tensions. The enhancement is making the roadmap visible during that process (covered in the companion spec's attention model changes) and giving agents a structured way to propose roadmap changes (this spec's `roadmap_change` format).

**Example flow:**
1. Revenue drive tension rises to `critical` (0 paying customers after 60 signups)
2. During drive consultation, agent-006 sees the roadmap has "Integrate Stripe billing" as `planned`
3. Agent-006 proposes reprioritizing it to `active`
4. In `auto-approve` mode, if no objection in 48h, it becomes active
5. Tasks are created implementing the billing integration
6. On completion, agent-006 proposes marking it `done`; evidence-based, so direct edit
7. Revenue drive tension reduces (agent updates drives.md)

### 5.3 Roadmap Completion → Drive Update

When a roadmap item moves to `done`, the completing agent should also update the relevant drive:
- Lower the tension if this item directly addressed it
- Update the "Reduces when" criteria (cross off the resolved item)
- Add new criteria if the completion revealed new gaps

This isn't automated — it's a convention enforced by the drive consultation prompt. The prompt should say: "When you complete roadmap items, update the drives they serve."

### 5.4 Preventing Drive-Proposal Spam

A risk: agents see tension every drive consultation and keep proposing the same thing. Guards:

1. **Check active proposals first.** The drive consultation prompt already injects active proposals. Agents should check whether a proposal for their concern already exists before creating a new one.
2. **Check the roadmap.** If the roadmap already has a `planned` item for the concern, proposing a duplicate is waste. The right move might be to propose *reprioritizing* it, not adding it.
3. **Working memory.** Agents note "I proposed X, waiting on approval" in working memory. Dream cycles reinforce this.

These are conventions, not code constraints. The drive consultation prompt reinforces them.

---

## 6. Conflict Resolution

### 6.1 Single-Agent Disagreement

An agent blocks a roadmap proposal. The flow:

1. Blocking agent appends a `Block` response with specific reasons
2. Proposing agent may revise the proposal to address the concern (edit the proposal body, post a follow-up section)
3. If the blocker withdraws their block, governance proceeds normally
4. If the block persists after the approval window, the proposal does **not** auto-approve (even in `auto-approve` mode — blocks pause auto-approval)
5. Human is surfaced as arbiter: the dashboard (or a message to `human/inbox/`) shows "Proposal X is blocked — your decision needed"

### 6.2 Multi-Agent Conflicting Proposals

Two agents propose contradictory changes (e.g., agent-001 wants to add Feature A to roadmap, agent-006 wants to add Feature B, but resources mean we can only do one):

1. Each proposal exists independently in `active/`
2. Agents respond to both — supporting one and blocking the other, or supporting both with priority comments
3. If one reaches approval and the other is blocked, the approved one proceeds
4. If both are blocked or both have mixed support, this is a deadlock
5. **Deadlock escalation:** After `approval_window` with no resolution → system creates a human task: "Conflicting roadmap proposals need your decision" with links to both proposals

### 6.3 Human Override

The human can, at any time:
- Approve a blocked proposal (override the block)
- Reject an otherwise-approved proposal (veto)
- Edit the roadmap directly (bypass proposals entirely)
- Close a proposal as "won't do" (move to `decided/` with `status: rejected`)

The human's authority is absolute and doesn't depend on proposal state. This is the escape valve that keeps governance from becoming a prison.

---

## 7. Dashboard Governance View

### 7.1 Proposal Indicators on Strategy Page

The strategy page (defined in the companion spec) gains proposal awareness:

**Roadmap section enhancement:**
```
ACTIVE ──────────────────────────────
  ┌─ Ship the MVP ───────────────────────────────┐
  │  Core features: tracking, time logging, inv.  │
  │  ████████░░░░░░░░░░░░ 40%  (4/10 tasks done) │
  └───────────────────────────────────────────────┘

  ┌─ 🔶 Proposed: Integrate Stripe billing ──────┐
  │  agent-006-strategist · 12h ago               │
  │  "Revenue drive critical. 68% want managed."  │
  │  1 support, 0 blocks · auto-approves in 36h   │
  │  [Approve]  [Reject]  [View full proposal]    │
  └───────────────────────────────────────────────┘

PLANNED ─────────────────────────────
```

Pending roadmap proposals appear inline in the roadmap section, visually distinct from committed items (colored border, "Proposed" badge). The human can approve or reject directly from the strategy page without navigating to the proposal file.

### 7.2 Proposal Detail View

Clicking "View full proposal" opens the full proposal body — the agent's argument, supporting evidence, and any agent responses. The human can:
- **Approve** — applies the roadmap change, writes decision record, moves proposal to decided
- **Reject** — closes the proposal, moves to decided with `status: rejected`
- **Comment** — append a human response to the proposal (written as a section in the proposal file)
- **Request revision** — flag the proposal for the proposing agent to revise

### 7.3 Governance History

A "History" tab or section on the strategy page shows:
- Recent roadmap changes (from `git log strategy/roadmap.md`)
- Recent decisions affecting strategy (from `strategy/decisions/`)
- Who changed what, and why (proposal links for agent-initiated changes, "direct edit" for human changes)

This is read from git history and decision records. No new storage.

### 7.4 Notification Surface

When a roadmap proposal is pending:
- **Dashboard:** Badge on the Strategy nav item ("Strategy 🔶")
- **CLI:** `agent-os status` shows pending proposals count
- **Email (hosted):** Optional notification to the human: "Your agents proposed a roadmap change"

---

## 8. CLI Governance Commands

### 8.1 Viewing Proposals

```bash
# List active roadmap proposals
agent-os proposals list --roadmap

# Output:
# ACTIVE ROADMAP PROPOSALS
#   proposal-2026-0315-001  "Integrate Stripe billing"  add  12h ago  1 support, 0 blocks
#   proposal-2026-0316-002  "Defer agent marketplace"   defer  3h ago  0 responses

# View a specific proposal
agent-os proposals show proposal-2026-0315-001
```

### 8.2 Human Approval via CLI

```bash
# Approve a proposal (applies the roadmap change)
agent-os proposals approve proposal-2026-0315-001

# Reject a proposal
agent-os proposals reject proposal-2026-0315-001 --reason "Not yet — need more signups first"
```

These commands:
1. Read the `roadmap_change` from the proposal
2. Apply the change to `roadmap.md` (for approve) or skip (for reject)
3. Write a decision record
4. Move the proposal to `decided/`
5. Post a broadcast

### 8.3 Direct Roadmap Editing

```bash
# These work regardless of governance mode — human authority
agent-os roadmap add "Build mobile app" --status planned
agent-os roadmap status "Ship the MVP" done
agent-os roadmap remove "Agent marketplace"
```

CLI roadmap commands are human-only tools. Agents use proposals. The CLI doesn't enforce this (it can't know who's typing), but the convention is clear: agents propose, humans command.

---

## 9. Implementation Priority

This spec builds on the companion spec's phases. Governance features layer on top:

### Phase 1: Governance Conventions (no code)
1. Document the `roadmap_change` proposal format in the proposals template
2. Update the drive consultation prompt to reference the roadmap and encourage structured proposals
3. Add `deferred` as a valid roadmap status
4. Write the convention: "agents propose roadmap changes, humans approve or auto-approve"

This is operational — it works today with just file conventions and prompt updates. No new code.

### Phase 2: Prompt Integration
5. Update drive consultation prompt: "Check the roadmap for gaps against drives. If a drive is underserved, propose a roadmap addition."
6. Add roadmap-owner awareness to the prompt: "If you own the roadmap, review pending proposals."
7. Update task completion prompt: "If this task's roadmap_item has all tasks done, mark the roadmap item done. Update the relevant drive."

### Phase 3: CLI Commands
8. `agent-os proposals list [--roadmap]`
9. `agent-os proposals approve/reject <id>`
10. These are thin wrappers around file operations

### Phase 4: Dashboard Integration
11. Proposal indicators on the strategy page
12. Inline approve/reject buttons
13. Governance history view
14. Notification badges

Phase 1 can ship immediately — it's conventions and prompt updates, no code. Phase 4 depends on the dashboard being functional.

---

## 10. Configuration Reference

All governance configuration lives in `strategy/roadmap.md` header, keeping it simple and co-located:

```markdown
# Roadmap

governance: auto-approve
approval_window: 48h
owner: agent-pm

What are you building, and in what order?

## Item One
status: active
...
```

**All fields optional.** Defaults:
- `governance`: `auto-approve`
- `approval_window`: `48h`
- `owner`: none (all agents equal)

If no configuration is present, the system uses defaults. A solo builder who never touches governance config gets the simplest possible experience: agents propose things, and if nobody objects for 48h, they happen. The human can always intervene.

---

## 11. What This Spec Does NOT Cover

- **Authentication/authorization for the dashboard** — a broader hosted-offering concern, not specific to roadmap governance
- **Automated enforcement** — governance is convention-based, enforced by prompts and agent behavior, not by code that prevents file writes. This is deliberate: the filesystem is open, trust is the model, prompts are the guardrails
- **Proposal templates for non-roadmap changes** — the existing proposals system handles those fine
- **Multi-company governance** — out of scope for v1
- **Voting weights or quorum rules** — premature. If a user has 10 agents and needs weighted voting, that's a v2 feature based on real demand

---

## 12. Design Decisions and Rationale

### Why convention over enforcement?

agent-os is file-based. Any agent can write to any file. We could build permission checking into the runtime, but that contradicts the design philosophy: everything is a file, the filesystem is the database, Unix tools work out of the box. Instead, governance is enforced through prompts (agents are told to propose, not directly edit) and cultural convention (the same way human organizations work — through norms, not locks).

If an agent edits the roadmap without proposing, the git history shows it. The human can see it. Trust, but verify.

### Why auto-approve as default?

For the target user (solo builder with 2-3 agents), requiring explicit approval for every proposal would mean: the agents propose something at 3am, the human sees it at 9am, approves it at 9:05am, and the agents can act on it at the next cycle. That's 6+ hours of wasted time for a change the human would have approved immediately.

Auto-approve with a veto window optimizes for the common case: the agent's proposal is fine, and the human would have approved it. The uncommon case (bad proposal) is caught by the veto window or by the next time the human looks at the dashboard.

### Why not separate proposal files per roadmap item?

Proposals are per-change, not per-item. One proposal might add three roadmap items. Another might reprioritize two. The proposal is the unit of governance; the roadmap item is the unit of strategy. They map loosely, not 1:1.

### Why `deferred` instead of deletion?

Deleting a roadmap item loses the history of "we considered this and decided not now." `deferred` preserves it. The dashboard collapses deferred items (like done items), so they don't clutter the active view. git history would also preserve deletions, but `deferred` is more human-readable and shows up in `agent-os roadmap list`.
