const AGENT_COLORS: Record<string, string> = {
  'agent-000-steward': '#38bdf8',
  'agent-001-maker': '#a78bfa',
  'agent-003-operator': '#4ade80',
  'agent-005-grower': '#fbbf24',
  'agent-006-strategist': '#f87171',
}

function shortName(agentId: string): string {
  const parts = agentId.split('-')
  return parts.length > 2 ? parts.slice(2).join(' ').replace(/\b\w/g, c => c.toUpperCase()) : agentId
}

export function agentColor(agentId: string): string {
  return AGENT_COLORS[agentId] || '#94a3b8'
}

export default function AgentName({ id, short }: { id: string; short?: boolean }) {
  const color = agentColor(id)
  const name = short ? shortName(id) : id
  return <span style={{ color }}>{name}</span>
}
