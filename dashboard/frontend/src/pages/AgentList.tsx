import { Link } from 'react-router-dom'
import { useAgents } from '../api/hooks'
import AgentName, { agentColor } from '../components/AgentName'
import TimeAgo from '../components/TimeAgo'
import Loading from '../components/Loading'

export default function AgentList() {
  const { data: agents, isLoading } = useAgents()

  if (isLoading) return <Loading />

  if (!agents || agents.length === 0) {
    return (
      <div className="space-y-4">
        <h2 className="text-xl font-semibold">Agents</h2>
        <div className="flex items-center justify-center h-64 text-[#475569] text-sm">
          No agents found
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Agents</h2>
        <div className="text-xs text-[#64748b]">
          {agents.length} agents &middot; ${agents.reduce((s, a) => s + a.cost_today, 0).toFixed(2)} today
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
        {agents.map(agent => {
          const color = agentColor(agent.id)
          const isActive = agent.cycles_today > 0

          return (
            <Link key={agent.id} to={`/agents/${agent.id}`} className="no-underline group">
              <div
                className="bg-[#1e293b] border border-[#334155] rounded-lg overflow-hidden hover:border-[#475569] transition-all duration-200 h-full"
              >
                {/* Color accent bar */}
                <div className="h-1" style={{ backgroundColor: color }} />

                <div className="p-4">
                  {/* Header: name + status */}
                  <div className="flex items-start justify-between mb-3">
                    <div>
                      <div className="text-lg font-semibold" style={{ color }}>
                        <AgentName id={agent.id} short />
                      </div>
                      <div className="text-xs text-[#64748b] mt-0.5">{agent.role}</div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <div className={`w-2 h-2 rounded-full ${isActive ? 'bg-green-400' : 'bg-[#475569]'}`} />
                      <span className="text-[10px] text-[#64748b]">
                        <TimeAgo timestamp={agent.last_active} />
                      </span>
                    </div>
                  </div>

                  {/* Stats row */}
                  <div className="flex items-center gap-4 mb-3">
                    <div className="flex items-baseline gap-1">
                      <span className="text-xl font-bold text-[#f1f5f9]">${agent.cost_today.toFixed(2)}</span>
                      <span className="text-[10px] text-[#475569]">today</span>
                    </div>
                    <div className="flex items-baseline gap-1">
                      <span className="text-sm font-medium text-[#94a3b8]">{agent.cycles_today}</span>
                      <span className="text-[10px] text-[#475569]">cycles</span>
                    </div>
                    {agent.inbox_count! > 0 && (
                      <div className="flex items-center gap-1 ml-auto">
                        <span className="text-xs text-yellow-400 font-medium">{agent.inbox_count}</span>
                        <span className="text-[10px] text-yellow-400/70">inbox</span>
                      </div>
                    )}
                  </div>

                  {/* Current task */}
                  {agent.current_task ? (
                    <div className="bg-[#0f172a] rounded px-3 py-2 border border-[#334155]/50">
                      <div className="text-[10px] text-[#475569] uppercase tracking-wider mb-0.5">Working on</div>
                      <div className="text-xs text-[#94a3b8] line-clamp-2">{agent.current_task.title}</div>
                    </div>
                  ) : (
                    <div className="bg-[#0f172a]/50 rounded px-3 py-2 border border-[#334155]/30">
                      <div className="text-xs text-[#475569] italic">No active task</div>
                    </div>
                  )}
                </div>
              </div>
            </Link>
          )
        })}
      </div>
    </div>
  )
}
