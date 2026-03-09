import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import { useDailyCosts, useCostSummary } from '../api/hooks'
import Card from '../components/Card'
import { agentColor } from '../components/AgentName'
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

export default function Costs() {
  const { data: daily, isLoading: loadingDaily } = useDailyCosts(7)
  const { data: summary, isLoading: loadingSummary } = useCostSummary(7)

  if (loadingDaily || loadingSummary) return <Loading />

  const chartData = (daily || []).map(d => ({
    date: d.date.slice(5),
    ...Object.fromEntries(AGENT_IDS.map(id => [shortName(id), d.by_agent[id] || 0])),
    total: d.total,
  }))

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Costs</h2>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-4 gap-3">
          <Card>
            <div className="text-xs text-[#64748b]">7-Day Total</div>
            <div className="text-2xl font-bold mt-1">${summary.total.toFixed(2)}</div>
          </Card>
          <Card>
            <div className="text-xs text-[#64748b]">Daily Average</div>
            <div className="text-2xl font-bold mt-1">${summary.avg_daily.toFixed(2)}</div>
          </Card>
          <Card>
            <div className="text-xs text-[#64748b]">Total Invocations</div>
            <div className="text-2xl font-bold mt-1">{summary.invocations}</div>
          </Card>
          <Card>
            <div className="text-xs text-[#64748b]">Avg Cost/Invocation</div>
            <div className="text-2xl font-bold mt-1">
              ${summary.invocations > 0 ? (summary.total / summary.invocations).toFixed(2) : '0.00'}
            </div>
          </Card>
        </div>
      )}

      {/* Daily stacked bar chart */}
      <Card title="Daily Spend by Agent">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={chartData}>
            <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fill: '#64748b', fontSize: 11 }} axisLine={false} tickLine={false} tickFormatter={v => `$${v}`} width={45} />
            <Tooltip
              contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6, fontSize: 12 }}
              labelStyle={{ color: '#94a3b8' }}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              formatter={(v: any, name: any) => [`$${Number(v || 0).toFixed(2)}`, String(name)]}
            />
            <Legend
              formatter={(value: string) => <span style={{ color: '#94a3b8', fontSize: 11 }}>{value}</span>}
            />
            {AGENT_IDS.map(id => (
              <Bar key={id} dataKey={shortName(id)} stackId="cost" fill={agentColor(id)} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </Card>

      <div className="grid grid-cols-2 gap-4">
        {/* Per-agent breakdown */}
        <Card title="Per-Agent Breakdown">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[#64748b] text-xs border-b border-[#334155]">
                <th className="text-left py-2">Agent</th>
                <th className="text-right py-2">7-Day Total</th>
                <th className="text-right py-2">% of Spend</th>
              </tr>
            </thead>
            <tbody>
              {summary && Object.entries(summary.by_agent)
                .sort((a, b) => b[1].total - a[1].total)
                .map(([id, data]) => (
                  <tr key={id} className="border-b border-[#334155]/30">
                    <td className="py-2" style={{ color: agentColor(id) }}>{data.name}</td>
                    <td className="text-right py-2">${data.total.toFixed(2)}</td>
                    <td className="text-right py-2 text-[#64748b]">
                      {summary.total > 0 ? ((data.total / summary.total) * 100).toFixed(1) : 0}%
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </Card>

        {/* Per-task-type breakdown */}
        <Card title="By Task Type">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[#64748b] text-xs border-b border-[#334155]">
                <th className="text-left py-2">Task Type</th>
                <th className="text-right py-2">Cost</th>
              </tr>
            </thead>
            <tbody>
              {summary && Object.entries(summary.by_task_type)
                .slice(0, 15)
                .map(([type, cost]) => (
                  <tr key={type} className="border-b border-[#334155]/30">
                    <td className="py-2 text-[#94a3b8] text-xs">{humanizeAction(type)}</td>
                    <td className="text-right py-2">${cost.toFixed(2)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </Card>
      </div>
    </div>
  )
}
