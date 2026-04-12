import { useParams, Link } from 'react-router-dom'
import { useAgent, useAgentLogs, useAutonomy } from '../api/hooks'
import Card from '../components/Card'
import AgentName, { agentColor } from '../components/AgentName'
import TimeAgo from '../components/TimeAgo'
import Loading from '../components/Loading'
import Markdown from '../components/Markdown'
import { humanizeAction } from '../utils/humanize'

const AUTONOMY_BADGES: Record<string, { color: string; label: string }> = {
  low: { color: '#38bdf8', label: 'Execute only' },
  medium: { color: '#fbbf24', label: 'Tasks → backlog' },
  high: { color: '#4ade80', label: 'Full autonomy' },
}

export default function AgentDetail() {
  const { id } = useParams<{ id: string }>()
  const { data: agent, isLoading } = useAgent(id!)
  const { data: logs } = useAgentLogs(id!)
  const { data: autonomyData } = useAutonomy()

  if (isLoading || !agent) return <Loading />

  const color = agentColor(agent.id)

  return (
    <div className="space-y-4">
      {/* Header with color accent */}
      <div className="bg-[#1e293b] border border-[#334155] rounded-lg overflow-hidden">
        <div className="h-1" style={{ backgroundColor: color }} />
        <div className="p-4 flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold" style={{ color }}><AgentName id={agent.id} short /></h2>
            <p className="text-sm text-[#64748b]">{agent.role}</p>
          </div>
          <div className="flex items-center gap-6">
            {/* Autonomy badge (edit on Controls page) */}
            {autonomyData && (() => {
              const level = autonomyData.agents[agent.id] || autonomyData.default_level
              const badge = AUTONOMY_BADGES[level] || AUTONOMY_BADGES.medium
              return (
                <Link to="/controls" className="text-right no-underline group">
                  <div className="text-sm font-medium group-hover:underline" style={{ color: badge.color }}>
                    {level.charAt(0).toUpperCase() + level.slice(1)} Autonomy
                  </div>
                  <div className="text-[10px] text-[#64748b]">{badge.label}</div>
                </Link>
              )
            })()}
            <div className="text-right">
              <div className="text-2xl font-bold text-[#f1f5f9]">${agent.cost_today.toFixed(2)} <span className="text-sm font-normal text-[#64748b]">today</span></div>
              <div className="text-xs text-[#64748b]">
                {agent.cycles_today} cycles &middot; Last active: <TimeAgo timestamp={agent.last_active} />
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Soul */}
        <Card title="Soul">
          <div className="max-h-96 overflow-auto">
            {agent.soul ? <Markdown>{agent.soul}</Markdown> : (
              <div className="flex items-center justify-center py-8 text-center">
                <span className="text-[#475569] italic text-sm">No soul document</span>
              </div>
            )}
          </div>
        </Card>

        {/* Working Memory */}
        <Card title="Working Memory">
          <div className="max-h-96 overflow-auto">
            {agent.working_memory ? <Markdown>{agent.working_memory}</Markdown> : (
              <div className="flex items-center justify-center py-8 text-center">
                <span className="text-[#475569] italic text-sm">No working memory</span>
              </div>
            )}
          </div>
        </Card>
      </div>

      {/* Activity log */}
      <Card title="Today's Activity">
        <div className="space-y-0 max-h-96 overflow-auto">
          {(logs || []).map((entry, i) => (
            <div
              key={i}
              className="flex items-start gap-3 py-2 px-1 border-b border-[#334155]/30 last:border-0 hover:bg-[#334155]/10 rounded transition-colors"
            >
              <span className="text-[10px] text-[#475569] font-mono w-14 shrink-0 pt-0.5 text-right">
                {new Date(entry.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
              <span className="text-[10px] text-[#64748b] shrink-0 bg-[#334155]/30 px-1.5 py-0.5 rounded whitespace-nowrap">
                {humanizeAction(entry.action)}
              </span>
              <span className="text-xs text-[#94a3b8] min-w-0 break-words">{entry.detail}</span>
            </div>
          ))}
          {(!logs || logs.length === 0) && (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <div className="text-[#334155] text-2xl mb-2">@</div>
              <div className="text-sm text-[#475569]">No activity today</div>
              <div className="text-xs text-[#334155] mt-1">Activity will appear here once this agent runs a cycle</div>
            </div>
          )}
        </div>
      </Card>

      {/* Journal */}
      {agent.journal && (
        <Card title="Journal (recent entries)">
          <div className="text-sm text-[#94a3b8] whitespace-pre-wrap max-h-96 overflow-auto font-mono text-xs leading-relaxed">
            {agent.journal}
          </div>
        </Card>
      )}
    </div>
  )
}
