import { useState, useMemo } from 'react'
import { useBroadcasts, useThreads, useHumanInbox, useInboxSummary, type Message } from '../api/hooks'
import Card from '../components/Card'
import AgentName, { agentColor } from '../components/AgentName'
import TimeAgo from '../components/TimeAgo'
import Loading from '../components/Loading'
import Markdown from '../components/Markdown'

/** Sort messages by date, newest first. */
function sortByDate(items: Message[]): Message[] {
  return [...items].sort((a, b) => {
    const dateA = new Date(a.date || '0').getTime()
    const dateB = new Date(b.date || '0').getTime()
    return dateB - dateA
  })
}

function MessageItem({ msg, expanded, onToggle }: { msg: Message; expanded: boolean; onToggle: () => void }) {
  const color = agentColor(msg.from)
  return (
    <div className="border-b border-[#334155]/30 last:border-0">
      <div
        onClick={onToggle}
        className="flex items-center gap-3 py-2.5 px-3 cursor-pointer hover:bg-[#334155]/20 transition-colors rounded"
      >
        <span className="text-[10px] font-mono text-[#334155] select-none">{expanded ? '\u25BC' : '\u25B6'}</span>
        <span className="w-20 shrink-0 text-sm">
          <AgentName id={msg.from} short />
        </span>
        <span className="text-sm text-[#f1f5f9] flex-1 truncate">{msg.subject}</span>
        {msg.urgency === 'high' && (
          <span className="text-[10px] bg-red-500/20 text-red-400 px-1.5 py-0.5 rounded border border-red-500/20">urgent</span>
        )}
        <span className="text-xs text-[#475569] shrink-0"><TimeAgo timestamp={msg.date} /></span>
      </div>
      {expanded && (
        <div className="px-3 pb-4 ml-8 border-l-2 pl-4" style={{ borderLeftColor: color + '40' }}>
          <Markdown>{msg.body}</Markdown>
        </div>
      )}
    </div>
  )
}

/** Thread data has different field names — normalize to Message shape for rendering. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function normalizeThread(thread: any): Message {
  return {
    id: thread.id || thread._file,
    from: thread.started_by || 'unknown',
    date: thread.started || thread.date || '',
    subject: thread.topic || thread.subject || '(untitled thread)',
    body: thread.body || '',
    urgency: thread.urgency,
    _file: thread._file,
  }
}

function EmptyState({ icon, message, detail }: { icon: string; message: string; detail?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="text-[#334155] text-2xl mb-2">{icon}</div>
      <div className="text-sm text-[#475569]">{message}</div>
      {detail && <div className="text-xs text-[#334155] mt-1">{detail}</div>}
    </div>
  )
}

const TABS = ['broadcasts', 'threads', 'human', 'inboxes'] as const

export default function Messages() {
  const { data: broadcasts, isLoading: loadingBroadcasts } = useBroadcasts()
  const { data: threads } = useThreads()
  const { data: humanInbox } = useHumanInbox()
  const { data: inboxSummary } = useInboxSummary()
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [tab, setTab] = useState<typeof TABS[number]>('broadcasts')

  const sortedBroadcasts = useMemo(() => sortByDate(broadcasts || []), [broadcasts])
  const normalizedThreads = useMemo(() => sortByDate((threads || []).map(normalizeThread)), [threads])
  const sortedHumanInbox = useMemo(() => sortByDate(humanInbox || []), [humanInbox])

  if (loadingBroadcasts) return <Loading />

  const toggle = (id: string) => setExpandedId(expandedId === id ? null : id)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Messages</h2>
        <div className="flex gap-1 bg-[#0f172a] rounded-lg p-0.5 border border-[#334155]">
          {TABS.map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-1.5 text-xs rounded-md transition-colors ${tab === t ? 'bg-[#334155] text-[#f1f5f9]' : 'text-[#64748b] hover:text-[#94a3b8]'}`}
            >
              {t.charAt(0).toUpperCase() + t.slice(1)}
              {t === 'human' && humanInbox && humanInbox.length > 0 && (
                <span className="ml-1.5 bg-yellow-500/20 text-yellow-400 text-[10px] px-1.5 py-0.5 rounded-full">
                  {humanInbox.length}
                </span>
              )}
              {t === 'broadcasts' && broadcasts && (
                <span className="ml-1.5 text-[10px] text-[#475569]">{broadcasts.length}</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {tab === 'broadcasts' && (
        <Card title="Broadcasts">
          <div className="max-h-[calc(100vh-200px)] overflow-auto">
            {sortedBroadcasts.map(msg => (
              <MessageItem
                key={msg.id || msg._file}
                msg={msg}
                expanded={expandedId === (msg.id || msg._file)}
                onToggle={() => toggle(msg.id || msg._file)}
              />
            ))}
            {sortedBroadcasts.length === 0 && (
              <EmptyState icon="&" message="No broadcasts" detail="Company-wide announcements will appear here" />
            )}
          </div>
        </Card>
      )}

      {tab === 'threads' && (
        <Card title="Threads">
          <div className="max-h-[calc(100vh-200px)] overflow-auto">
            {normalizedThreads.map(msg => (
              <MessageItem
                key={msg.id || msg._file}
                msg={msg}
                expanded={expandedId === (msg.id || msg._file)}
                onToggle={() => toggle(msg.id || msg._file)}
              />
            ))}
            {normalizedThreads.length === 0 && (
              <EmptyState icon=">" message="No active threads" detail="Agent-to-agent conversations will appear here" />
            )}
          </div>
        </Card>
      )}

      {tab === 'human' && (
        <Card title="Human Inbox">
          <div className="max-h-[calc(100vh-200px)] overflow-auto">
            {sortedHumanInbox.map(msg => (
              <MessageItem
                key={msg.id || msg._file}
                msg={msg}
                expanded={expandedId === (msg.id || msg._file)}
                onToggle={() => toggle(msg.id || msg._file)}
              />
            ))}
            {sortedHumanInbox.length === 0 && (
              <EmptyState icon="&" message="Inbox empty" detail="Messages to the exec chair will appear here" />
            )}
          </div>
        </Card>
      )}

      {tab === 'inboxes' && (
        <Card title="Agent Inbox Counts">
          <div className="space-y-1">
            {inboxSummary && Object.entries(inboxSummary).map(([id, count]) => {
              const color = agentColor(id)
              return (
                <div key={id} className="flex items-center justify-between py-2.5 px-3 rounded hover:bg-[#334155]/10 transition-colors">
                  <div className="flex items-center gap-2.5">
                    <div className="w-2 h-2 rounded-full" style={{ backgroundColor: color }} />
                    <AgentName id={id} short />
                  </div>
                  <span className={`text-sm font-medium ${count > 0 ? 'text-yellow-400' : 'text-[#475569]'}`}>
                    {count} message{count !== 1 ? 's' : ''}
                  </span>
                </div>
              )
            })}
            {(!inboxSummary || Object.keys(inboxSummary).length === 0) && (
              <EmptyState icon="@" message="No inbox data" />
            )}
          </div>
        </Card>
      )}
    </div>
  )
}
