import { useState } from 'react'
import { useTimeline } from '../api/hooks'
import Card from '../components/Card'
import AgentName, { agentColor } from '../components/AgentName'
import Loading from '../components/Loading'
import { humanizeAction } from '../utils/humanize'

const AGENT_IDS = [
  'agent-000-steward',
  'agent-001-maker',
  'agent-003-operator',
  'agent-005-grower',
  'agent-006-strategist',
]

/** Action categories for visual styling */
const ACTION_CATEGORIES: Record<string, string> = {
  // Task lifecycle — blue
  task_start: 'task', task_started: 'task', task_complete: 'task', task_completed: 'task',
  task_failed: 'error', claimed_task: 'task', claim_task: 'task', completed_task: 'task', failed_task: 'error',
  // SDK — subtle
  sdk_invoke: 'system', sdk_complete: 'system',
  // Drives — purple
  drive_consultation_start: 'drive', drive_consultation_complete: 'drive', drive_consultation_skipped: 'drive',
  // Standing orders — teal
  standing_order_start: 'standing', standing_order_complete: 'standing',
  // Dreams — indigo
  dream_start: 'dream', dream_complete: 'dream',
  // Messages
  message_sent: 'message', broadcast_posted: 'message', thread_response: 'message', thread_started: 'message',
  // Errors
  error: 'error',
}

const CATEGORY_STYLES: Record<string, string> = {
  task: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  drive: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  standing: 'bg-teal-500/10 text-teal-400 border-teal-500/20',
  dream: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/20',
  message: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
  error: 'bg-red-500/10 text-red-400 border-red-500/20',
  system: 'bg-slate-500/8 text-[#64748b] border-slate-500/10',
}

function ActionBadge({ action }: { action: string }) {
  const category = ACTION_CATEGORIES[action] || 'system'
  const style = CATEGORY_STYLES[category] || CATEGORY_STYLES.system
  return (
    <span className={`inline-block px-2 py-0.5 text-[10px] rounded border ${style} whitespace-nowrap`}>
      {humanizeAction(action)}
    </span>
  )
}

export default function Timeline() {
  const today = new Date().toISOString().slice(0, 10)
  const [date, setDate] = useState(today)
  const [agentFilter, setAgentFilter] = useState<string>('')
  const [showIdle, setShowIdle] = useState(false)
  const { data: entries, isLoading } = useTimeline(date, agentFilter || undefined, !showIdle)

  if (isLoading) return <Loading />

  // Group entries by hour for visual separation
  function getHourLabel(timestamp: string): string {
    const d = new Date(timestamp)
    const h = d.getHours()
    const ampm = h >= 12 ? 'PM' : 'AM'
    const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h
    return `${h12} ${ampm}`
  }

  let lastHour = ''

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Timeline</h2>
        <div className="flex gap-2 items-center">
          <input
            type="date"
            value={date}
            onChange={e => setDate(e.target.value)}
            className="bg-[#0f172a] border border-[#334155] rounded px-2.5 py-1.5 text-sm text-[#f1f5f9] focus:border-[#38bdf8] outline-none"
          />
          <select
            value={agentFilter}
            onChange={e => setAgentFilter(e.target.value)}
            className="bg-[#0f172a] border border-[#334155] rounded px-2.5 py-1.5 text-sm text-[#f1f5f9] focus:border-[#38bdf8] outline-none"
          >
            <option value="">All agents</option>
            {AGENT_IDS.map(id => (
              <option key={id} value={id}>{id.split('-').slice(2).join(' ')}</option>
            ))}
          </select>
          <button
            onClick={() => setShowIdle(!showIdle)}
            className={`px-2.5 py-1.5 text-xs rounded border transition-colors ${
              showIdle
                ? 'bg-[#334155] border-[#475569] text-[#f1f5f9]'
                : 'bg-[#0f172a] border-[#334155] text-[#64748b] hover:text-[#94a3b8]'
            }`}
          >
            Show idle
          </button>
        </div>
      </div>

      {/* Entry count */}
      {entries && entries.length > 0 && (
        <div className="text-xs text-[#475569]">{entries.length} events</div>
      )}

      <Card>
        <div className="space-y-0 max-h-[calc(100vh-200px)] overflow-auto">
          {(entries || []).map((entry, i) => {
            const hourLabel = getHourLabel(entry.timestamp)
            const showHourDivider = hourLabel !== lastHour
            lastHour = hourLabel

            const color = agentColor(entry.agent)

            return (
              <div key={i}>
                {/* Hour divider */}
                {showHourDivider && (
                  <div className="flex items-center gap-3 py-2 px-1 mt-1 first:mt-0">
                    <span className="text-[10px] font-medium text-[#475569] uppercase tracking-wider w-12 shrink-0 text-right">
                      {hourLabel}
                    </span>
                    <div className="flex-1 h-px bg-[#334155]/50" />
                  </div>
                )}

                {/* Entry row */}
                <div
                  className="flex items-start gap-3 py-2 px-2 rounded hover:bg-[#334155]/10 transition-colors border-l-2"
                  style={{ borderLeftColor: color + '60' }}
                >
                  <span className="text-[10px] text-[#475569] font-mono w-14 shrink-0 pt-0.5 text-right">
                    {new Date(entry.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </span>
                  <span className="w-20 shrink-0 text-sm">
                    <AgentName id={entry.agent} short />
                  </span>
                  <span className="shrink-0">
                    <ActionBadge action={entry.action} />
                  </span>
                  <span className="text-xs text-[#94a3b8] flex-1 min-w-0 break-words">{entry.detail}</span>
                </div>
              </div>
            )
          })}
          {(!entries || entries.length === 0) && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="text-[#334155] text-3xl mb-3">|</div>
              <div className="text-sm text-[#475569]">No activity for this date</div>
              <div className="text-xs text-[#334155] mt-1">Try selecting a different date or agent filter</div>
            </div>
          )}
        </div>
      </Card>
    </div>
  )
}
