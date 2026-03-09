import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useTasks, useBacklog, type TaskItem } from '../api/hooks'
import AgentName from '../components/AgentName'
import TimeAgo from '../components/TimeAgo'
import Loading from '../components/Loading'
import Markdown from '../components/Markdown'

const STATUSES = ['backlog', 'queued', 'in-progress', 'in-review', 'done', 'failed', 'declined']

const STATUS_COLORS: Record<string, string> = {
  backlog: 'bg-cyan-500/20 text-cyan-400',
  queued: 'bg-blue-500/20 text-blue-400',
  'in-progress': 'bg-yellow-500/20 text-yellow-400',
  'in-review': 'bg-purple-500/20 text-purple-400',
  done: 'bg-green-500/20 text-green-400',
  failed: 'bg-red-500/20 text-red-400',
  declined: 'bg-orange-500/20 text-orange-400',
}

function BacklogActions({ taskId }: { taskId: string }) {
  const queryClient = useQueryClient()
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState('')

  const promote = async (e: React.MouseEvent) => {
    e.stopPropagation()
    await fetch(`/api/backlog/${taskId}/promote`, { method: 'POST' })
    queryClient.invalidateQueries({ queryKey: ['backlog'] })
    queryClient.invalidateQueries({ queryKey: ['tasks'] })
  }

  const reject = async (e: React.MouseEvent) => {
    e.stopPropagation()
    await fetch(`/api/backlog/${taskId}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    })
    queryClient.invalidateQueries({ queryKey: ['backlog'] })
    setRejecting(false)
  }

  if (rejecting) {
    return (
      <div className="flex gap-1 mt-1" onClick={e => e.stopPropagation()}>
        <input
          autoFocus
          placeholder="Reason..."
          className="flex-1 bg-[#1e293b] border border-[#334155] rounded px-1.5 py-0.5 text-[10px] text-[#f1f5f9] outline-none"
          value={reason}
          onChange={e => setReason(e.target.value)}
          onKeyDown={e => { if (e.key === 'Escape') setRejecting(false) }}
        />
        <button onClick={reject} className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 hover:bg-red-500/30">OK</button>
      </div>
    )
  }

  return (
    <div className="flex gap-1 mt-1">
      <button onClick={promote} className="text-[10px] px-1.5 py-0.5 rounded bg-green-500/20 text-green-400 hover:bg-green-500/30">Promote</button>
      <button onClick={e => { e.stopPropagation(); setRejecting(true) }} className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 hover:bg-red-500/30">Reject</button>
    </div>
  )
}

function TaskCard({ task, onClick }: { task: TaskItem; onClick: () => void }) {
  return (
    <div
      onClick={onClick}
      className="bg-[#0f172a] border border-[#334155] rounded-md p-3 cursor-pointer hover:border-[#475569] transition-colors"
    >
      <div className="text-sm font-medium text-[#f1f5f9] mb-1 line-clamp-2">{task.title}</div>
      <div className="flex items-center justify-between text-xs">
        <AgentName id={task.assigned_to || 'unassigned'} short />
        <span className={`px-1.5 py-0.5 rounded text-[10px] ${STATUS_COLORS[task.status] || ''}`}>
          {task.priority || 'normal'}
        </span>
      </div>
      <div className="text-[10px] text-[#475569] mt-1">
        {task.id} &middot; <TimeAgo timestamp={task.created} />
      </div>
      {task.status === 'backlog' && <BacklogActions taskId={task.id} />}
    </div>
  )
}

const COLUMN_CAP = 10
const CAPPABLE = new Set(['done', 'declined'])

export default function Tasks() {
  const [searchParams, setSearchParams] = useSearchParams()
  const statusFilter = searchParams.get('status') || undefined
  const { data: tasks, isLoading } = useTasks()
  const { data: backlogData } = useBacklog()
  const [selectedTask, setSelectedTask] = useState<TaskItem | null>(null)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  if (isLoading) return <Loading />

  const grouped: Record<string, TaskItem[]> = {}
  for (const s of STATUSES) grouped[s] = []

  // Add backlog items
  for (const item of backlogData?.items || []) {
    grouped['backlog'].push({
      id: item.id,
      title: item.title,
      assigned_to: item.assigned_to,
      created_by: item.created_by,
      priority: item.priority,
      created: item.created_at,
      status: 'backlog',
      body: item.body,
      _file: '',
    })
  }

  for (const task of tasks || []) {
    const s = task.status || 'queued'
    if (grouped[s]) grouped[s].push(task)
  }

  // If filtering, show only that column expanded
  const visibleStatuses = statusFilter ? [statusFilter] : STATUSES

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Task Board</h2>
        <div className="flex gap-1">
          <button
            onClick={() => setSearchParams({})}
            className={`px-2 py-1 text-xs rounded ${!statusFilter ? 'bg-[#334155] text-[#f1f5f9]' : 'text-[#64748b] hover:text-[#94a3b8]'}`}
          >
            All
          </button>
          {STATUSES.map(s => (
            <button
              key={s}
              onClick={() => setSearchParams({ status: s })}
              className={`px-2 py-1 text-xs rounded ${statusFilter === s ? 'bg-[#334155] text-[#f1f5f9]' : 'text-[#64748b] hover:text-[#94a3b8]'}`}
            >
              {s} ({grouped[s]?.length || 0})
            </button>
          ))}
        </div>
      </div>

      <div className="flex gap-3 overflow-x-auto">
        {visibleStatuses.map(status => (
          <div key={status} className={`${statusFilter ? 'flex-1' : 'w-56 shrink-0'}`}>
            <div className="flex items-center gap-2 mb-2 px-1">
              <span className={`w-2 h-2 rounded-full ${STATUS_COLORS[status]?.split(' ')[0] || 'bg-slate-500'}`} />
              <span className="text-xs font-medium text-[#94a3b8] uppercase tracking-wider">{status}</span>
              <span className="text-xs text-[#475569]">{grouped[status]?.length || 0}</span>
            </div>
            <div className="space-y-2 max-h-[calc(100vh-200px)] overflow-auto">
              {(() => {
                const items = grouped[status] || []
                const isCapped = !statusFilter && CAPPABLE.has(status) && !expanded[status]
                const visible = isCapped ? items.slice(0, COLUMN_CAP) : items
                const remaining = items.length - COLUMN_CAP
                return (
                  <>
                    {visible.map(task => (
                      <TaskCard key={task.id || task._file} task={task} onClick={() => setSelectedTask(task)} />
                    ))}
                    {isCapped && remaining > 0 && (
                      <button
                        onClick={() => setExpanded(prev => ({ ...prev, [status]: true }))}
                        className="w-full text-xs text-[#64748b] hover:text-[#94a3b8] py-2 transition-colors"
                      >
                        {remaining} more {status}...
                      </button>
                    )}
                    {!statusFilter && CAPPABLE.has(status) && expanded[status] && items.length > COLUMN_CAP && (
                      <button
                        onClick={() => setExpanded(prev => ({ ...prev, [status]: false }))}
                        className="w-full text-xs text-[#64748b] hover:text-[#94a3b8] py-2 transition-colors"
                      >
                        Show fewer
                      </button>
                    )}
                  </>
                )
              })()}
            </div>
          </div>
        ))}
      </div>

      {/* Task detail modal */}
      {selectedTask && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setSelectedTask(null)}>
          <div className="bg-[#1e293b] border border-[#334155] rounded-lg w-[600px] max-h-[80vh] overflow-auto" onClick={e => e.stopPropagation()}>
            <div className="p-4 border-b border-[#334155] flex items-center justify-between">
              <div>
                <h3 className="text-lg font-medium">{selectedTask.title}</h3>
                <div className="text-xs text-[#64748b] mt-1">
                  {selectedTask.id} &middot; {selectedTask.status} &middot; <AgentName id={selectedTask.assigned_to || 'unassigned'} short />
                </div>
              </div>
              <button onClick={() => setSelectedTask(null)} className="text-[#64748b] hover:text-[#f1f5f9] text-xl">&times;</button>
            </div>
            <div className="p-4">
              <Markdown>{selectedTask.body}</Markdown>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
