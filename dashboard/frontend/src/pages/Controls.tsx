import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useSchedule, useBudget, useAutonomy } from '../api/hooks'
import Card from '../components/Card'
import AgentName from '../components/AgentName'
import Loading from '../components/Loading'

function Toggle({ on, onToggle, disabled }: { on: boolean; onToggle: () => void; disabled?: boolean }) {
  return (
    <button
      onClick={onToggle}
      disabled={disabled}
      className={`relative w-10 h-5 rounded-full transition-colors ${on ? 'bg-[#38bdf8]' : 'bg-[#334155]'} ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
    >
      <span
        className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${on ? 'translate-x-5' : ''}`}
      />
    </button>
  )
}

function budgetBarColor(pct: number, tripped: boolean): string {
  if (tripped) return '#f87171'
  if (pct >= 85) return '#f87171'
  if (pct >= 60) return '#fbbf24'
  return '#38bdf8'
}

function EditableCap({ label, value, field }: { label: string; value: number; field: string }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')

  const save = async () => {
    const num = parseFloat(draft)
    if (isNaN(num) || num <= 0) { setEditing(false); return }
    await fetch('/api/budget', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [field]: num }),
    })
    queryClient.invalidateQueries({ queryKey: ['budget'] })
    setEditing(false)
  }

  return (
    <div className="bg-[#0f172a] border border-[#334155] rounded-lg p-3 text-center">
      <div className="text-[10px] text-[#64748b] uppercase tracking-wider mb-1">{label}</div>
      {editing ? (
        <input
          autoFocus
          type="number"
          step="0.01"
          className="w-20 bg-[#1e293b] border border-[#38bdf8] rounded px-2 py-1 text-center text-lg font-bold text-[#f1f5f9] outline-none"
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onBlur={save}
          onKeyDown={e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') setEditing(false) }}
        />
      ) : (
        <div
          className="text-lg font-bold text-[#f1f5f9] cursor-pointer hover:text-[#38bdf8] transition-colors"
          onClick={() => { setDraft(value.toString()); setEditing(true) }}
        >
          ${value.toFixed(2)}
        </div>
      )}
    </div>
  )
}

const SCHEDULE_TYPES = ['cycles', 'standing_orders', 'drives', 'dreams'] as const

const SCHEDULE_DESCRIPTIONS: Record<string, string> = {
  cycles: 'Check tasks, read messages, act',
  standing_orders: 'Health scans, weekly reflections',
  drives: 'Consult strategy, find opportunities',
  dreams: 'Consolidate memory, prune old context',
}

export default function Controls() {
  const queryClient = useQueryClient()
  const { data: schedule, isLoading: schedLoading } = useSchedule()
  const { data: budget, isLoading: budgetLoading } = useBudget()
  const { data: autonomyData } = useAutonomy()
  const [triggerAgent, setTriggerAgent] = useState('')
  const [triggerMode, setTriggerMode] = useState('cycle')
  const [triggering, setTriggering] = useState(false)
  const [triggerResult, setTriggerResult] = useState<{ status: string; output?: string } | null>(null)

  if (schedLoading || budgetLoading) return <Loading />

  const toggleSchedule = async (type?: string) => {
    const config = schedule?.config as Record<string, unknown> | undefined
    const currentEnabled = type
      ? (config?.[type] as { enabled?: boolean })?.enabled ?? true
      : (config?.enabled as boolean | undefined) ?? true
    await fetch('/api/schedule/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: type || null, enabled: !currentEnabled }),
    })
    queryClient.invalidateQueries({ queryKey: ['schedule'] })
  }

  const triggerRun = async () => {
    if (!triggerAgent) return
    setTriggering(true)
    setTriggerResult(null)
    try {
      const res = await fetch('/api/schedule/trigger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: triggerAgent, mode: triggerMode }),
      })
      setTriggerResult(await res.json())
    } catch {
      setTriggerResult({ status: 'error', output: 'Request failed' })
    }
    setTriggering(false)
    queryClient.invalidateQueries({ queryKey: ['schedule'] })
  }

  const config = (schedule?.config || {}) as Record<string, unknown>
  const masterEnabled = (config.enabled as boolean | undefined) ?? true
  const state = (schedule?.state || {}) as Record<string, unknown>

  return (
    <div className="space-y-5">
      <h2 className="text-xl font-semibold">Controls</h2>

      {/* === Budget Section === */}
      <Card title="Budget">
        {budget ? (
          <div className="space-y-4">
            {budget.daily.tripped && (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3 text-red-400 text-sm font-medium">
                CIRCUIT BREAKER TRIPPED — all agent activity paused
              </div>
            )}

            {/* Daily progress bar */}
            <div>
              <div className="flex justify-between text-sm mb-1">
                <span className="text-[#94a3b8]">Daily spend</span>
                <span className="text-[#f1f5f9]">
                  ${budget.daily.spent.toFixed(2)} / ${budget.daily.cap.toFixed(2)}
                  <span className="text-[#64748b] ml-2">${budget.daily.remaining.toFixed(2)} remaining</span>
                </span>
              </div>
              <div className="w-full h-3 bg-[#0f172a] rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${Math.min(budget.daily.pct, 100)}%`,
                    backgroundColor: budgetBarColor(budget.daily.pct, budget.daily.tripped),
                  }}
                />
              </div>
            </div>

            {/* Cap cards */}
            <div className="grid grid-cols-3 gap-3">
              <EditableCap label="Daily Cap" value={budget.daily.cap} field="daily_cap" />
              <EditableCap label="Weekly Cap" value={budget.weekly_cap} field="weekly_cap" />
              <EditableCap label="Monthly Cap" value={budget.monthly_cap} field="monthly_cap" />
            </div>

            {/* Per-agent table */}
            <div>
              <div className="text-xs text-[#64748b] uppercase tracking-wider mb-2">Per Agent</div>
              <div className="bg-[#0f172a] rounded-lg border border-[#334155] overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#334155] text-[10px] text-[#64748b] uppercase">
                      <th className="px-3 py-2 text-left">Agent</th>
                      <th className="px-3 py-2 text-right">Spent</th>
                      <th className="px-3 py-2 text-right">Cap</th>
                      <th className="px-3 py-2 text-center">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(budget.per_agent).map(([id, info]) => (
                      <tr key={id} className="border-b border-[#334155]/30 last:border-0">
                        <td className="px-3 py-2"><AgentName id={id} short /></td>
                        <td className="px-3 py-2 text-right text-[#f1f5f9]">${info.spent.toFixed(2)}</td>
                        <td className="px-3 py-2 text-right text-[#64748b]">${info.cap.toFixed(2)}</td>
                        <td className="px-3 py-2 text-center">
                          <span className={`text-[10px] px-1.5 py-0.5 rounded ${info.within ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
                            {info.within ? 'within' : 'over'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Per-invocation caps */}
            <div>
              <div className="text-xs text-[#64748b] uppercase tracking-wider mb-2">Per Invocation Caps</div>
              <div className="flex gap-3">
                {Object.entries(budget.per_invocation).map(([type, cap]) => (
                  <div key={type} className="bg-[#0f172a] border border-[#334155] rounded px-3 py-1.5 text-xs">
                    <span className="text-[#64748b]">{type}:</span>{' '}
                    <span className="text-[#f1f5f9]">${cap.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className="text-sm text-[#475569] italic py-4 text-center">No budget data available</div>
        )}
      </Card>

      {/* === Autonomy Section === */}
      <Card title="Autonomy">
        <div className="space-y-3">
          <p className="text-sm text-[#94a3b8]">
            Controls how agents handle self-generated work. Affects what happens when an agent identifies something that needs doing.
          </p>

          {autonomyData && (
            <>
              <div className="text-xs text-[#64748b]">
                Default level: <span className="text-[#f1f5f9] capitalize">{autonomyData.default_level}</span>
              </div>

              <div className="bg-[#0f172a] rounded-lg border border-[#334155] overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-[#334155] text-[10px] text-[#64748b] uppercase">
                      <th className="px-3 py-2 text-left">Agent</th>
                      <th className="px-3 py-2 text-center">Level</th>
                      <th className="px-3 py-2 text-left">Behavior</th>
                    </tr>
                  </thead>
                  <tbody>
                    {['agent-000-steward', 'agent-001-maker', 'agent-003-operator', 'agent-005-grower', 'agent-006-strategist'].map(id => {
                      const level = autonomyData.agents[id] || autonomyData.default_level
                      const levelInfo: Record<string, { color: string; desc: string }> = {
                        low: { color: '#38bdf8', desc: 'Execute assigned tasks only \u2014 no self-initiated work' },
                        medium: { color: '#fbbf24', desc: 'Can propose tasks, but they go to backlog for human review' },
                        high: { color: '#4ade80', desc: 'Full autonomy \u2014 agents create and execute their own tasks' },
                      }
                      const info = levelInfo[level] || levelInfo.medium
                      return (
                        <tr key={id} className="border-b border-[#334155]/30 last:border-0">
                          <td className="px-3 py-2"><AgentName id={id} short /></td>
                          <td className="px-3 py-2 text-center">
                            <select
                              value={level}
                              onChange={async (e) => {
                                await fetch(`/api/autonomy/${id}`, {
                                  method: 'PATCH',
                                  headers: { 'Content-Type': 'application/json' },
                                  body: JSON.stringify({ level: e.target.value }),
                                })
                                queryClient.invalidateQueries({ queryKey: ['autonomy'] })
                              }}
                              className="bg-[#1e293b] border border-[#334155] text-sm rounded px-2 py-1 outline-none"
                              style={{ color: info.color }}
                            >
                              <option value="low" style={{ color: '#38bdf8' }}>Low</option>
                              <option value="medium" style={{ color: '#fbbf24' }}>Medium</option>
                              <option value="high" style={{ color: '#4ade80' }}>High</option>
                            </select>
                          </td>
                          <td className="px-3 py-2 text-xs text-[#94a3b8]">{info.desc}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {!autonomyData && (
            <div className="text-sm text-[#475569] italic py-4 text-center">Loading autonomy data...</div>
          )}
        </div>
      </Card>

      {/* === Schedule Section === */}
      <Card title="Schedule">
        <div className="space-y-4">
          {/* Master toggle */}
          <div className="flex items-center justify-between bg-[#0f172a] border border-[#334155] rounded-lg px-4 py-3">
            <div className="flex items-center gap-3">
              <span className={`w-2 h-2 rounded-full ${masterEnabled ? 'bg-green-400' : 'bg-red-400'}`} />
              <span className="text-sm font-medium text-[#f1f5f9]">Scheduler</span>
              <span className="text-xs text-[#64748b]">{masterEnabled ? 'Running' : 'Paused'}</span>
            </div>
            <Toggle on={masterEnabled} onToggle={() => toggleSchedule()} />
          </div>

          {/* Type cards */}
          <div className="grid grid-cols-4 gap-3">
            {SCHEDULE_TYPES.map(type => {
              const typeConfig = config[type] as { enabled?: boolean; interval?: string; time?: string } | undefined
              const enabled = typeConfig?.enabled ?? true
              const lastRun = state[`last_${type}`] as string | undefined
              return (
                <div key={type} className="bg-[#0f172a] border border-[#334155] rounded-lg p-3">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm font-medium text-[#f1f5f9] capitalize">{type.replace('_', ' ')}</span>
                    <Toggle on={enabled} onToggle={() => toggleSchedule(type)} />
                  </div>
                  <div className="text-[10px] text-[#475569] mb-1.5">{SCHEDULE_DESCRIPTIONS[type]}</div>
                  {typeConfig?.interval && (
                    <div className="text-[10px] text-[#64748b]">Every {typeConfig.interval}</div>
                  )}
                  {typeConfig?.time && (
                    <div className="text-[10px] text-[#64748b]">At {typeConfig.time}</div>
                  )}
                  {lastRun && (
                    <div className="text-[10px] text-[#475569] mt-1">Last: {new Date(lastRun).toLocaleTimeString()}</div>
                  )}
                </div>
              )
            })}
          </div>

          {/* Operating hours */}
          {config.operating_hours != null && (
            <div className="text-xs text-[#64748b]">
              Operating hours: {(config.operating_hours as { start?: string })?.start || '00:00'} – {(config.operating_hours as { end?: string })?.end || '23:59'}
            </div>
          )}

          {/* Manual trigger */}
          <div className="bg-[#0f172a] border border-[#334155] rounded-lg p-3">
            <div className="text-xs text-[#64748b] uppercase tracking-wider mb-2">Manual Trigger</div>
            <div className="flex gap-2 items-center">
              <select
                value={triggerAgent}
                onChange={e => setTriggerAgent(e.target.value)}
                className="bg-[#1e293b] border border-[#334155] text-sm rounded px-2 py-1.5 text-[#f1f5f9] outline-none"
              >
                <option value="">Select agent...</option>
                <option value="agent-000-steward">Steward</option>
                <option value="agent-001-maker">Maker</option>
                <option value="agent-003-operator">Operator</option>
                <option value="agent-005-grower">Grower</option>
                <option value="agent-006-strategist">Strategist</option>
              </select>
              <select
                value={triggerMode}
                onChange={e => setTriggerMode(e.target.value)}
                className="bg-[#1e293b] border border-[#334155] text-sm rounded px-2 py-1.5 text-[#f1f5f9] outline-none"
              >
                <option value="cycle">Cycle</option>
                <option value="drives">Drives</option>
                <option value="standing_orders">Standing Orders</option>
                <option value="dream">Dream</option>
              </select>
              <button
                onClick={triggerRun}
                disabled={!triggerAgent || triggering}
                className="bg-[#38bdf8] hover:bg-[#0ea5e9] disabled:opacity-50 disabled:cursor-not-allowed text-[#0f172a] text-sm font-medium px-4 py-1.5 rounded transition-colors"
              >
                {triggering ? 'Running...' : 'Trigger'}
              </button>
            </div>
            {triggerResult && (
              <div className={`mt-2 text-xs p-2 rounded ${triggerResult.status === 'ok' ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'}`}>
                {triggerResult.status === 'ok' ? 'Completed successfully' : `Error: ${triggerResult.output || triggerResult.status}`}
              </div>
            )}
          </div>
        </div>
      </Card>

    </div>
  )
}
