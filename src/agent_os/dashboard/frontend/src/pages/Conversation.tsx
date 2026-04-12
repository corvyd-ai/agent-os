import { useState, useRef, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import AgentName, { agentColor } from '../components/AgentName'
import Markdown from '../components/Markdown'
import {
  useConversations,
  useConversation,
  useAgentAvailability,
  streamConversation,
  type StreamEvent,
  type ConversationSummary,
} from '../api/hooks'

const AGENTS = [
  { id: 'agent-000-steward', label: 'The Steward' },
  { id: 'agent-001-maker', label: 'The Maker' },
  { id: 'agent-003-operator', label: 'The Operator' },
  { id: 'agent-005-grower', label: 'The Grower' },
  { id: 'agent-006-strategist', label: 'The Strategist' },
]

interface DisplayMessage {
  role: 'human' | 'assistant'
  content: string
  tools?: { name: string; preview: string }[]
  cost_usd?: number
  duration_ms?: number
  num_turns?: number
}

export default function Conversation() {
  const [searchParams, setSearchParams] = useSearchParams()
  const agentParam = searchParams.get('agent') || AGENTS[0].id
  const convParam = searchParams.get('conv')

  const [selectedAgent, setSelectedAgent] = useState(agentParam)
  const [conversationId, setConversationId] = useState<string | null>(convParam)
  const [messages, setMessages] = useState<DisplayMessage[]>([])
  const [inputText, setInputText] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [totalCost, setTotalCost] = useState(0)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const { data: availability } = useAgentAvailability(selectedAgent)
  const { data: conversations, refetch: refetchConversations } = useConversations()
  const { data: loadedConv } = useConversation(convParam)

  // Load conversation from URL param
  useEffect(() => {
    if (loadedConv && loadedConv.turns?.length) {
      const displayMsgs: DisplayMessage[] = loadedConv.turns.map(t => ({
        role: t.role,
        content: t.content,
      }))
      setMessages(displayMsgs)
      setConversationId(loadedConv.id)
      setSelectedAgent(loadedConv.agent_id)
      setTotalCost(loadedConv.total_cost_usd || 0)
    }
  }, [loadedConv])

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Update URL params
  useEffect(() => {
    const params: Record<string, string> = { agent: selectedAgent }
    if (conversationId) params.conv = conversationId
    setSearchParams(params, { replace: true })
  }, [selectedAgent, conversationId, setSearchParams])

  const handleSend = useCallback(() => {
    const text = inputText.trim()
    if (!text || isStreaming) return

    setInputText('')
    setIsStreaming(true)

    // Add human message
    const humanMsg: DisplayMessage = { role: 'human', content: text }
    setMessages(prev => [...prev, humanMsg])

    // Add placeholder assistant message
    const assistantIdx = messages.length + 1
    setMessages(prev => [...prev, { role: 'assistant', content: '', tools: [] }])

    const currentTools: { name: string; preview: string }[] = []

    const controller = streamConversation(
      selectedAgent,
      text,
      conversationId,
      (event: StreamEvent) => {
        switch (event.type) {
          case 'text':
            setMessages(prev => {
              const updated = [...prev]
              const msg = updated[assistantIdx]
              if (msg) {
                updated[assistantIdx] = { ...msg, content: msg.content + event.text }
              }
              return updated
            })
            break

          case 'tool_use':
            currentTools.push({ name: event.name, preview: event.input_preview })
            setMessages(prev => {
              const updated = [...prev]
              const msg = updated[assistantIdx]
              if (msg) {
                updated[assistantIdx] = { ...msg, tools: [...currentTools] }
              }
              return updated
            })
            break

          case 'complete':
            setMessages(prev => {
              const updated = [...prev]
              const msg = updated[assistantIdx]
              if (msg) {
                updated[assistantIdx] = {
                  ...msg,
                  cost_usd: event.cost_usd,
                  duration_ms: event.duration_ms,
                  num_turns: event.num_turns,
                }
              }
              return updated
            })
            setTotalCost(prev => prev + event.cost_usd)
            break

          case 'conversation_saved':
            setConversationId(event.conversation_id)
            refetchConversations()
            break

          case 'error':
            setMessages(prev => {
              const updated = [...prev]
              const msg = updated[assistantIdx]
              if (msg) {
                updated[assistantIdx] = {
                  ...msg,
                  content: msg.content || `Error: ${event.message}`,
                }
              }
              return updated
            })
            break
        }
      },
      () => {
        setIsStreaming(false)
        abortRef.current = null
      },
      (error) => {
        setIsStreaming(false)
        abortRef.current = null
        setMessages(prev => {
          const updated = [...prev]
          const msg = updated[assistantIdx]
          if (msg) {
            updated[assistantIdx] = { ...msg, content: `Connection error: ${error}` }
          }
          return updated
        })
      },
    )

    abortRef.current = controller
  }, [inputText, isStreaming, selectedAgent, conversationId, messages.length, refetchConversations])

  const handleCancel = () => {
    if (abortRef.current) {
      abortRef.current.abort()
      setIsStreaming(false)
      abortRef.current = null
    }
  }

  const handleNewConversation = () => {
    setConversationId(null)
    setMessages([])
    setTotalCost(0)
    setSearchParams({ agent: selectedAgent }, { replace: true })
    textareaRef.current?.focus()
  }

  const handleLoadConversation = (conv: ConversationSummary) => {
    setSearchParams({ agent: conv.agent_id, conv: conv.id }, { replace: true })
    setShowHistory(false)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const isAvailable = availability?.available !== false

  return (
    <div className="flex flex-col h-full -m-6">
      {/* Header */}
      <div className="flex items-center gap-4 px-6 py-3 border-b border-[#334155] bg-[#1e293b]/50">
        <select
          value={selectedAgent}
          onChange={e => {
            setSelectedAgent(e.target.value)
            handleNewConversation()
          }}
          disabled={isStreaming}
          className="bg-[#0f172a] border border-[#334155] rounded px-3 py-1.5 text-sm text-[#f1f5f9] outline-none focus:border-[#38bdf8]"
        >
          {AGENTS.map(a => (
            <option key={a.id} value={a.id}>{a.label}</option>
          ))}
        </select>

        {/* Availability indicator */}
        <div className="flex items-center gap-1.5">
          <div className={`w-2 h-2 rounded-full ${isAvailable ? 'bg-green-400' : 'bg-yellow-400 animate-pulse'}`} />
          <span className="text-xs text-[#64748b]">
            {isAvailable ? 'Available' : 'Busy'}
          </span>
        </div>

        <div className="flex-1" />

        {totalCost > 0 && (
          <span className="text-xs text-[#64748b] font-mono">
            ${totalCost.toFixed(4)}
          </span>
        )}

        <button
          onClick={() => { setShowHistory(!showHistory); if (!showHistory) refetchConversations() }}
          className={`text-xs px-3 py-1.5 rounded border transition-colors ${
            showHistory
              ? 'border-[#38bdf8] text-[#38bdf8] bg-[#38bdf8]/10'
              : 'border-[#334155] text-[#94a3b8] hover:text-[#f1f5f9] hover:border-[#475569]'
          }`}
        >
          History
        </button>

        <button
          onClick={handleNewConversation}
          disabled={isStreaming}
          className="text-xs px-3 py-1.5 rounded border border-[#334155] text-[#94a3b8] hover:text-[#f1f5f9] hover:border-[#475569] disabled:opacity-50 transition-colors"
        >
          New
        </button>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* History panel */}
        {showHistory && (
          <div className="w-72 border-r border-[#334155] overflow-y-auto p-3 space-y-2 shrink-0">
            <h3 className="text-xs font-medium text-[#64748b] uppercase tracking-wider mb-3">
              Recent Conversations
            </h3>
            {conversations?.length === 0 && (
              <p className="text-xs text-[#475569]">No conversations yet</p>
            )}
            {conversations?.map(conv => (
              <button
                key={conv.id}
                onClick={() => handleLoadConversation(conv)}
                className={`w-full text-left p-3 rounded border transition-colors ${
                  conv.id === conversationId
                    ? 'border-[#38bdf8] bg-[#38bdf8]/10'
                    : 'border-[#334155] hover:border-[#475569] bg-[#1e293b]'
                }`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <AgentName id={conv.agent_id} short />
                  <span className="text-[10px] text-[#475569] ml-auto">
                    {conv.turn_count / 2 | 0} turns
                  </span>
                </div>
                <p className="text-xs text-[#94a3b8] truncate">{conv.preview || '(empty)'}</p>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-[10px] text-[#475569] font-mono">
                    ${conv.total_cost_usd.toFixed(4)}
                  </span>
                  <span className="text-[10px] text-[#475569]">
                    {new Date(conv.updated).toLocaleDateString()}
                  </span>
                </div>
              </button>
            ))}
          </div>
        )}

        {/* Messages area */}
        <div className="flex-1 flex flex-col overflow-hidden">
          <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
            {messages.length === 0 && (
              <div className="flex items-center justify-center h-full">
                <div className="text-center">
                  <p className="text-[#475569] text-sm mb-1">
                    Start a conversation with <AgentName id={selectedAgent} short />
                  </p>
                  <p className="text-[#334155] text-xs">
                    They have full access to the agent-os filesystem and their own context.
                  </p>
                </div>
              </div>
            )}

            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'human' ? 'justify-end' : 'justify-start'}`}>
                {msg.role === 'human' ? (
                  <div className="max-w-[75%] bg-[#1e3a5f] border border-[#2563eb]/30 rounded-lg px-4 py-3">
                    <p className="text-sm text-[#f1f5f9] whitespace-pre-wrap">{msg.content}</p>
                  </div>
                ) : (
                  <div className="max-w-[85%] w-full">
                    <div
                      className="rounded-lg border px-4 py-3"
                      style={{
                        borderColor: agentColor(selectedAgent) + '30',
                        backgroundColor: '#1e293b',
                      }}
                    >
                      {/* Agent header */}
                      <div className="flex items-center gap-2 mb-2 pb-2 border-b border-[#334155]">
                        <AgentName id={selectedAgent} short />
                        {msg.cost_usd !== undefined && (
                          <span className="text-[10px] text-[#475569] font-mono ml-auto">
                            ${msg.cost_usd.toFixed(4)} / {((msg.duration_ms || 0) / 1000).toFixed(1)}s / {msg.num_turns} turns
                          </span>
                        )}
                      </div>

                      {/* Tool use badges */}
                      {msg.tools && msg.tools.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mb-2">
                          {msg.tools.map((tool, j) => (
                            <span
                              key={j}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] bg-[#0f172a] border border-[#334155] text-[#64748b]"
                              title={tool.preview}
                            >
                              <span className="text-[#38bdf8]">{tool.name}</span>
                              {tool.preview && (
                                <span className="truncate max-w-32">{tool.preview}</span>
                              )}
                            </span>
                          ))}
                        </div>
                      )}

                      {/* Message content */}
                      {msg.content ? (
                        <Markdown>{msg.content}</Markdown>
                      ) : isStreaming && i === messages.length - 1 ? (
                        <div className="flex items-center gap-2 text-[#64748b] text-xs py-1">
                          <div className="w-3 h-3 border-2 border-[#334155] border-t-[#38bdf8] rounded-full animate-spin" />
                          Thinking...
                        </div>
                      ) : null}
                    </div>
                  </div>
                )}
              </div>
            ))}

            <div ref={messagesEndRef} />
          </div>

          {/* Input area */}
          <div className="border-t border-[#334155] px-6 py-3 bg-[#1e293b]/30">
            <div className="flex gap-3 items-end">
              <textarea
                ref={textareaRef}
                value={inputText}
                onChange={e => setInputText(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isStreaming}
                placeholder={
                  isStreaming
                    ? 'Waiting for response...'
                    : isAvailable
                    ? `Message ${AGENTS.find(a => a.id === selectedAgent)?.label || 'agent'}... (Enter to send, Shift+Enter for newline)`
                    : 'Agent is busy...'
                }
                rows={1}
                className="flex-1 bg-[#0f172a] border border-[#334155] rounded-lg px-4 py-2.5 text-sm text-[#f1f5f9] placeholder-[#475569] outline-none focus:border-[#38bdf8] resize-none disabled:opacity-50 min-h-[40px] max-h-[120px]"
                style={{ height: 'auto' }}
                onInput={e => {
                  const el = e.currentTarget
                  el.style.height = 'auto'
                  el.style.height = Math.min(el.scrollHeight, 120) + 'px'
                }}
              />
              {isStreaming ? (
                <button
                  onClick={handleCancel}
                  className="px-4 py-2.5 rounded-lg bg-red-500/20 border border-red-500/40 text-red-400 text-sm hover:bg-red-500/30 transition-colors shrink-0"
                >
                  Cancel
                </button>
              ) : (
                <button
                  onClick={handleSend}
                  disabled={!inputText.trim() || !isAvailable}
                  className="px-4 py-2.5 rounded-lg bg-[#38bdf8]/20 border border-[#38bdf8]/40 text-[#38bdf8] text-sm hover:bg-[#38bdf8]/30 disabled:opacity-30 disabled:cursor-not-allowed transition-colors shrink-0"
                >
                  Send
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
