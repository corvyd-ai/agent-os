import { useQuery } from '@tanstack/react-query'

const POLL_INTERVAL = 30_000 // 30 seconds

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

// --- App Info ---

export interface AppInfo {
  version: string
}

export function useAppInfo() {
  return useQuery<AppInfo>({
    queryKey: ['app-info'],
    queryFn: () => fetchJson('/api/info'),
    staleTime: Infinity,
  })
}

// --- Types ---

export interface AgentSummary {
  id: string
  name: string
  role?: string
  short_name?: string
  last_active: string | null
  cost_today: number
  cycles_today: number
  current_task: { id: string; title: string } | null
  inbox_count?: number
}

export interface AgentDetail extends AgentSummary {
  soul: string
  working_memory: string
  registry: string
  journal: string
}

export interface TaskItem {
  id: string
  title: string
  assigned_to: string
  created_by: string
  priority: string
  created: string
  status: string
  body: string
  _file: string
  depends_on?: string[] | null
}

export interface Drive {
  name: string
  tension: string
  state: string
  last_updated: string
  reduce?: string
}

export interface CostDay {
  date: string
  total: number
  invocations?: number
  by_agent: Record<string, number>
}

export interface CostSummary {
  total: number
  days: number
  invocations: number
  avg_daily: number
  by_agent: Record<string, { total: number; name: string }>
  by_task_type: Record<string, number>
  daily_totals: { date: string; total: number }[]
}

export interface LogEntry {
  timestamp: string
  agent: string
  action: string
  detail: string
  refs?: Record<string, unknown>
}

export interface HumanTask {
  id: string
  title: string
  priority: string
  created_by: string
  created: string
}

export interface ExecutiveSummary {
  content: string
  last_updated: string
}

export interface OverviewData {
  executive_summary: ExecutiveSummary | null
  agents: AgentSummary[]
  task_counts: Record<string, number>
  cost_trend: CostDay[]
  drives: Drive[]
  human_tasks: HumanTask[]
  recent_activity: LogEntry[]
}

export interface Message {
  id: string
  from: string
  to?: string
  date: string
  subject: string
  body: string
  urgency?: string
  _file: string
}

export interface Proposal {
  id: string
  title: string
  proposed_by: string
  date: string
  status: string
  decision?: string
  body: string
  _file: string
}

export interface Decision {
  id: string
  title: string
  date: string
  decided_by: string
  status: string
  tags?: string[]
  body: string
  _file: string
}

// --- Hooks ---

export function useOverview() {
  return useQuery<OverviewData>({
    queryKey: ['overview'],
    queryFn: () => fetchJson('/api/overview'),
    refetchInterval: POLL_INTERVAL,
  })
}

export function useAgents() {
  return useQuery<AgentSummary[]>({
    queryKey: ['agents'],
    queryFn: () => fetchJson('/api/agents'),
    refetchInterval: POLL_INTERVAL,
  })
}

export function useAgent(id: string) {
  return useQuery<AgentDetail>({
    queryKey: ['agent', id],
    queryFn: () => fetchJson(`/api/agents/${id}`),
    refetchInterval: POLL_INTERVAL,
  })
}

export function useAgentLogs(id: string, date?: string, hideIdle = true) {
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  if (!hideIdle) params.set('hide_idle', 'false')
  const qs = params.toString() ? `?${params}` : ''
  return useQuery<LogEntry[]>({
    queryKey: ['agent-logs', id, date, hideIdle],
    queryFn: () => fetchJson(`/api/agents/${id}/logs${qs}`),
    refetchInterval: POLL_INTERVAL,
  })
}

export function useTasks(status?: string) {
  const params = status ? `?status=${status}` : ''
  return useQuery<TaskItem[]>({
    queryKey: ['tasks', status],
    queryFn: () => fetchJson(`/api/tasks${params}`),
    refetchInterval: POLL_INTERVAL,
  })
}

export function useTaskSummary() {
  return useQuery<Record<string, number>>({
    queryKey: ['task-summary'],
    queryFn: () => fetchJson('/api/tasks/summary'),
    refetchInterval: POLL_INTERVAL,
  })
}

export function useDailyCosts(days = 7) {
  return useQuery<CostDay[]>({
    queryKey: ['costs-daily', days],
    queryFn: () => fetchJson(`/api/costs/daily?days=${days}`),
    refetchInterval: POLL_INTERVAL,
  })
}

export function useCostSummary(days = 7) {
  return useQuery<CostSummary>({
    queryKey: ['cost-summary', days],
    queryFn: () => fetchJson(`/api/costs/summary?days=${days}`),
    refetchInterval: POLL_INTERVAL,
  })
}

export function useDrives() {
  return useQuery<Drive[]>({
    queryKey: ['drives'],
    queryFn: () => fetchJson('/api/drives'),
    refetchInterval: POLL_INTERVAL,
  })
}

export function useTimeline(date?: string, agent?: string, hideIdle = true) {
  const params = new URLSearchParams()
  if (date) params.set('date', date)
  if (agent) params.set('agent', agent)
  if (!hideIdle) params.set('hide_idle', 'false')
  const qs = params.toString() ? `?${params}` : ''
  return useQuery<LogEntry[]>({
    queryKey: ['timeline', date, agent, hideIdle],
    queryFn: () => fetchJson(`/api/timeline${qs}`),
    refetchInterval: POLL_INTERVAL,
  })
}

export function useBroadcasts() {
  return useQuery<Message[]>({
    queryKey: ['broadcasts'],
    queryFn: () => fetchJson('/api/messages/broadcast'),
    refetchInterval: POLL_INTERVAL,
  })
}

export function useThreads() {
  return useQuery<Message[]>({
    queryKey: ['threads'],
    queryFn: () => fetchJson('/api/messages/threads'),
    refetchInterval: POLL_INTERVAL,
  })
}

export function useHumanInbox() {
  return useQuery<Message[]>({
    queryKey: ['human-inbox'],
    queryFn: () => fetchJson('/api/messages/human'),
    refetchInterval: POLL_INTERVAL,
  })
}

export function useInboxSummary() {
  return useQuery<Record<string, number>>({
    queryKey: ['inbox-summary'],
    queryFn: () => fetchJson('/api/messages/inboxes'),
    refetchInterval: POLL_INTERVAL,
  })
}

export function useProposals() {
  return useQuery<{ active: Proposal[]; decided: Proposal[] }>({
    queryKey: ['proposals'],
    queryFn: () => fetchJson('/api/proposals'),
    refetchInterval: POLL_INTERVAL,
  })
}

export function useDecisions() {
  return useQuery<Decision[]>({
    queryKey: ['decisions'],
    queryFn: () => fetchJson('/api/decisions'),
    refetchInterval: POLL_INTERVAL,
  })
}

// --- Health Metrics Types ---

export interface MetricScores {
  score: number
  [key: string]: unknown
}

export interface AgentHealth {
  agent_id: string
  days: number
  composite_score: number
  autonomy: MetricScores & {
    productive_cycle_ratio: number
    escalation_rate: number
    self_initiated_ratio: number
    decision_autonomy: number
    productive_cycles: number
    total_cycles: number
    tasks_completed: number
    human_tasks_created: number
    self_initiated_tasks: number
  }
  effectiveness: MetricScores & {
    completion_rate: number
    throughput_per_day: number
    mean_duration_ms: number
    tasks_done: number
    tasks_failed: number
    tasks_total: number
  }
  efficiency: MetricScores & {
    total_cost_usd: number
    cost_per_task_usd: number
    cost_per_turn_usd: number
    idle_cost_ratio: number
    total_turns: number
    task_invocations: number
    drive_invocations: number
    standing_order_invocations: number
  }
  system_health: MetricScores & {
    error_rate: number
    error_count: number
    schedule_adherence: number
    active_days: number
    expected_days: number
    standing_order_invocations: number
    mean_recovery_minutes: number
  }
}

export interface GovernanceHealth {
  score: number
  active_proposals: number
  decided_proposals_in_period: number
  proposal_throughput: number
  decisions_in_period: number
  total_threads: number
  resolved_threads: number
  active_threads: number
  resolution_rate: number
  mean_response_hours: number
}

export interface HealthTrend {
  score_7d: number
  score_30d: number
  delta: number
  direction: 'improving' | 'stable' | 'declining'
}

export interface HealthMetrics {
  current: {
    system_composite: number
    governance: GovernanceHealth
    agents: Record<string, AgentHealth>
    period_days: number
    computed_at: string
  }
  baseline: {
    system_composite: number
    governance: GovernanceHealth
    agents: Record<string, AgentHealth>
    period_days: number
    computed_at: string
  }
  trends: {
    system: HealthTrend
    agents: Record<string, HealthTrend>
  }
  computed_at: string
}

export interface HealthSummary {
  system_score: number
  system_direction: 'improving' | 'stable' | 'declining'
  system_delta: number
  governance_score: number
  agents: Record<string, {
    score: number
    direction: 'improving' | 'stable' | 'declining'
    delta: number
  }>
  computed_at: string
}

// --- Health Metrics Hooks ---

export function useHealthMetrics() {
  return useQuery<HealthMetrics>({
    queryKey: ['health-metrics'],
    queryFn: () => fetchJson('/api/health/metrics'),
    refetchInterval: 60_000, // 60s — metrics are expensive to compute
  })
}

export function useHealthSummary() {
  return useQuery<HealthSummary>({
    queryKey: ['health-summary'],
    queryFn: () => fetchJson('/api/health/summary'),
    refetchInterval: 60_000,
  })
}

// --- Notes (System Notes, formerly Feedback) Types ---

export interface NoteResponse {
  author: string
  timestamp: string
  text: string
}

export interface NoteItem {
  id: string
  author: string
  created: string
  status: 'open' | 'acknowledged' | 'addressed'
  tags: string[]
  body: string
  responses: NoteResponse[]
  _file: string
}

export function useNotes() {
  return useQuery<NoteItem[]>({
    queryKey: ['notes'],
    queryFn: () => fetchJson('/api/notes'),
    refetchInterval: POLL_INTERVAL,
  })
}

// Backward compat aliases
export type FeedbackResponse = NoteResponse
export type FeedbackItem = NoteItem
export const useFeedback = useNotes

// --- Governance Controls Types ---

export interface ScheduleTypeConfig {
  enabled: boolean
  interval?: string
  time?: string
  [key: string]: unknown
}

export interface ScheduleData {
  config: Record<string, ScheduleTypeConfig | unknown>
  budget_summary: { daily_cap: number; weekly_cap: number }
  state: Record<string, unknown>
}

export interface BudgetData {
  daily: { spent: number; cap: number; remaining: number; pct: number; tripped: boolean }
  weekly_cap: number
  monthly_cap: number
  per_agent: Record<string, { spent: number; cap: number; within: boolean }>
  per_invocation: Record<string, number>
}

export interface AutonomyData {
  default_level: string
  agents: Record<string, string>
}

export interface BacklogItem {
  id: string
  title: string
  created_by: string
  assigned_to: string
  priority: string
  created_at: string
  body: string
}

export interface BacklogData {
  items: BacklogItem[]
}

// --- Governance Controls Hooks ---

export function useSchedule() {
  return useQuery<ScheduleData>({
    queryKey: ['schedule'],
    queryFn: () => fetchJson('/api/schedule'),
    refetchInterval: POLL_INTERVAL,
  })
}

export function useBudget() {
  return useQuery<BudgetData>({
    queryKey: ['budget'],
    queryFn: () => fetchJson('/api/budget'),
    refetchInterval: POLL_INTERVAL,
  })
}

export function useAutonomy() {
  return useQuery<AutonomyData>({
    queryKey: ['autonomy'],
    queryFn: () => fetchJson('/api/autonomy'),
    refetchInterval: POLL_INTERVAL,
  })
}

export function useBacklog() {
  return useQuery<BacklogData>({
    queryKey: ['backlog'],
    queryFn: () => fetchJson('/api/backlog'),
    refetchInterval: POLL_INTERVAL,
  })
}

// --- Conversation Types ---

export interface ConversationTurn {
  role: 'human' | 'assistant'
  content: string
}

export interface ConversationSummary {
  id: string
  agent_id: string
  created: string
  updated: string
  preview: string
  turn_count: number
  total_cost_usd: number
}

export interface Conversation {
  id: string
  agent_id: string
  created: string
  updated: string
  turns: ConversationTurn[]
  total_cost_usd: number
}

export interface AgentAvailability {
  available: boolean
  agent_id?: string
  reason?: string
  error?: string
}

export type StreamEvent =
  | { type: 'text'; text: string }
  | { type: 'tool_use'; name: string; input_preview: string }
  | { type: 'complete'; cost_usd: number; duration_ms: number; num_turns: number }
  | { type: 'error'; message: string }
  | { type: 'conversation_saved'; conversation_id: string }

// --- Conversation Hooks ---

export function useConversations() {
  return useQuery<ConversationSummary[]>({
    queryKey: ['conversations'],
    queryFn: () => fetchJson('/api/conversations'),
  })
}

export function useConversation(id: string | null) {
  return useQuery<Conversation>({
    queryKey: ['conversation', id],
    queryFn: () => fetchJson(`/api/conversations/${id}`),
    enabled: !!id,
  })
}

export function useAgentAvailability(agentId: string | null) {
  return useQuery<AgentAvailability>({
    queryKey: ['agent-availability', agentId],
    queryFn: () => fetchJson(`/api/conversation/status/${agentId}`),
    enabled: !!agentId,
    refetchInterval: 10_000,
  })
}

export function streamConversation(
  agentId: string,
  message: string,
  conversationId: string | null,
  onEvent: (event: StreamEvent) => void,
  onDone: () => void,
  onError: (error: string) => void,
): AbortController {
  const controller = new AbortController()

  fetch('/api/conversation/send', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      agent_id: agentId,
      message,
      conversation_id: conversationId,
    }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        onError(`HTTP ${res.status}: ${res.statusText}`)
        return
      }

      const reader = res.body?.getReader()
      if (!reader) {
        onError('No response body')
        return
      }

      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event = JSON.parse(line.slice(6)) as StreamEvent
              onEvent(event)
            } catch {
              // Skip malformed JSON
            }
          }
        }
      }

      // Process any remaining data in buffer
      if (buffer.startsWith('data: ')) {
        try {
          const event = JSON.parse(buffer.slice(6)) as StreamEvent
          onEvent(event)
        } catch {
          // Skip
        }
      }

      onDone()
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onError(err.message || 'Stream failed')
      }
    })

  return controller
}
