# Dream Journal Failure Investigation

**Investigated by**: agent-001-maker  
**Task**: task-2026-0517-001  
**Date**: 2026-05-17  

## Problem

During dream cycles, journal entries sometimes fail to append to `agents/logs/{agent-id}/journal.md` even though the dream cycle reports success. Working memory gets updated, soul gets reviewed, but the journal section (Step 6 of the dream prompt) is silently skipped. Observed at least 3 times in 2 weeks for agent-003.

## Root Cause

The journal append was **entirely delegated to the LLM** via prompt instructions (Step 6 of `dream.jinja2`). The platform's `run_dream_cycle()` function had **zero post-cycle verification** — it could not distinguish between a dream that completed all 6 steps and one that ran out of turns after step 5.

Five specific gaps:

1. **No pre-cycle file state capture** — the function didn't snapshot journal.md's mtime before the SDK call, so there was no baseline to compare against.

2. **No post-cycle verification** — after the SDK query completed, the runner just logged cost and said "Dream cycle finished." It never checked if journal.md was actually modified.

3. **No `result_msg.is_error` check** — unlike task cycles, the dream runner didn't check for SDK-level errors at all. Even a hard error that returned a result message would be logged as success.

4. **No `error_max_turns` detection** — if the agent exhausted its 25-turn budget on steps 1-5 (reading 4+ files, rewriting working memory from scratch, reorganizing old memories), Step 6 never executed, but the platform reported success.

5. **No `CycleOutcomeEvent` emission** — task cycles emit structured observability events separating "the process ran" from "the work shipped." Dream cycles had nothing equivalent — no structured signal at all.

## Why It Happens

Dream cycles are cognitively heavy. The agent must:
- Read 4 files (soul, working memory, journal, old memories)
- Rewrite working memory from scratch
- Reorganize old memories by topic
- Optionally mine old memories
- Review soul for changes
- **Then** journal the dream

With `dream_max_turns: 25` and `dream_max_budget_usd: 1.50`, the agent can run out of budget on the first 5 steps — especially when files are large or the agent does thorough reorganization. The journal step is last in the prompt, making it the most vulnerable to truncation.

## Fix Applied

Three changes in agent-os source (branch `agent/task-2026-0517-001`):

### 1. `DreamOutcomeEvent` (events.py)
New structured event that tracks:
- `process_status`: "completed", "error", or "max_turns"
- `journal_updated`: boolean — did journal.md's mtime change?
- `working_memory_updated`: boolean — did working-memory.md's mtime change?
- `cost_usd`, `num_turns`, `failure_reason`

Booleans are always serialized (even when False) because False is the interesting signal.

### 2. Post-dream verification (runner.py)
`run_dream_cycle()` now:
- Snapshots journal.md and working-memory.md mtime before the SDK call
- Checks `result_msg.is_error` and detects `error_max_turns`
- Compares post-cycle mtime to detect whether files were modified
- Emits `DreamOutcomeEvent` on every dream cycle
- Fires a `dream_journal_missing` notification when the journal wasn't updated

### 3. Notification event types (notifications.py)
Two new event types registered in `KNOWN_EVENT_TYPES`:
- `dream_journal_missing` — the specific failure signal
- `dream_outcome` — general dream observability

## Detection Going Forward

After this fix, a dream cycle where the journal is silently skipped will:
1. Emit a `dream_outcome` event at `warn` level (visible in JSONL logs)
2. Fire a `dream_journal_missing` notification (visible in notification system)
3. Log `dream_journal_missing` warning to the agent's JSONL log

The "partial failure masquerading as health" pattern is structurally eliminated for dream cycles.

## Broader Pattern

This same vulnerability (platform reports success on an LLM-delegated step that silently failed) could apply to other cycle types. Drive consultations have the same structure — the runner doesn't verify that the agent actually did anything meaningful. Future work could add similar verification to drive consultations and standing orders.
