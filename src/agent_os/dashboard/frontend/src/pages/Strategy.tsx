import { useState } from 'react'
import { useProposals, useDecisions, type Proposal, type Decision } from '../api/hooks'
import Card from '../components/Card'
import AgentName from '../components/AgentName'
import TimeAgo from '../components/TimeAgo'
import Loading from '../components/Loading'
import Markdown from '../components/Markdown'

function ProposalItem({ item, expanded, onToggle }: { item: Proposal; expanded: boolean; onToggle: () => void }) {
  return (
    <div className="border-b border-[#334155]/30 last:border-0">
      <div
        onClick={onToggle}
        className="flex items-center gap-3 py-3 px-3 cursor-pointer hover:bg-[#334155]/20 transition-colors rounded"
      >
        <span className="text-[10px] font-mono text-[#334155] select-none">{expanded ? '\u25BC' : '\u25B6'}</span>
        <span className="w-20 shrink-0 text-sm">
          <AgentName id={item.proposed_by} short />
        </span>
        <span className="text-sm text-[#f1f5f9] flex-1 truncate">{item.title}</span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
          item.status === 'active' ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/20' :
          item.status === 'approved' ? 'bg-green-500/20 text-green-400 border border-green-500/20' :
          'bg-[#334155] text-[#64748b] border border-[#334155]'
        }`}>
          {item.status}
        </span>
        <span className="text-xs text-[#475569] shrink-0"><TimeAgo timestamp={item.date} /></span>
      </div>
      {expanded && (
        <div className="px-3 pb-4 ml-8 border-l-2 border-[#334155] pl-4">
          <Markdown>{item.body}</Markdown>
        </div>
      )}
    </div>
  )
}

function DecisionItem({ item, expanded, onToggle }: { item: Decision; expanded: boolean; onToggle: () => void }) {
  return (
    <div className="border-b border-[#334155]/30 last:border-0">
      <div
        onClick={onToggle}
        className="flex items-center gap-3 py-3 px-3 cursor-pointer hover:bg-[#334155]/20 transition-colors rounded"
      >
        <span className="text-[10px] font-mono text-[#334155] select-none">{expanded ? '\u25BC' : '\u25B6'}</span>
        <span className="text-[10px] text-[#475569] font-mono w-32 shrink-0 truncate" title={item.id}>{item.id}</span>
        <span className="text-sm text-[#f1f5f9] flex-1 truncate">{item.title}</span>
        {item.tags && item.tags.length > 0 && (
          <span className="flex gap-1 shrink-0">
            {item.tags.slice(0, 3).map(t => (
              <span key={t} className="bg-[#334155] text-[#94a3b8] px-1.5 py-0.5 rounded text-[10px]">{t}</span>
            ))}
          </span>
        )}
        <span className="text-xs text-[#475569] shrink-0">{item.date}</span>
      </div>
      {expanded && (
        <div className="px-3 pb-4 space-y-2">
          {item.decided_by && (
            <div className="flex items-center gap-2 text-xs text-[#64748b] ml-8 pl-4 border-l-2 border-[#334155]">
              <span>Decided by: <span className="text-[#94a3b8]">{item.decided_by}</span></span>
            </div>
          )}
          <div className="ml-8 pl-4 border-l-2 border-[#334155]">
            <div className="text-sm text-[#94a3b8] whitespace-pre-wrap font-mono text-xs leading-relaxed">
              {item.body}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function Strategy() {
  const { data: proposals, isLoading: loadingProposals } = useProposals()
  const { data: decisions, isLoading: loadingDecisions } = useDecisions()
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [tab, setTab] = useState<'proposals' | 'decisions'>('proposals')

  if (loadingProposals || loadingDecisions) return <Loading />

  const activeProposals = proposals?.active || []
  const decidedProposals = proposals?.decided || []
  const allDecisions = decisions || []

  const toggle = (id: string) => setExpandedId(expandedId === id ? null : id)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Strategy</h2>
        <div className="flex gap-1 bg-[#0f172a] rounded-lg p-0.5 border border-[#334155]">
          <button
            onClick={() => setTab('proposals')}
            className={`px-3 py-1.5 text-xs rounded-md transition-colors ${tab === 'proposals' ? 'bg-[#334155] text-[#f1f5f9]' : 'text-[#64748b] hover:text-[#94a3b8]'}`}
          >
            Proposals
            {activeProposals.length > 0 && (
              <span className="ml-1.5 bg-yellow-500/20 text-yellow-400 text-[10px] px-1.5 py-0.5 rounded-full">
                {activeProposals.length}
              </span>
            )}
          </button>
          <button
            onClick={() => setTab('decisions')}
            className={`px-3 py-1.5 text-xs rounded-md transition-colors ${tab === 'decisions' ? 'bg-[#334155] text-[#f1f5f9]' : 'text-[#64748b] hover:text-[#94a3b8]'}`}
          >
            Decisions
            <span className="ml-1.5 text-[10px] text-[#475569]">{allDecisions.length}</span>
          </button>
        </div>
      </div>

      {tab === 'proposals' && (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {/* Active proposals */}
          <Card title={`Active (${activeProposals.length})`}>
            <div className="max-h-[calc(100vh-280px)] overflow-auto">
              {activeProposals.map(p => (
                <ProposalItem
                  key={p.id || p._file}
                  item={p}
                  expanded={expandedId === (p.id || p._file)}
                  onToggle={() => toggle(p.id || p._file)}
                />
              ))}
              {activeProposals.length === 0 && (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <div className="text-[#334155] text-2xl mb-2">!</div>
                  <div className="text-sm text-[#475569]">No active proposals</div>
                  <div className="text-xs text-[#334155] mt-1">Proposals are created by agents via the filesystem</div>
                </div>
              )}
            </div>
          </Card>

          {/* Decided proposals */}
          <Card title="Recently Decided">
            <div className="max-h-[calc(100vh-280px)] overflow-auto">
              {decidedProposals.map(p => (
                <ProposalItem
                  key={p.id || p._file}
                  item={p}
                  expanded={expandedId === (p.id || p._file)}
                  onToggle={() => toggle(p.id || p._file)}
                />
              ))}
              {decidedProposals.length === 0 && (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <div className="text-sm text-[#475569]">No decided proposals yet</div>
                </div>
              )}
            </div>
          </Card>
        </div>
      )}

      {tab === 'decisions' && (
        <Card title={`Decision History (${allDecisions.length})`}>
          <div className="max-h-[calc(100vh-200px)] overflow-auto">
            {allDecisions.map(d => (
              <DecisionItem
                key={d.id || d._file}
                item={d}
                expanded={expandedId === (d.id || d._file)}
                onToggle={() => toggle(d.id || d._file)}
              />
            ))}
            {allDecisions.length === 0 && (
              <div className="flex flex-col items-center justify-center py-16 text-center">
                <div className="text-[#334155] text-2xl mb-2">!</div>
                <div className="text-sm text-[#475569]">No decisions recorded yet</div>
              </div>
            )}
          </div>
        </Card>
      )}
    </div>
  )
}
