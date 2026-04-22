import { useState, useRef, useEffect, useCallback, type KeyboardEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import type { AgentSpec, Task, Message, Entity, Delegation } from '../../types'
import { getDelegations } from '../../api'

interface SpacePanelProps {
  agent: AgentSpec | undefined
  agents: AgentSpec[]
  tasks: Task[]
  selectedTaskId: string
  messages: Message[]
  entities: Entity[]
  isStreaming?: boolean
  currentRunId?: string
  onTaskSelect: (id: string) => void
  onDeleteTask: (id: string) => void
  onJumpToTask: (agentId: string, taskId: string) => void
  onSend: (text: string) => void
  builderOpen: boolean
  onToggleBuilder: () => void
}

function statusColor(status: string): string {
  switch (status) {
    case 'completed': return 'var(--color-success)'
    case 'in_progress': return 'var(--color-warning)'
    case 'blocked': return 'var(--color-error)'
    case 'abandoned': return 'var(--color-text-dim)'
    default: return 'var(--color-text-dim)'
  }
}

function formatTime(ts: string): string {
  if (!ts) return ''
  if (/^\d{2}:\d{2}/.test(ts)) return ts
  try { return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }
  catch { return ts }
}

// ─── ToolCallRow ──────────────────────────────────────────────────────────────

function ToolCallRow({ toolCall }: { toolCall: { id: string; tool: string; args: Record<string, unknown> } }) {
  const [open, setOpen] = useState(false)
  return (
    <div style={{ marginTop: '5px', borderRadius: 'var(--radius-sm)', background: 'var(--color-surface)', border: '1px solid var(--color-border)', overflow: 'hidden' }}>
      <div onClick={() => setOpen((v) => !v)}
        style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '4px 8px', cursor: 'pointer', userSelect: 'none' }}>
        <span style={{ fontSize: '9px', color: 'var(--color-text-dim)' }}>{open ? '▾' : '▸'}</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--color-warning)' }}>{toolCall.tool.replace(/^mcp__[^_]+__/, '')}</span>
      </div>
      {open && (
        <div style={{ padding: '6px 8px', fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--color-text-muted)', borderTop: '1px solid var(--color-border)', whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: '120px', overflowY: 'auto', lineHeight: 1.7 }}>
          {JSON.stringify(toolCall.args, null, 2)}
        </div>
      )}
    </div>
  )
}

// ─── MessageBubble ────────────────────────────────────────────────────────────

function MessageBubble({ message }: { message: Message }) {
  const isAgent = message.role === 'agent'
  const hasContent = !!message.content?.trim()
  const hasToolCalls = (message.tool_calls?.length ?? 0) > 0
  if (!hasContent && !hasToolCalls) return null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: isAgent ? 'flex-start' : 'flex-end', marginBottom: '16px' }}>
      <div style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', fontWeight: 500, letterSpacing: '0.06em', color: isAgent ? 'var(--color-accent)' : 'var(--color-text-dim)', marginBottom: '5px', textTransform: 'uppercase' }}>
        {isAgent ? 'agent' : 'you'}
      </div>
      <div style={{
        maxWidth: '82%',
        padding: hasContent ? '10px 14px' : '6px 10px',
        background: isAgent ? 'var(--color-surface-2)' : 'var(--color-surface-3)',
        borderRadius: isAgent ? '2px 10px 10px 10px' : '10px 2px 10px 10px',
        borderLeft: isAgent ? '2px solid var(--color-accent)' : 'none',
        fontSize: '13px',
        color: 'var(--color-text)',
        lineHeight: 1.65,
        wordBreak: 'break-word',
        fontFamily: 'var(--font-sans)',
      }}>
        {hasContent && (
          <div className="md-body">
            <ReactMarkdown>{message.content}</ReactMarkdown>
          </div>
        )}
        {hasToolCalls && (
          <div style={{ marginTop: hasContent ? '6px' : 0 }}>
            {message.tool_calls!.map((tc) => <ToolCallRow key={tc.id} toolCall={tc} />)}
          </div>
        )}
      </div>
      {message.timestamp && (
        <div style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--color-text-dim)', marginTop: '4px', alignSelf: isAgent ? 'flex-start' : 'flex-end' }}>
          {formatTime(message.timestamp)}
        </div>
      )}
    </div>
  )
}

// ─── TaskRow ──────────────────────────────────────────────────────────────────

function TaskRow({ task, selected, onSelect, onDelete }: { task: Task; selected: boolean; onSelect: (id: string) => void; onDelete: (id: string) => void }) {
  const [hovered, setHovered] = useState(false)
  const [confirming, setConfirming] = useState(false)
  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => { setHovered(false); setConfirming(false) }}
      style={{
        padding: '8px 14px', cursor: 'pointer', position: 'relative',
        borderLeft: `2px solid ${selected ? 'var(--color-accent)' : 'transparent'}`,
        background: selected ? 'var(--color-accent-bg)' : hovered ? 'var(--color-surface-2)' : 'transparent',
        transition: 'background 100ms ease',
      }}
    >
      <div onClick={() => !confirming && onSelect(task.id)}>
        <div style={{ fontSize: '12px', fontFamily: 'var(--font-sans)', fontWeight: selected ? 500 : 400, color: selected ? 'var(--color-text)' : 'var(--color-text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', lineHeight: 1.3, marginBottom: '4px', paddingRight: '18px' }}>
          {task.title || `Task ${task.id.slice(0, 8)}`}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ width: 5, height: 5, borderRadius: '50%', background: statusColor(task.status), flexShrink: 0 }} />
          <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--color-text-dim)' }}>
            {task.status.replace('_', ' ')}
          </span>
        </div>
        {task.outcome_summary && (
          <div style={{ fontSize: '10px', color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)', marginTop: '3px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', lineHeight: 1.4 }}>
            {task.outcome_summary}
          </div>
        )}
      </div>

      {hovered && task.id && (
        confirming ? (
          <div onClick={(e) => e.stopPropagation()}
            style={{ position: 'absolute', top: '8px', right: '8px', display: 'flex', alignItems: 'center', gap: '4px' }}>
            <span style={{ fontSize: '10px', color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)' }}>Delete?</span>
            <button onClick={() => onDelete(task.id)}
              style={{ fontSize: '10px', fontFamily: 'var(--font-sans)', fontWeight: 600, color: 'var(--color-error)', background: 'none', border: 'none', cursor: 'pointer', padding: '0 2px' }}>
              Yes
            </button>
            <button onClick={() => setConfirming(false)}
              style={{ fontSize: '10px', fontFamily: 'var(--font-sans)', color: 'var(--color-text-dim)', background: 'none', border: 'none', cursor: 'pointer', padding: '0 2px' }}>
              No
            </button>
          </div>
        ) : (
          <button
            onClick={(e) => { e.stopPropagation(); setConfirming(true) }}
            style={{ position: 'absolute', top: '8px', right: '8px', background: 'none', border: 'none', cursor: 'pointer', fontSize: '13px', color: 'var(--color-text-dim)', lineHeight: 1, padding: '0 2px' }}
            onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-error)')}
            onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-text-dim)')}
          >×</button>
        )
      )}
    </div>
  )
}

// ─── SpacePanel ───────────────────────────────────────────────────────────────

const TYPE_DOTS: Record<string, string> = {
  Person: '#60A5FA', Company: '#34D399', Deal: '#FB923C',
  Task: '#A78BFA', Agent: '#F472B6', Run: '#38BDF8',
}

export function SpacePanel({ agent, agents, tasks, selectedTaskId, messages, entities, isStreaming = false, currentRunId, onTaskSelect, onDeleteTask, onJumpToTask, onSend, builderOpen, onToggleBuilder }: SpacePanelProps) {
  const [inputValue, setInputValue] = useState('')
  const [delegations, setDelegations] = useState<Delegation[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const pollRef = useRef<number | null>(null)

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  useEffect(() => {
    if (pollRef.current !== null) { clearInterval(pollRef.current); pollRef.current = null }
    if (!currentRunId) { setDelegations([]); return }
    getDelegations(currentRunId).then(setDelegations).catch(() => {})
    pollRef.current = window.setInterval(() => {
      getDelegations(currentRunId).then(setDelegations).catch(() => {})
    }, 2000)
    return () => { if (pollRef.current !== null) { clearInterval(pollRef.current); pollRef.current = null } }
  }, [currentRunId])

  const handleSend = useCallback(() => {
    const text = inputValue.trim(); if (!text) return
    setInputValue(''); onSend(text)
  }, [inputValue, onSend])

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  const HIDDEN_TYPES = new Set(['Run', 'Agent'])
  const groupedEntities: Record<string, Entity[]> = {}
  for (const entity of entities) {
    const t = entity.type || 'Unknown'
    if (HIDDEN_TYPES.has(t)) continue
    const displayName = entity.name?.trim()
    if (!displayName || displayName === entity.id.slice(0, 8)) continue
    if (!groupedEntities[t]) groupedEntities[t] = []
    groupedEntities[t].push(entity)
  }

  return (
    <div style={{ flex: '1 1 auto', display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
      <style>{`
        .sp-scroll::-webkit-scrollbar { width: 3px; }
        .sp-input { transition: border-color 150ms ease; }
        .sp-input:focus { border-color: var(--color-accent) !important; box-shadow: 0 0 0 3px var(--color-accent-glow) !important; }
        .sp-input::placeholder { color: var(--color-text-dim); }
        .sp-send:hover:not(:disabled) { background: var(--color-accent-hover) !important; }
        .sp-send:disabled { opacity: 0.35; cursor: default; }
        .sp-toggle:hover { background: var(--color-surface-2) !important; color: var(--color-text) !important; }
        @keyframes sp-dot { 0%, 80%, 100% { transform: scale(0.5); opacity: 0.3; } 40% { transform: scale(1); opacity: 1; } }
        @keyframes sp-pulse { 0%, 100% { opacity: 0.5; } 50% { opacity: 1; } }
        .md-body { line-height: 1.65; }
        .md-body p { margin: 0 0 0.6em; }
        .md-body p:last-child { margin-bottom: 0; }
        .md-body ul, .md-body ol { margin: 0.4em 0 0.6em 1.2em; padding: 0; }
        .md-body li { margin-bottom: 0.2em; }
        .md-body code { font-family: var(--font-mono); font-size: 11px; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 3px; padding: 1px 4px; color: var(--color-accent); }
        .md-body pre { margin: 0.5em 0; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--radius-md); padding: 8px 10px; overflow-x: auto; }
        .md-body pre code { background: none; border: none; padding: 0; font-size: 11px; color: var(--color-text-muted); }
        .md-body strong { color: var(--color-text); font-weight: 600; }
        .md-body em { color: var(--color-text-muted); }
        .md-body h1, .md-body h2, .md-body h3 { font-weight: 600; color: var(--color-text); margin: 0.5em 0 0.3em; line-height: 1.3; }
        .md-body h1 { font-size: 15px; } .md-body h2 { font-size: 14px; } .md-body h3 { font-size: 13px; }
        .md-body a { color: var(--color-accent); text-decoration: none; }
        .md-body a:hover { text-decoration: underline; }
        .md-body blockquote { margin: 0.4em 0; padding: 4px 10px; border-left: 2px solid var(--color-border-2); color: var(--color-text-muted); }
      `}</style>

      {/* Header bar */}
      <div style={{ height: '48px', display: 'flex', alignItems: 'center', padding: '0 14px', gap: '10px', borderBottom: '1px solid var(--color-border)', background: 'var(--color-surface)', flexShrink: 0 }}>
        {/* Builder toggle */}
        <button className="sp-toggle" onClick={onToggleBuilder}
          title={builderOpen ? 'Hide builder' : 'Show builder'}
          style={{ width: 28, height: 28, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 'var(--radius-sm)', background: builderOpen ? 'var(--color-accent-bg)' : 'transparent', color: builderOpen ? 'var(--color-accent)' : 'var(--color-text-dim)', border: `1px solid ${builderOpen ? 'var(--color-accent)' : 'transparent'}`, transition: 'all 120ms ease', flexShrink: 0 }}>
          <svg width="13" height="10" viewBox="0 0 13 10" fill="currentColor">
            <rect y="0" width="13" height="1.5" rx="0.75" />
            <rect y="4" width="9" height="1.5" rx="0.75" />
            <rect y="8" width="11" height="1.5" rx="0.75" />
          </svg>
        </button>

        {agent ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, minWidth: 0 }}>
            <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'var(--color-success)', flexShrink: 0, boxShadow: '0 0 8px var(--color-success)' }} />
            <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--color-text)', fontFamily: 'var(--font-sans)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {agent.name}
            </span>
            {isStreaming && (
              <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--color-accent)', animation: 'sp-pulse 1.4s ease-in-out infinite', letterSpacing: '0.05em' }}>
                thinking…
              </span>
            )}
          </div>
        ) : (
          <span style={{ flex: 1, fontSize: '12px', color: 'var(--color-text-dim)', fontFamily: 'var(--font-mono)' }}>no agent selected</span>
        )}

        <span style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--color-text-dim)', letterSpacing: '0.04em', flexShrink: 0 }}>
          {messages.length > 0 ? `${messages.length} msg` : ''}
        </span>
      </div>

      {!agent ? (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-dim)', fontSize: '12px', fontFamily: 'var(--font-mono)' }}>
          select an agent in the builder →
        </div>
      ) : (
        <div style={{ display: 'flex', flex: '1 1 auto', overflow: 'hidden', minHeight: 0 }}>

          {/* Tasks column */}
          <div style={{ width: 172, flexShrink: 0, display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--color-border)', overflow: 'hidden' }}>
            <div style={{ padding: '10px 14px 6px', fontSize: '10px', fontFamily: 'var(--font-mono)', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--color-text-dim)', flexShrink: 0 }}>
              tasks
            </div>
            <div className="sp-scroll" style={{ flex: '1 1 auto', overflowY: 'auto' }}>
              {tasks.map((task) => (
                <TaskRow key={task.id} task={task} selected={task.id === selectedTaskId} onSelect={onTaskSelect} onDelete={onDeleteTask} />
              ))}
              {selectedTaskId === '' && (
                <TaskRow task={{ id: '', title: 'New task', status: 'pending', session_count: 0, spec_id: '', entity_count: 0, outcome_summary: null }} selected onSelect={() => {}} />
              )}
            </div>
            <button onClick={() => onTaskSelect('')}
              style={{ margin: '6px 10px 10px', padding: '5px 10px', fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--color-text-dim)', background: 'transparent', border: '1px dashed var(--color-border)', borderRadius: 'var(--radius-md)', cursor: 'pointer', textAlign: 'left', flexShrink: 0 }}
              onMouseEnter={(e) => { e.currentTarget.style.color = 'var(--color-accent)'; e.currentTarget.style.borderColor = 'var(--color-accent)' }}
              onMouseLeave={(e) => { e.currentTarget.style.color = 'var(--color-text-dim)'; e.currentTarget.style.borderColor = 'var(--color-border)' }}>
              + new task
            </button>
          </div>

          {/* Conversation */}
          <div style={{ flex: '1 1 auto', display: 'flex', flexDirection: 'column', overflow: 'hidden', minWidth: 0 }}>
            <div className="sp-scroll" style={{ flex: '1 1 auto', overflowY: 'auto', padding: '20px 20px 8px' }}>
              {messages.length === 0 && !isStreaming ? (
                <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
                  <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
                    <circle cx="16" cy="16" r="12" stroke="var(--color-border-2)" strokeWidth="1.5" />
                    <circle cx="16" cy="16" r="4" fill="var(--color-accent)" opacity="0.3" />
                    <circle cx="16" cy="16" r="1.5" fill="var(--color-accent)" />
                  </svg>
                  <span style={{ fontSize: '12px', color: 'var(--color-text-dim)', fontFamily: 'var(--font-mono)' }}>
                    {selectedTaskId ? 'send a message to start' : 'describe a new task below'}
                  </span>
                </div>
              ) : (
                <>
                  {messages.map((msg) => <MessageBubble key={msg.id} message={msg} />)}
                  {isStreaming && (
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', marginBottom: '16px' }}>
                      <div style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', letterSpacing: '0.06em', color: 'var(--color-accent)', textTransform: 'uppercase', marginBottom: '5px' }}>agent</div>
                      <div style={{ padding: '10px 14px', background: 'var(--color-surface-2)', borderRadius: '2px 10px 10px 10px', borderLeft: '2px solid var(--color-accent)', display: 'flex', alignItems: 'center', gap: '5px' }}>
                        {[0, 1, 2].map((i) => (
                          <span key={i} style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--color-accent)', display: 'inline-block', animation: `sp-dot 1.2s ease-in-out ${i * 0.2}s infinite` }} />
                        ))}
                      </div>
                    </div>
                  )}
                  <div ref={messagesEndRef} />
                </>
              )}
            </div>

            {/* Delegations */}
            {delegations.length > 0 && (
              <div style={{ padding: '8px 16px 10px', borderTop: '1px solid var(--color-border)', flexShrink: 0 }}>
                <div style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--color-text-dim)', marginBottom: '6px' }}>
                  delegations
                </div>
                {delegations.map(d => {
                  const targetAgent = agents.find((a) => a.id === d.to_agent_spec_id)
                  const agentName = targetAgent?.name ?? 'agent'
                  return (
                    <div key={d.id} style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                      <span style={{
                        fontSize: '9px', fontFamily: 'var(--font-mono)', letterSpacing: '0.04em',
                        padding: '2px 6px', borderRadius: 3, flexShrink: 0,
                        background: d.status === 'completed' ? 'rgba(52,211,153,0.12)' : d.status === 'failed' ? 'rgba(239,68,68,0.12)' : 'rgba(96,165,250,0.12)',
                        color: d.status === 'completed' ? 'var(--color-success)' : d.status === 'failed' ? 'var(--color-error)' : 'var(--color-accent)',
                      }}>
                        {d.status}
                      </span>
                      <span style={{ fontSize: '11px', fontFamily: 'var(--font-sans)', color: 'var(--color-text-muted)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        → {agentName}
                      </span>
                      {d.task_entity_id && (
                        <button
                          onClick={() => onJumpToTask(d.to_agent_spec_id, d.task_entity_id!)}
                          style={{
                            fontSize: '10px', fontFamily: 'var(--font-mono)', fontWeight: 600,
                            color: 'var(--color-accent)', background: 'var(--color-accent-bg)',
                            border: '1px solid var(--color-accent)', borderRadius: 'var(--radius-sm)',
                            padding: '2px 8px', cursor: 'pointer', letterSpacing: '0.02em', flexShrink: 0,
                            transition: 'background 120ms ease, color 120ms ease',
                          }}
                          onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--color-accent)'; e.currentTarget.style.color = '#0B0C16' }}
                          onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--color-accent-bg)'; e.currentTarget.style.color = 'var(--color-accent)' }}
                        >
                          view →
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>
            )}

            {/* Input */}
            <div style={{ padding: '10px 16px 14px', borderTop: '1px solid var(--color-border)', flexShrink: 0, background: 'var(--color-surface)' }}>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <input
                  ref={inputRef}
                  className="sp-input"
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={selectedTaskId ? `Message ${agent.name}…` : `Describe a task for ${agent.name}…`}
                  autoComplete="off" spellCheck={false}
                  style={{ flex: 1, background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', padding: '9px 13px', fontSize: '13px', fontFamily: 'var(--font-sans)', color: 'var(--color-text)', outline: 'none', boxShadow: 'none' }}
                />
                <button className="sp-send" onClick={handleSend} disabled={!inputValue.trim() || isStreaming}
                  style={{ background: 'var(--color-accent)', color: '#0B0C16', border: 'none', borderRadius: 'var(--radius-md)', padding: '9px 18px', fontSize: '12px', fontWeight: 700, fontFamily: 'var(--font-sans)', cursor: 'pointer', flexShrink: 0, letterSpacing: '0.02em', transition: 'background 120ms ease' }}>
                  Send
                </button>
              </div>
            </div>
          </div>

          {/* Entities column */}
          <div style={{ width: 160, flexShrink: 0, display: 'flex', flexDirection: 'column', borderLeft: '1px solid var(--color-border)', overflow: 'hidden' }}>
            <div style={{ padding: '10px 14px 6px', fontSize: '10px', fontFamily: 'var(--font-mono)', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--color-text-dim)', flexShrink: 0 }}>
              entities
            </div>
            <div className="sp-scroll" style={{ flex: '1 1 auto', overflowY: 'auto' }}>
              {entities.length === 0 ? (
                <div style={{ padding: '16px 14px', fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--color-text-dim)', lineHeight: 1.6 }}>
                  entities found during this task will appear here
                </div>
              ) : (
                Object.entries(groupedEntities).sort().map(([type, items], i) => (
                  <div key={type}>
                    <div style={{ padding: '8px 14px 3px', fontSize: '10px', fontFamily: 'var(--font-mono)', letterSpacing: '0.07em', textTransform: 'uppercase', color: 'var(--color-text-dim)', borderTop: i > 0 ? '1px solid var(--color-border)' : 'none', marginTop: i > 0 ? 4 : 0 }}>
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '5px' }}>
                        <span style={{ width: 5, height: 5, borderRadius: '50%', background: TYPE_DOTS[type] ?? 'var(--color-text-dim)', display: 'inline-block' }} />
                        {type}
                      </span>
                    </div>
                    {items.map((entity) => (
                      <div key={entity.id} style={{ padding: '3px 14px' }}>
                        <div style={{ fontSize: '12px', fontFamily: 'var(--font-sans)', color: 'var(--color-text-muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                          onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-text)')}
                          onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-text-muted)')}>
                          {entity.name || entity.id.slice(0, 12)}
                        </div>
                      </div>
                    ))}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default SpacePanel
