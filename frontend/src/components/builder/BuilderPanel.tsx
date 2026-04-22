import { useState, useEffect } from 'react'
import type { AgentSpec } from '../../types'
import { generateAgentSpec, createAgent, updateAgent, deleteAgent } from '../../api'

const CAPABILITIES: Record<string, { label: string; desc: string; tools: string[] }> = {
  web_research: { label: 'Web research', desc: 'Fetch URLs, search the web', tools: ['WebFetch', 'WebSearch'] },
  file_analysis: { label: 'File analysis', desc: 'Read, write, and search files', tools: ['Read', 'Write', 'Edit', 'Glob', 'Grep'] },
  company_data: { label: 'Company data', desc: 'Fetch company & email data', tools: ['mcp__demo__fetch_company_data', 'mcp__demo__fetch_email_thread'] },
}

function toolsToCapabilities(allowedTools: string[]): string[] {
  const toolSet = new Set(allowedTools)
  return Object.entries(CAPABILITIES)
    .filter(([, { tools }]) => tools.some((t) => toolSet.has(t)))
    .map(([slug]) => slug)
}

type Mode = 'create' | 'preview' | 'view' | 'edit'

interface Draft {
  name: string
  system_prompt: string
  capabilities: string[]
}

interface BuilderPanelProps {
  agents: AgentSpec[]
  selectedId: string
  onSelect: (id: string) => void
  onUpdate: (updated: AgentSpec) => void
  onDelete: (id: string) => void
}

const statusDot = (status: string) => {
  if (status === 'active') return 'var(--color-success)'
  if (status === 'draft') return 'var(--color-warning)'
  return 'var(--color-text-dim)'
}

export function BuilderPanel({ agents, selectedId, onSelect, onUpdate, onDelete }: BuilderPanelProps) {
  const [mode, setMode] = useState<Mode>('create')
  const [description, setDescription] = useState('')
  const [draft, setDraft] = useState<Draft>({ name: '', system_prompt: '', capabilities: [] })
  const [isGenerating, setIsGenerating] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hoveredAgent, setHoveredAgent] = useState<string | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null)

  useEffect(() => {
    const agent = agents.find((a) => a.id === selectedId)
    if (agent) {
      setMode('view')
      setDraft({ name: agent.name, system_prompt: agent.system_prompt, capabilities: toolsToCapabilities(agent.allowed_tools) })
      setError(null)
    }
  }, [selectedId, agents])

  const handleNewAgent = () => {
    setMode('create'); setDescription(''); setDraft({ name: '', system_prompt: '', capabilities: [] }); setError(null)
  }

  const handleGenerate = async () => {
    const desc = description.trim(); if (!desc) return
    setIsGenerating(true); setError(null)
    try {
      const spec = await generateAgentSpec(desc)
      setDraft({ name: spec.name, system_prompt: spec.system_prompt, capabilities: spec.capabilities })
      setMode('preview')
    } catch (err) { setError(String(err)) }
    finally { setIsGenerating(false) }
  }

  const handleSave = async () => {
    setIsSaving(true); setError(null)
    try {
      const saved = mode === 'preview'
        ? await createAgent(draft.name, draft.system_prompt, draft.capabilities)
        : await updateAgent(selectedId, { name: draft.name, system_prompt: draft.system_prompt, capabilities: draft.capabilities })
      onUpdate(saved)
      if (mode === 'edit') setMode('view')
    } catch (err) { setError(String(err)) }
    finally { setIsSaving(false) }
  }

  const toggleCapability = (slug: string) => {
    setDraft((prev) => ({
      ...prev,
      capabilities: prev.capabilities.includes(slug)
        ? prev.capabilities.filter((c) => c !== slug)
        : [...prev.capabilities, slug],
    }))
  }

  return (
    <div style={{ width: 264, height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--color-surface)', overflow: 'hidden', flexShrink: 0 }}>
      <style>{`
        .bp-input {
          background: var(--color-surface-2);
          border: 1px solid var(--color-border);
          border-radius: var(--radius-md);
          color: var(--color-text);
          font-family: var(--font-sans);
          font-size: 12px;
          padding: 7px 10px;
          width: 100%;
          outline: none;
          transition: border-color 150ms ease;
        }
        .bp-input:focus { border-color: var(--color-accent); }
        .bp-input::placeholder { color: var(--color-text-dim); }
        .bp-agent-row:hover .bp-agent-name { color: var(--color-text) !important; }
        .bp-cap-row { display: flex; align-items: flex-start; gap: 8px; padding: 6px 0; cursor: pointer; }
        .bp-cap-row:hover .bp-cap-label { color: var(--color-text) !important; }
        .bp-btn-primary {
          width: 100%;
          padding: 8px;
          background: var(--color-accent);
          color: #0B0C16;
          border: none;
          border-radius: var(--radius-md);
          font-family: var(--font-sans);
          font-size: 12px;
          font-weight: 700;
          letter-spacing: 0.02em;
          cursor: pointer;
          transition: background 120ms ease, opacity 120ms ease;
        }
        .bp-btn-primary:hover:not(:disabled) { background: var(--color-accent-hover); }
        .bp-btn-primary:disabled { opacity: 0.35; cursor: default; }
        .bp-btn-ghost {
          padding: 7px 12px;
          background: transparent;
          color: var(--color-text-muted);
          border: 1px solid var(--color-border);
          border-radius: var(--radius-md);
          font-family: var(--font-sans);
          font-size: 12px;
          cursor: pointer;
          transition: border-color 120ms, color 120ms;
        }
        .bp-btn-ghost:hover { color: var(--color-text); border-color: var(--color-border-2); }
      `}</style>

      {/* Header */}
      <div style={{ padding: '14px 16px 10px', flexShrink: 0 }}>
        <div style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', letterSpacing: '0.1em', textTransform: 'uppercase', color: 'var(--color-text-dim)', marginBottom: '12px' }}>
          builder
        </div>
        <div style={{ fontSize: '11px', fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--color-text-muted)', marginBottom: '8px' }}>
          Agents
        </div>

        {/* Agent list */}
        <div style={{ marginBottom: '2px' }}>
          {agents.map((agent) => {
            const isSelected = agent.id === selectedId
            const isHovered = hoveredAgent === agent.id
            const isConfirming = confirmingDelete === agent.id
            return (
              <div key={agent.id} className="bp-agent-row"
                onClick={() => !isConfirming && onSelect(agent.id)}
                onMouseEnter={() => setHoveredAgent(agent.id)}
                onMouseLeave={() => { setHoveredAgent(null); setConfirmingDelete(null) }}
                style={{
                  display: 'flex', alignItems: 'center', gap: '8px',
                  padding: '6px 8px', borderRadius: 'var(--radius-md)', cursor: 'pointer', position: 'relative',
                  background: isSelected ? 'var(--color-accent-bg)' : isHovered ? 'var(--color-surface-2)' : 'transparent',
                  borderLeft: `2px solid ${isSelected ? 'var(--color-accent)' : 'transparent'}`,
                  transition: 'background 100ms ease',
                  marginBottom: '1px',
                }}
              >
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: statusDot(agent.status), flexShrink: 0, boxShadow: isSelected ? `0 0 6px ${statusDot(agent.status)}` : 'none' }} />
                <span className="bp-agent-name" style={{
                  fontSize: '12px', fontFamily: 'var(--font-sans)', fontWeight: isSelected ? 600 : 400,
                  color: isSelected ? 'var(--color-accent)' : 'var(--color-text-muted)',
                  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', flex: 1,
                  transition: 'color 100ms',
                }}>{agent.name}</span>
                {isHovered && (
                  isConfirming ? (
                    <span onClick={(e) => e.stopPropagation()} style={{ display: 'flex', alignItems: 'center', gap: '3px', flexShrink: 0 }}>
                      <span style={{ fontSize: '10px', color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)' }}>Sure?</span>
                      <button onClick={async (e) => { e.stopPropagation(); try { await deleteAgent(agent.id); onDelete(agent.id) } catch (err) { console.error(err) } }}
                        style={{ fontSize: '10px', fontFamily: 'var(--font-sans)', fontWeight: 600, color: 'var(--color-error)', background: 'none', border: 'none', cursor: 'pointer', padding: '0 2px' }}>Yes</button>
                      <button onClick={(e) => { e.stopPropagation(); setConfirmingDelete(null) }}
                        style={{ fontSize: '10px', fontFamily: 'var(--font-sans)', color: 'var(--color-text-dim)', background: 'none', border: 'none', cursor: 'pointer', padding: '0 2px' }}>No</button>
                    </span>
                  ) : (
                    <button onClick={(e) => { e.stopPropagation(); setConfirmingDelete(agent.id) }}
                      style={{ fontSize: '13px', color: 'var(--color-text-dim)', background: 'none', border: 'none', cursor: 'pointer', padding: '0 2px', flexShrink: 0, lineHeight: 1 }}
                      onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-error)')}
                      onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-text-dim)')}>×</button>
                  )
                )}
              </div>
            )
          })}
        </div>

        <button onClick={handleNewAgent}
          style={{ fontSize: '11px', fontFamily: 'var(--font-sans)', color: 'var(--color-text-dim)', background: 'none', border: 'none', cursor: 'pointer', padding: '4px 8px', textAlign: 'left', width: '100%' }}
          onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-accent)')}
          onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-text-dim)')}>
          + new agent
        </button>
      </div>

      <div style={{ height: '1px', background: 'var(--color-border)', flexShrink: 0, margin: '0 0 0 0' }} />

      {/* Form area */}
      <div style={{ flex: '1 1 auto', overflowY: 'auto', padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>

        {mode === 'create' && (
          <>
            <div>
              <div style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--color-text-dim)', marginBottom: '6px' }}>
                describe the agent
              </div>
              <textarea
                className="bp-input"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleGenerate() }}
                placeholder="e.g. Research companies, track contacts, summarize findings across sessions"
                rows={4}
                style={{ resize: 'none', lineHeight: '1.55' }}
              />
            </div>
            {error && <div style={{ fontSize: '11px', color: 'var(--color-error)', fontFamily: 'var(--font-sans)' }}>{error}</div>}
            <button className="bp-btn-primary" onClick={handleGenerate} disabled={isGenerating || !description.trim()}>
              {isGenerating ? (
                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', border: '1.5px solid #0B0C16', borderTopColor: 'transparent', display: 'inline-block', animation: 'bp-spin 0.7s linear infinite' }} />
                  Generating…
                </span>
              ) : 'Generate agent'}
            </button>
            <style>{`@keyframes bp-spin { to { transform: rotate(360deg); } }`}</style>
          </>
        )}

        {mode === 'view' && (
          <>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--color-text-dim)' }}>
                agent
              </div>
              <button className="bp-btn-ghost" style={{ padding: '3px 10px', fontSize: '11px' }}
                onClick={() => setMode('edit')}>
                Edit
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <div style={labelStyle}>Name</div>
              <div style={{ fontSize: '12px', fontFamily: 'var(--font-sans)', color: 'var(--color-text)', fontWeight: 600 }}>{draft.name}</div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <div style={labelStyle}>System prompt</div>
              <div style={{ fontSize: '12px', fontFamily: 'var(--font-sans)', color: 'var(--color-text-muted)', lineHeight: 1.6, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                {draft.system_prompt || <span style={{ color: 'var(--color-text-dim)', fontStyle: 'italic' }}>none</span>}
              </div>
            </div>

            {draft.capabilities.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <div style={labelStyle}>Capabilities</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  {draft.capabilities.map((slug) => {
                    const cap = CAPABILITIES[slug]; if (!cap) return null
                    return (
                      <div key={slug} style={{ fontSize: '12px', fontFamily: 'var(--font-sans)', color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ width: 5, height: 5, borderRadius: '50%', background: 'var(--color-accent)', flexShrink: 0 }} />
                        {cap.label}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </>
        )}

        {(mode === 'preview' || mode === 'edit') && (
          <>
            <div style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--color-text-dim)' }}>
              {mode === 'preview' ? 'review & save' : 'edit agent'}
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={labelStyle}>Name</label>
              <input className="bp-input" value={draft.name} onChange={(e) => setDraft((p) => ({ ...p, name: e.target.value }))} />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={labelStyle}>System prompt</label>
              <textarea className="bp-input" value={draft.system_prompt}
                onChange={(e) => setDraft((p) => ({ ...p, system_prompt: e.target.value }))}
                rows={6} style={{ resize: 'none', lineHeight: '1.55' }} />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={labelStyle}>Capabilities</label>
              {Object.entries(CAPABILITIES).map(([slug, { label, desc }]) => {
                const checked = draft.capabilities.includes(slug)
                return (
                  <label key={slug} className="bp-cap-row" onClick={() => toggleCapability(slug)}>
                    <div style={{
                      width: 14, height: 14, borderRadius: 3, border: `1.5px solid ${checked ? 'var(--color-accent)' : 'var(--color-border-2)'}`,
                      background: checked ? 'var(--color-accent)' : 'transparent', flexShrink: 0, marginTop: 1,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      transition: 'background 120ms, border-color 120ms',
                    }}>
                      {checked && <svg width="8" height="8" viewBox="0 0 8 8"><polyline points="1,4 3,6 7,2" stroke="#0B0C16" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/></svg>}
                    </div>
                    <div>
                      <div className="bp-cap-label" style={{ fontSize: '12px', color: checked ? 'var(--color-text)' : 'var(--color-text-muted)', transition: 'color 120ms' }}>{label}</div>
                      <div style={{ fontSize: '10px', color: 'var(--color-text-dim)', fontFamily: 'var(--font-mono)', marginTop: '1px' }}>{desc}</div>
                    </div>
                  </label>
                )
              })}
            </div>

            {error && <div style={{ fontSize: '11px', color: 'var(--color-error)', fontFamily: 'var(--font-sans)' }}>{error}</div>}

            <div style={{ display: 'flex', gap: '6px' }}>
              <button className="bp-btn-primary" onClick={handleSave} disabled={isSaving || !draft.name.trim()} style={{ flex: 1 }}>
                {isSaving ? 'Saving…' : mode === 'preview' ? 'Save agent' : 'Update'}
              </button>
              <button className="bp-btn-ghost" onClick={() => mode === 'preview' ? handleNewAgent() : setMode('view')}>
                {mode === 'preview' ? 'Back' : 'Cancel'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

const labelStyle: React.CSSProperties = {
  fontSize: '10px',
  fontFamily: 'var(--font-mono)',
  letterSpacing: '0.07em',
  textTransform: 'uppercase',
  color: 'var(--color-text-dim)',
}

export default BuilderPanel
