/**
 * Humanize machine-readable action labels from agent logs.
 * Maps raw log action strings to human-friendly descriptions.
 */

const ACTION_MAP: Record<string, string> = {
  // Cycle lifecycle
  cycle_start: 'Cycle started',
  cycle_idle: 'Idle cycle (nothing to do)',
  cycle_complete: 'Cycle completed',

  // SDK
  sdk_invoke: 'Calling Claude Agent SDK',
  sdk_complete: 'SDK call completed',

  // Tasks
  task_start: 'Starting task',
  task_started: 'Started task',
  task_complete: 'Task completed',
  task_completed: 'Completed task',
  task_failed: 'Task failed',
  claimed_task: 'Claimed task',
  claim_task: 'Claimed task',
  completed_task: 'Completed task',
  failed_task: 'Task failed',

  // Standing orders
  standing_order_start: 'Running standing order',
  standing_order_complete: 'Standing order finished',

  // Drive consultations
  drive_consultation_start: 'Consulting drives',
  drive_consultation_complete: 'Drive consultation finished',
  drive_consultation_skipped: 'Drive consultation skipped',

  // Dream cycles
  dream_start: 'Dream cycle started',
  dream_complete: 'Dream cycle finished',

  // Messages
  message_sent: 'Sent message',
  message_read: 'Read message',
  broadcast_posted: 'Posted broadcast',
  thread_response: 'Responded to thread',
  thread_started: 'Started thread',

  // Quality gates
  quality_gate_pass: 'Quality gates passed',
  quality_gate_fail: 'Quality gates failed',

  // Misc
  pull: 'Git pull',
  error: 'Error occurred',
  working_memory_updated: 'Updated working memory',
  soul_updated: 'Updated soul',
}

/**
 * Convert a machine-readable action label to a human-friendly string.
 * Falls back to title-casing the raw label if no mapping exists.
 */
export function humanizeAction(action: string): string {
  if (ACTION_MAP[action]) return ACTION_MAP[action]

  // Fallback: replace underscores/hyphens with spaces, title-case
  return action
    .replace(/[_-]/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
}

/**
 * Format a cost value with appropriate precision.
 * Shows 2 decimals for values >= $1, 4 decimals for smaller values.
 */
export function formatCost(cost: number): string {
  if (cost >= 1) return `$${cost.toFixed(2)}`
  if (cost > 0) return `$${cost.toFixed(4)}`
  return '$0.00'
}
