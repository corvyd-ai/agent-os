import { useState } from 'react'
import { RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip } from 'recharts'
import { useHealthMetrics } from '../api/hooks'
import type { AgentHealth, GovernanceHealth, HealthTrend } from '../api/hooks'
import Card from '../components/Card'
import AgentName, { agentColor } from '../components/AgentName'
import Loading from '../components/Loading'

const AGENT_IDS = [
  'agent-000-steward',
  'agent-001-maker',
  'agent-003-operator',
  'agent-005-grower',
  'agent-006-strategist',
]

const CATEGORY_LABELS: Record<string, string> = {
  autonomy: 'Autonomy',
  effectiveness: 'Effectiveness',
  efficiency: 'Efficiency',
  system_health: 'System Health',
}

function scoreColor(score: number): string {
  if (score >= 70) return '#4ade80'
  if (score >= 40) return '#fbbf24'
  return '#f87171'
}

function trendIcon(direction: string): string {
  if (direction === 'improving') return '\u2191'
  if (direction === 'declining') return '\u2193'
  return '\u2192'
}

function trendColor(direction: string): string {
  if (direction === 'improving') return '#4ade80'
  if (direction === 'declining') return '#f87171'
  return '#64748b'
}

function ScoreRing({ score, size = 80, label }: { score: number; size?: number; label?: string }) {
  const radius = (size - 8) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference - (score / 100) * circumference
  const color = scoreColor(score)

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={size} height={size} className="transform -rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="#334155" strokeWidth={4} />
        <circle
          cx={size / 2} cy={size / 2} r={radius}
          fill="none" stroke={color} strokeWidth={4}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
        />
      </svg>
      <div className="absolute flex items-center justify-center" style={{ width: size, height: size }}>
        <span className="text-lg font-bold" style={{ color }}>{Math.round(score)}</span>
      </div>
      {label && <span className="text-[10px] text-[#64748b]">{label}</span>}
    </div>
  )
}

function MetricRow({ label, value, format = 'number' }: { label: string; value: number; format?: 'number' | 'percent' | 'currency' | 'duration' }) {
  let display: string
  if (format === 'percent') display = `${(value * 100).toFixed(1)}%`
  else if (format === 'currency') display = `$${value.toFixed(4)}`
  else if (format === 'duration') {
    if (value > 60000) display = `${(value / 60000).toFixed(1)}m`
    else if (value > 1000) display = `${(value / 1000).toFixed(1)}s`
    else display = `${Math.round(value)}ms`
  }
  else display = value.toFixed(value % 1 === 0 ? 0 : 2)

  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-xs text-[#94a3b8]">{label}</span>
      <span className="text-xs font-mono text-[#f1f5f9]">{display}</span>
    </div>
  )
}

function AgentHealthCard({ health, trend }: { health: AgentHealth; trend: HealthTrend }) {
  const [expanded, setExpanded] = useState(false)
  const color = agentColor(health.agent_id)

  const radarData = [
    { category: 'Autonomy', score: health.autonomy.score },
    { category: 'Effective', score: health.effectiveness.score },
    { category: 'Efficient', score: health.efficiency.score },
    { category: 'System', score: health.system_health.score },
  ]

  return (
    <div className="bg-[#1e293b] border border-[#334155] rounded-lg overflow-hidden">
      <div className="h-0.5" style={{ backgroundColor: color }} />
      <div
        className="p-4 cursor-pointer hover:bg-[#334155]/20 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center justify-between mb-3">
          <AgentName id={health.agent_id} short />
          <div className="flex items-center gap-2">
            <span
              className="text-xs font-mono"
              style={{ color: trendColor(trend.direction) }}
            >
              {trendIcon(trend.direction)} {trend.delta > 0 ? '+' : ''}{trend.delta}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div className="relative">
            <ScoreRing score={health.composite_score} size={64} />
          </div>
          <div className="flex-1 grid grid-cols-2 gap-x-4 gap-y-1">
            {Object.entries(CATEGORY_LABELS).map(([key, label]) => {
              const catScore = (health[key as keyof AgentHealth] as { score: number })?.score ?? 0
              return (
                <div key={key} className="flex items-center justify-between">
                  <span className="text-[10px] text-[#64748b]">{label}</span>
                  <span className="text-xs font-mono" style={{ color: scoreColor(catScore) }}>
                    {Math.round(catScore)}
                  </span>
                </div>
              )
            })}
          </div>
        </div>

        <div className="flex justify-between mt-2 pt-2 border-t border-[#334155]/50">
          <span className="text-[10px] text-[#475569]">7d: {trend.score_7d.toFixed(1)}</span>
          <span className="text-[10px] text-[#475569]">30d: {trend.score_30d.toFixed(1)}</span>
          <span className="text-[10px] text-[#475569]">{expanded ? '\u25B2 less' : '\u25BC more'}</span>
        </div>
      </div>

      {expanded && (
        <div className="px-4 pb-4 space-y-4 border-t border-[#334155]">
          {/* Radar chart */}
          <div className="flex justify-center pt-3">
            <ResponsiveContainer width={200} height={160}>
              <RadarChart data={radarData}>
                <PolarGrid stroke="#334155" />
                <PolarAngleAxis dataKey="category" tick={{ fill: '#64748b', fontSize: 10 }} />
                <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
                <Radar dataKey="score" stroke={color} fill={color} fillOpacity={0.2} />
              </RadarChart>
            </ResponsiveContainer>
          </div>

          {/* Autonomy details */}
          <div>
            <h4 className="text-xs font-medium text-[#94a3b8] mb-1">Autonomy</h4>
            <MetricRow label="Productive cycle ratio" value={health.autonomy.productive_cycle_ratio} format="percent" />
            <MetricRow label="Escalation rate" value={health.autonomy.escalation_rate} format="percent" />
            <MetricRow label="Self-initiated work" value={health.autonomy.self_initiated_ratio} format="percent" />
            <MetricRow label="Decision autonomy" value={health.autonomy.decision_autonomy} format="percent" />
          </div>

          {/* Effectiveness details */}
          <div>
            <h4 className="text-xs font-medium text-[#94a3b8] mb-1">Effectiveness</h4>
            <MetricRow label="Completion rate" value={health.effectiveness.completion_rate} format="percent" />
            <MetricRow label="Throughput / day" value={health.effectiveness.throughput_per_day} />
            <MetricRow label="Mean task duration" value={health.effectiveness.mean_duration_ms} format="duration" />
            <MetricRow label="Tasks done" value={health.effectiveness.tasks_done} />
            <MetricRow label="Tasks failed" value={health.effectiveness.tasks_failed} />
          </div>

          {/* Efficiency details */}
          <div>
            <h4 className="text-xs font-medium text-[#94a3b8] mb-1">Efficiency</h4>
            <MetricRow label="Total cost" value={health.efficiency.total_cost_usd} format="currency" />
            <MetricRow label="Cost / task" value={health.efficiency.cost_per_task_usd} format="currency" />
            <MetricRow label="Cost / turn" value={health.efficiency.cost_per_turn_usd} format="currency" />
            <MetricRow label="Idle cost ratio" value={health.efficiency.idle_cost_ratio} format="percent" />
          </div>

          {/* System Health details */}
          <div>
            <h4 className="text-xs font-medium text-[#94a3b8] mb-1">System Health</h4>
            <MetricRow label="Error rate" value={health.system_health.error_rate} format="percent" />
            <MetricRow label="Schedule adherence" value={health.system_health.schedule_adherence} format="percent" />
            <MetricRow label="Active days" value={health.system_health.active_days} />
            <MetricRow label="Recovery time" value={health.system_health.mean_recovery_minutes} />
          </div>
        </div>
      )}
    </div>
  )
}

function GovernanceCard({ governance, governance30d }: { governance: GovernanceHealth; governance30d: GovernanceHealth }) {
  return (
    <Card title="Governance Health">
      <div className="flex items-center gap-4 mb-4">
        <div className="relative">
          <ScoreRing score={governance.score} size={64} />
        </div>
        <div className="flex-1">
          <div className="text-sm text-[#f1f5f9]">
            Coordination effectiveness across proposals, decisions, and threads.
          </div>
          <div className="text-[10px] text-[#475569] mt-1">
            7d: {governance.score.toFixed(1)} / 30d: {governance30d.score.toFixed(1)}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-0">
        <MetricRow label="Active proposals" value={governance.active_proposals} />
        <MetricRow label="Decided (period)" value={governance.decided_proposals_in_period} />
        <MetricRow label="Proposal throughput" value={governance.proposal_throughput} format="percent" />
        <MetricRow label="Decisions (period)" value={governance.decisions_in_period} />
        <MetricRow label="Total threads" value={governance.total_threads} />
        <MetricRow label="Resolved threads" value={governance.resolved_threads} />
        <MetricRow label="Resolution rate" value={governance.resolution_rate} format="percent" />
        <MetricRow label="Mean response (hrs)" value={governance.mean_response_hours} />
      </div>
    </Card>
  )
}

function SystemCompositeBar({ agents }: {
  agents: Record<string, AgentHealth>
}) {
  const chartData = AGENT_IDS.map(id => {
    const h = agents[id]
    if (!h) return { name: id.split('-').slice(2).join(' '), score: 0 }
    return {
      name: id.split('-').slice(2).join(' '),
      autonomy: h.autonomy.score,
      effectiveness: h.effectiveness.score,
      efficiency: h.efficiency.score,
      system: h.system_health.score,
      fill: agentColor(id),
    }
  })

  return (
    <Card title="Agent Scores Comparison">
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={chartData} layout="vertical">
          <XAxis type="number" domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" tick={{ fill: '#94a3b8', fontSize: 11 }} width={80} axisLine={false} tickLine={false} />
          <Tooltip
            contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6, fontSize: 12 }}
            labelStyle={{ color: '#94a3b8' }}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            formatter={(v: any) => [Number(v || 0).toFixed(1)]}
          />
          <Bar dataKey="autonomy" stackId="scores" fill="#38bdf8" name="Autonomy" />
          <Bar dataKey="effectiveness" stackId="scores" fill="#a78bfa" name="Effectiveness" />
          <Bar dataKey="efficiency" stackId="scores" fill="#4ade80" name="Efficiency" />
          <Bar dataKey="system" stackId="scores" fill="#fbbf24" name="System" />
        </BarChart>
      </ResponsiveContainer>
      <div className="flex gap-4 justify-center mt-2">
        {[
          { label: 'Autonomy', color: '#38bdf8' },
          { label: 'Effectiveness', color: '#a78bfa' },
          { label: 'Efficiency', color: '#4ade80' },
          { label: 'System', color: '#fbbf24' },
        ].map(item => (
          <div key={item.label} className="flex items-center gap-1.5">
            <div className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: item.color }} />
            <span className="text-[10px] text-[#64748b]">{item.label}</span>
          </div>
        ))}
      </div>
    </Card>
  )
}

export default function Health() {
  const { data, isLoading, error } = useHealthMetrics()

  if (isLoading) return <Loading />
  if (error || !data) return <div className="text-red-400">Failed to load health metrics</div>

  const { current, baseline, trends } = data
  const sysT = trends.system

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">System Health</h2>
        <div className="flex items-center gap-3 text-xs text-[#64748b]">
          <span
            className="font-mono"
            style={{ color: trendColor(sysT.direction) }}
          >
            {trendIcon(sysT.direction)} {sysT.delta > 0 ? '+' : ''}{sysT.delta}
          </span>
          <span>7d: {sysT.score_7d.toFixed(1)}</span>
          <span>30d: {sysT.score_30d.toFixed(1)}</span>
        </div>
      </div>

      {/* System composite score */}
      <div className="bg-[#1e293b] border border-[#334155] rounded-lg overflow-hidden">
        <div className="h-0.5 bg-[#38bdf8]" />
        <div className="p-5 flex items-center gap-6">
          <div className="relative">
            <ScoreRing score={current.system_composite} size={96} label="System" />
          </div>
          <div className="flex-1">
            <div className="text-lg font-semibold text-[#f1f5f9]">
              Operational Health Score
            </div>
            <div className="text-sm text-[#94a3b8] mt-1">
              Composite of autonomy, effectiveness, efficiency, governance, and system reliability
              across all {AGENT_IDS.length} agents over the last 7 days.
            </div>
            <div className="flex gap-4 mt-3">
              <div className="text-center">
                <div className="text-lg font-bold" style={{ color: scoreColor(current.governance.score) }}>
                  {Math.round(current.governance.score)}
                </div>
                <div className="text-[10px] text-[#475569]">Governance</div>
              </div>
              {AGENT_IDS.map(id => {
                const agent = current.agents[id]
                if (!agent) return null
                return (
                  <div key={id} className="text-center">
                    <div className="text-lg font-bold" style={{ color: agentColor(id) }}>
                      {Math.round(agent.composite_score)}
                    </div>
                    <div className="text-[10px] text-[#475569]">
                      <AgentName id={id} short />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Agent score comparison chart */}
      <SystemCompositeBar agents={current.agents} />

      {/* Per-agent health cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {AGENT_IDS.map(id => {
          const health = current.agents[id]
          const trend = trends.agents[id]
          if (!health || !trend) return null
          return <AgentHealthCard key={id} health={health} trend={trend} />
        })}
      </div>

      {/* Governance card */}
      <GovernanceCard governance={current.governance} governance30d={baseline.governance} />
    </div>
  )
}
