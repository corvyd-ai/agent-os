import { Link } from 'react-router-dom'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { useOverview, useHealthSummary, useSchedule, useBudget, useBacklog, useHumanInbox } from '../api/hooks'
import Card from '../components/Card'
import Markdown from '../components/Markdown'
import TensionBadge from '../components/TensionBadge'
import TimeAgo from '../components/TimeAgo'
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

function shortName(id: string) {
  const parts = id.split('-')
  return parts.length > 2 ? parts[2].charAt(0).toUpperCase() + parts[2].slice(1) : id
}

function scoreColor(score: number): string {
  if (score >= 70) return '#4ade80'
  if (score >= 40) return '#fbbf24'
  return '#f87171'
}

function trendArrow(direction: string): string {
  if (direction === 'improving') return '\u2191'
  if (direction === 'declining') return '\u2193'
  return '\u2192'
}

function trendTextColor(direction: string): string {
  if (direction === 'improving') return '#4ade80'
  if (direction === 'declining') return '#f87171'
  return '#64748b'
}

export default function Overview() {
  const { data, isLoading, error } = useOverview()
  const { data: healthSummary } = useHealthSummary()
  const { data: schedule } = useSchedule()
  const { data: budget } = useBudget()
  const { data: backlog } = useBacklog()
  const { data: humanInbox } = useHumanInbox()

  if (isLoading) return <Loading />
  if (error || !data) return <div className="text-red-400">Failed to load overview</div>

  const chartData = data.cost_trend.map(d => ({
    date: d.date.slice(5), // MM-DD
    total: d.total,
    ...Object.fromEntries(
      AGENT_IDS.map(id => [shortName(id), d.by_agent[id] || 0])
    ),
  }))

  const totalToday = data.agents.reduce((s, a) => s + a.cost_today, 0)

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">System Overview</h2>
        <div className="text-xs text-[#64748b]">
          ${totalToday.toFixed(2)} today &middot; {data.agents.reduce((s, a) => s + a.cycles_today, 0)} cycles
        </div>
      </div>

      {/* Executive Summary */}
      {data.executive_summary ? (
        <div className="bg-[#1e293b] border border-[#334155] rounded-lg overflow-hidden">
          <div className="h-0.5 bg-[#38bdf8]" />
          <div className="px-4 py-3 border-b border-[#334155] flex items-center justify-between">
            <h3 className="text-sm font-medium text-[#94a3b8]">Executive Summary</h3>
            <TimeAgo timestamp={data.executive_summary.last_updated} />
          </div>
          <div className="p-4">
            <Markdown>{data.executive_summary.content}</Markdown>
          </div>
        </div>
      ) : (
        <div className="bg-[#1e293b] border border-[#334155] rounded-lg overflow-hidden">
          <div className="h-0.5 bg-[#334155]" />
          <div className="px-4 py-3 border-b border-[#334155]">
            <h3 className="text-sm font-medium text-[#94a3b8]">Executive Summary</h3>
          </div>
          <div className="p-4">
            <p className="text-sm text-[#475569] italic">No summary yet — the Steward will generate one during the next health scan.</p>
          </div>
        </div>
      )}

      {/* Needs Attention */}
      {(() => {
        const attentionItems: Array<{ type: string; typeBadge: string; text: string; agent: string; time: string; link: string }> = []

        // Human tasks
        for (const task of data.human_tasks) {
          attentionItems.push({
            type: 'task',
            typeBadge: 'bg-red-500/20 text-red-400',
            text: task.title,
            agent: task.created_by,
            time: task.created,
            link: '/tasks?status=queued',
          })
        }

        // Backlog items
        if (backlog) {
          for (const item of backlog.items) {
            attentionItems.push({
              type: 'backlog',
              typeBadge: 'bg-cyan-500/20 text-cyan-400',
              text: item.title,
              agent: item.created_by,
              time: item.created_at,
              link: '/tasks',
            })
          }
        }

        // Human inbox messages
        if (humanInbox) {
          for (const msg of humanInbox) {
            attentionItems.push({
              type: 'inbox',
              typeBadge: 'bg-purple-500/20 text-purple-400',
              text: msg.subject,
              agent: msg.from,
              time: msg.date,
              link: '/messages',
            })
          }
        }

        // Sort by time (most recent first)
        attentionItems.sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime())

        if (attentionItems.length === 0) return null

        return (
          <div className="bg-[#1e293b] border border-[#334155] rounded-lg overflow-hidden">
            <div className="h-0.5 bg-[#f59e0b]" />
            <div className="px-4 py-3 border-b border-[#334155]">
              <h3 className="text-sm font-medium text-[#f59e0b]">Needs Attention ({attentionItems.length})</h3>
            </div>
            <div className="divide-y divide-[#334155]/30">
              {attentionItems.map((item, i) => (
                <Link key={i} to={item.link} className="no-underline">
                  <div className="flex items-center gap-3 px-4 py-2.5 hover:bg-[#334155]/20 transition-colors">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${item.typeBadge}`}>
                      {item.type}
                    </span>
                    <span className="text-sm text-[#f1f5f9] flex-1 truncate">{item.text}</span>
                    <span className="text-xs shrink-0">
                      <AgentName id={item.agent} short />
                    </span>
                    <span className="text-xs text-[#475569] shrink-0">
                      <TimeAgo timestamp={item.time} />
                    </span>
                    <span className="text-[#475569] text-xs">&rarr;</span>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )
      })()}

      {/* Agent status cards */}
      <div className="grid grid-cols-5 gap-3">
        {data.agents.map(agent => {
          const color = agentColor(agent.id)
          return (
            <Link key={agent.id} to={`/agents/${agent.id}`}>
              <div className="bg-[#1e293b] border border-[#334155] rounded-lg overflow-hidden hover:border-[#475569] transition-colors">
                <div className="h-0.5" style={{ backgroundColor: color }} />
                <div className="p-3">
                  <div className="flex items-center justify-between mb-1.5">
                    <AgentName id={agent.id} short />
                    <span className="text-[10px] text-[#475569]">{agent.cycles_today} cycles</span>
                  </div>
                  <div className="text-2xl font-bold text-[#f1f5f9]">
                    ${agent.cost_today.toFixed(2)}
                  </div>
                  <div className="text-xs mt-1">
                    <TimeAgo timestamp={agent.last_active} />
                  </div>
                  {agent.current_task && (
                    <div className="mt-2 text-[10px] text-[#64748b] truncate border-t border-[#334155]/50 pt-1.5">
                      {agent.current_task.title}
                    </div>
                  )}
                </div>
              </div>
            </Link>
          )
        })}
      </div>

      {/* Status bar */}
      <Link to="/controls" className="no-underline">
        <div className="bg-[#1e293b] border border-[#334155] rounded-lg px-4 py-2 flex items-center gap-6 hover:border-[#475569] transition-colors">
          {/* Scheduler */}
          <div className="flex items-center gap-2 text-xs">
            <span className={`w-2 h-2 rounded-full ${
              (schedule?.config as Record<string, unknown>)?.enabled !== false ? 'bg-green-400' : 'bg-red-400'
            }`} />
            <span className="text-[#94a3b8]">Scheduler:</span>
            <span className="text-[#f1f5f9]">
              {(schedule?.config as Record<string, unknown>)?.enabled !== false ? 'Running' : 'Paused'}
            </span>
          </div>

          {/* Budget */}
          {budget && (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-[#94a3b8]">Budget:</span>
              <div className="w-24 h-2 bg-[#0f172a] rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${Math.min(budget.daily.pct, 100)}%`,
                    backgroundColor: budget.daily.tripped ? '#f87171' : budget.daily.pct >= 85 ? '#f87171' : budget.daily.pct >= 60 ? '#fbbf24' : '#38bdf8',
                  }}
                />
              </div>
              <span className={budget.daily.tripped ? 'text-red-400' : 'text-[#f1f5f9]'}>
                {Math.round(budget.daily.pct)}% (${budget.daily.spent.toFixed(0)}/${budget.daily.cap.toFixed(0)})
              </span>
            </div>
          )}

          {/* Backlog */}
          {backlog && backlog.items.length > 0 && (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-cyan-400">{backlog.items.length}</span>
              <span className="text-[#94a3b8]">awaiting review</span>
            </div>
          )}
        </div>
      </Link>

      <div className="grid grid-cols-4 gap-4">
        {/* System Health summary */}
        <Link to="/health" className="no-underline">
          <Card title="System Health">
            {healthSummary ? (
              <div>
                <div className="flex items-center justify-between mb-3">
                  <div className="text-3xl font-bold" style={{ color: scoreColor(healthSummary.system_score) }}>
                    {Math.round(healthSummary.system_score)}
                  </div>
                  <span
                    className="text-sm font-mono"
                    style={{ color: trendTextColor(healthSummary.system_direction) }}
                  >
                    {trendArrow(healthSummary.system_direction)} {healthSummary.system_delta > 0 ? '+' : ''}{healthSummary.system_delta}
                  </span>
                </div>
                <div className="space-y-1.5">
                  {AGENT_IDS.map(id => {
                    const agent = healthSummary.agents[id]
                    if (!agent) return null
                    return (
                      <div key={id} className="flex items-center justify-between">
                        <AgentName id={id} short />
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-mono" style={{ color: scoreColor(agent.score) }}>
                            {Math.round(agent.score)}
                          </span>
                          <span
                            className="text-[10px]"
                            style={{ color: trendTextColor(agent.direction) }}
                          >
                            {trendArrow(agent.direction)}
                          </span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            ) : (
              <div className="text-sm text-[#475569] italic py-4 text-center">Loading health data...</div>
            )}
          </Card>
        </Link>

        {/* Task queue summary */}
        <Card title="Task Queue">
          <div className="grid grid-cols-3 gap-2 text-center">
            {Object.entries(data.task_counts)
              .filter(([s]) => ['queued', 'in-progress', 'done'].includes(s))
              .map(([status, count]) => (
                <Link key={status} to={`/tasks?status=${status}`} className="no-underline">
                  <div className="text-2xl font-bold text-[#f1f5f9]">{count}</div>
                  <div className="text-xs text-[#64748b]">{status}</div>
                </Link>
              ))}
          </div>
          <div className="flex gap-4 mt-3 pt-3 border-t border-[#334155] text-xs text-[#64748b]">
            <span>Failed: {data.task_counts.failed || 0}</span>
            <span>Declined: {data.task_counts.declined || 0}</span>
          </div>
        </Card>

        {/* Cost sparkline */}
        <Card title="7-Day Cost Trend">
          <ResponsiveContainer width="100%" height={120}>
            <BarChart data={chartData}>
              <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={v => `$${v}`} width={35} />
              <Tooltip
                contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6, fontSize: 12 }}
                labelStyle={{ color: '#94a3b8' }}
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                formatter={(v: any) => [`$${Number(v || 0).toFixed(2)}`]}
              />
              {AGENT_IDS.map(id => (
                <Bar key={id} dataKey={shortName(id)} stackId="cost" fill={agentColor(id)} radius={[0, 0, 0, 0]} />
              ))}
            </BarChart>
          </ResponsiveContainer>
          <div className="text-right text-xs text-[#64748b] mt-1">
            7-day total: ${data.cost_trend.reduce((s, d) => s + d.total, 0).toFixed(2)}
          </div>
        </Card>

        {/* Drive tensions */}
        <Card title="Drive Tensions">
          <div className="space-y-2.5">
            {data.drives.map(drive => (
              <div key={drive.name} className="flex items-start justify-between gap-3">
                <span className="text-sm text-[#f1f5f9] shrink-0">{drive.name}</span>
                <div className="shrink-0">
                  <TensionBadge tension={drive.tension} />
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Recent activity */}
      <Card title="Recent Activity">
        <div className="space-y-0">
          {data.recent_activity.slice(0, 10).map((entry, i) => (
            <div
              key={i}
              className="flex items-start gap-3 py-2 px-1 border-b border-[#334155]/30 last:border-0 hover:bg-[#334155]/10 rounded transition-colors"
            >
              <span className="text-[10px] text-[#475569] font-mono w-28 shrink-0 pt-0.5 text-right" title={new Date(entry.timestamp).toLocaleString()}>
                {(() => {
                  const d = new Date(entry.timestamp)
                  const now = new Date()
                  const isToday = d.toLocaleDateString() === now.toLocaleDateString()
                  if (isToday) return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                  return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                })()}
              </span>
              <span className="w-20 shrink-0">
                <AgentName id={entry.agent} short />
              </span>
              <span className="text-[10px] text-[#64748b] w-auto shrink-0 bg-[#334155]/30 px-1.5 py-0.5 rounded">
                {humanizeAction(entry.action)}
              </span>
              <span className="text-xs text-[#94a3b8] truncate">{entry.detail}</span>
            </div>
          ))}
          {data.recent_activity.length === 0 && (
            <div className="text-sm text-[#475569] italic py-8 text-center">No recent activity</div>
          )}
          {data.recent_activity.length > 10 && (
            <Link to="/timeline" className="block text-center text-xs text-[#38bdf8] hover:text-[#7dd3fc] py-2 mt-1 transition-colors no-underline">
              View full timeline &rarr;
            </Link>
          )}
        </div>
      </Card>
    </div>
  )
}
