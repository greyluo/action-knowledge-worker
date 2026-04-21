import { useState, useEffect } from 'react'
import type { AgentSpec } from '../../types'
import { generateAgentSpec, createAgent, updateAgent } from '../../api'

const CAPABILITIES: Record<string, { label: string; tools: string[] }> = {
  web_research: { label: 'Web research', tools: ['WebFetch', 'WebSearch'] },
  file_analysis: { label: 'File analysis', tools: ['Read', 'Write', 'Edit', 'Glob', 'Grep'] },
  shell: { label: 'Shell access', tools: ['Bash'] },
  company_data: { label: 'Company data', tools: ['mcp__demo__fetch_company_data', 'mcp__demo__fetch_email_thread'] },
}

function toolsToCapabilities(allowedTools: string[]): string[] {
  const toolSet = new Set(allowedTools)
  return Object.entries(CAPABILITIES)
    .filter(([, { tools }]) => tools.some((t) => toolSet.has(t)))
    .map(([slug]) => slug)
}

type Mode = 'create' | 'preview' | 'edit'

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
  expanded: boolean
  collapsed: boolean
  onExpand: () => void
  onCollapse: () => void
  style?: React.CSSProperties
}

const statusColor = (status: string) => {
  if (status === 'active') return 'var(--color-success)'
  if (status === 'draft') return 'var(--color-warning)'
  return 'var(--color-text-muted)'
}

const statusBg = (status: string) => {
  if (status === 'active') return 'var(--color-success-bg)'
  if (status === 'draft') return 'rgba(251,191,36,0.1)'
  return 'rgba(92,98,130,0.12)'
}

export function BuilderPanel({
  agents,
  selectedId,
  onSelect,
  onUpdate,
  expanded,
  collapsed,
  onExpand,
  onCollapse,
  style,
}: BuilderPanelProps) {
  const [mode, setMode] = useState<Mode>('create')
  const [description, setDescription] = useState('')
  const [draft, setDraft] = useState<Draft>({ name: '', system_prompt: '', capabilities: [] })
  const [isGenerating, setIsGenerating] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hoveredAgent, setHoveredAgent] = useState<string | null>(null)
  const [iconBtnHover, setIconBtnHover] = useState<'expand' | 'collapse' | null>(null)
  const [newAgentHover, setNewAgentHover] = useState(false)

  useEffect(() => {
    const agent = agents.find((a) => a.id === selectedId)
    if (agent) {
      setMode('edit')
      setDraft({
        name: agent.name,
        system_prompt: agent.system_prompt,
        capabilities: toolsToCapabilities(agent.allowed_tools),
      })
      setError(null)
    }
  }, [selectedId, agents])

  const handleNewAgent = () => {
    setMode('create')
    setDescription('')
    setDraft({ name: '', system_prompt: '', capabilities: [] })
    setError(null)
  }

  const handleGenerate = async () => {
    const desc = description.trim()
    if (!desc) return
    setIsGenerating(true)
    setError(null)
    try {
      const spec = await generateAgentSpec(desc)
      setDraft({
        name: spec.name,
        system_prompt: spec.system_prompt,
        capabilities: spec.capabilities,
      })
      setMode('preview')
    } catch (err) {
      setError(String(err))
    } finally {
      setIsGenerating(false)
    }
  }

  const handleSave = async () => {
    setIsSaving(true)
    setError(null)
    try {
      let saved: AgentSpec
      if (mode === 'preview') {
        saved = await createAgent(draft.name, draft.system_prompt, draft.capabilities)
      } else {
        saved = await updateAgent(selectedId, {
          name: draft.name,
          system_prompt: draft.system_prompt,
          capabilities: draft.capabilities,
        })
      }
      onUpdate(saved)
    } catch (err) {
      setError(String(err))
    } finally {
      setIsSaving(false)
    }
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
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        background: 'var(--color-surface)',
        borderBottom: '1px solid var(--color-border)',
        overflow: 'hidden',
        fontFamily: 'var(--font-sans)',
        minHeight: 0,
        ...style,
      }}
    >
      {/* Header */}
      <div
        style={{
          height: '44px',
          minHeight: '44px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 12px',
          borderBottom: '1px solid var(--color-border)',
          flexShrink: 0,
        }}
      >
        <span
          style={{
            fontSize: '12px',
            fontWeight: 600,
            letterSpacing: '0.05em',
            color: 'var(--color-text-muted)',
            textTransform: 'uppercase',
          }}
        >
          Builder
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          {(['expand', 'collapse'] as const).map((action) => (
            <button
              key={action}
              onClick={action === 'expand' ? onExpand : onCollapse}
              title={action === 'expand' ? 'Expand' : 'Collapse'}
              onMouseEnter={() => setIconBtnHover(action)}
              onMouseLeave={() => setIconBtnHover(null)}
              style={{
                width: '24px',
                height: '24px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'transparent',
                border: 'none',
                borderRadius: 'var(--radius-sm)',
                color: iconBtnHover === action ? 'var(--color-text)' : 'var(--color-text-muted)',
                cursor: 'pointer',
                fontSize: '13px',
                lineHeight: 1,
                transition: 'color 100ms ease',
                padding: 0,
              }}
            >
              {action === 'expand' ? '⌃' : '⌄'}
            </button>
          ))}
        </div>
      </div>

      {/* Body */}
      {!collapsed && (
        <div
          style={{
            display: 'flex',
            flex: '1 1 auto',
            overflow: 'hidden',
            minHeight: 0,
          }}
        >
          {/* Left column — agent list */}
          <div
            style={{
              width: '160px',
              minWidth: '160px',
              display: 'flex',
              flexDirection: 'column',
              borderRight: '1px solid var(--color-border)',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                padding: '10px 12px 6px',
                fontSize: '11px',
                fontWeight: 600,
                letterSpacing: '0.06em',
                color: 'var(--color-text-muted)',
                textTransform: 'uppercase',
                flexShrink: 0,
              }}
            >
              Agents
            </div>
            <div style={{ flex: '1 1 auto', overflowY: 'auto', padding: '2px 0' }}>
              {agents.map((agent) => {
                const isSelected = agent.id === selectedId
                const isHovered = hoveredAgent === agent.id
                return (
                  <div
                    key={agent.id}
                    onClick={() => onSelect(agent.id)}
                    onMouseEnter={() => setHoveredAgent(agent.id)}
                    onMouseLeave={() => setHoveredAgent(null)}
                    style={{
                      padding: '6px 12px',
                      cursor: 'pointer',
                      borderLeft: isSelected ? '2px solid var(--color-accent)' : '2px solid transparent',
                      background: isSelected
                        ? 'var(--color-accent-bg)'
                        : isHovered
                        ? 'var(--color-surface-2)'
                        : 'transparent',
                      transition: 'background 100ms ease',
                    }}
                  >
                    <div
                      style={{
                        fontSize: '13px',
                        fontWeight: isSelected ? 500 : 400,
                        color: isSelected ? 'var(--color-accent)' : 'var(--color-text)',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        lineHeight: 1.4,
                      }}
                    >
                      {agent.icon ? `${agent.icon} ` : ''}{agent.name}
                    </div>
                    <div
                      style={{
                        marginTop: '3px',
                        display: 'inline-flex',
                        alignItems: 'center',
                        fontSize: '10px',
                        fontWeight: 500,
                        letterSpacing: '0.03em',
                        padding: '1px 6px',
                        borderRadius: 'var(--radius-sm)',
                        background: statusBg(agent.status),
                        color: statusColor(agent.status),
                      }}
                    >
                      {agent.status}
                    </div>
                  </div>
                )
              })}
            </div>
            <button
              onClick={handleNewAgent}
              onMouseEnter={() => setNewAgentHover(true)}
              onMouseLeave={() => setNewAgentHover(false)}
              style={{
                margin: '6px 8px 8px',
                padding: '6px 12px',
                fontSize: '12px',
                fontFamily: 'var(--font-sans)',
                fontWeight: 500,
                color: newAgentHover ? 'var(--color-accent)' : 'var(--color-text-muted)',
                background: 'transparent',
                border: 'none',
                borderRadius: 'var(--radius-sm)',
                cursor: 'pointer',
                textAlign: 'left',
                transition: 'color 100ms ease',
                flexShrink: 0,
              }}
            >
              + New agent
            </button>
          </div>

          {/* Right column — form */}
          <div
            style={{
              flex: '1 1 auto',
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              minWidth: 0,
            }}
          >
            <div
              style={{
                flex: '1 1 auto',
                overflowY: 'auto',
                padding: '14px 16px',
                display: 'flex',
                flexDirection: 'column',
                gap: '12px',
              }}
            >
              {/* CREATE MODE */}
              {mode === 'create' && (
                <>
                  <label
                    style={{
                      fontSize: '11px',
                      fontWeight: 600,
                      letterSpacing: '0.06em',
                      color: 'var(--color-text-muted)',
                      textTransform: 'uppercase',
                    }}
                  >
                    What should this agent do?
                  </label>
                  <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleGenerate()
                    }}
                    placeholder="e.g. Research companies, track contacts, and summarize findings across sessions"
                    rows={4}
                    style={{
                      background: 'var(--color-surface-2)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 'var(--radius-md)',
                      color: 'var(--color-text)',
                      fontFamily: 'var(--font-sans)',
                      fontSize: '13px',
                      padding: '10px 12px',
                      outline: 'none',
                      resize: 'none',
                      lineHeight: '1.5',
                    }}
                  />
                  {error && (
                    <div style={{ fontSize: '12px', color: 'var(--color-error, #f87171)' }}>
                      {error}
                    </div>
                  )}
                  <button
                    onClick={handleGenerate}
                    disabled={isGenerating || !description.trim()}
                    style={{
                      padding: '8px 16px',
                      background: isGenerating || !description.trim()
                        ? 'var(--color-surface-3)'
                        : 'var(--color-accent)',
                      color: isGenerating || !description.trim()
                        ? 'var(--color-text-muted)'
                        : 'white',
                      fontFamily: 'var(--font-sans)',
                      fontSize: '12px',
                      fontWeight: 600,
                      border: 'none',
                      borderRadius: 'var(--radius-sm)',
                      cursor: isGenerating || !description.trim() ? 'not-allowed' : 'pointer',
                      alignSelf: 'flex-start',
                      letterSpacing: '0.01em',
                    }}
                  >
                    {isGenerating ? 'Generating…' : 'Create agent'}
                  </button>
                </>
              )}

              {/* PREVIEW + EDIT MODE */}
              {(mode === 'preview' || mode === 'edit') && (
                <>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <label style={labelStyle}>Name</label>
                    <input
                      value={draft.name}
                      onChange={(e) => setDraft((p) => ({ ...p, name: e.target.value }))}
                      style={inputStyle}
                    />
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <label style={labelStyle}>System prompt</label>
                    <textarea
                      value={draft.system_prompt}
                      onChange={(e) => setDraft((p) => ({ ...p, system_prompt: e.target.value }))}
                      rows={5}
                      style={{ ...inputStyle, resize: 'none', lineHeight: '1.5' }}
                    />
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <label style={labelStyle}>Capabilities</label>
                    {Object.entries(CAPABILITIES).map(([slug, { label }]) => (
                      <label
                        key={slug}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                          fontSize: '13px',
                          color: 'var(--color-text)',
                          cursor: 'pointer',
                          userSelect: 'none',
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={draft.capabilities.includes(slug)}
                          onChange={() => toggleCapability(slug)}
                          style={{ accentColor: 'var(--color-accent)', width: '14px', height: '14px' }}
                        />
                        {label}
                      </label>
                    ))}
                  </div>

                  {error && (
                    <div style={{ fontSize: '12px', color: 'var(--color-error, #f87171)' }}>
                      {error}
                    </div>
                  )}

                  <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
                    <button
                      onClick={handleSave}
                      disabled={isSaving || !draft.name.trim()}
                      style={{
                        padding: '8px 16px',
                        background: isSaving || !draft.name.trim()
                          ? 'var(--color-surface-3)'
                          : 'var(--color-accent)',
                        color: isSaving || !draft.name.trim()
                          ? 'var(--color-text-muted)'
                          : 'white',
                        fontFamily: 'var(--font-sans)',
                        fontSize: '12px',
                        fontWeight: 600,
                        border: 'none',
                        borderRadius: 'var(--radius-sm)',
                        cursor: isSaving || !draft.name.trim() ? 'not-allowed' : 'pointer',
                        letterSpacing: '0.01em',
                      }}
                    >
                      {isSaving ? 'Saving…' : 'Save'}
                    </button>
                    {mode === 'preview' && (
                      <button
                        onClick={handleNewAgent}
                        style={{
                          padding: '8px 16px',
                          background: 'transparent',
                          color: 'var(--color-text-muted)',
                          fontFamily: 'var(--font-sans)',
                          fontSize: '12px',
                          fontWeight: 500,
                          border: '1px solid var(--color-border)',
                          borderRadius: 'var(--radius-sm)',
                          cursor: 'pointer',
                        }}
                      >
                        Back
                      </button>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

const labelStyle: React.CSSProperties = {
  fontSize: '11px',
  fontWeight: 600,
  letterSpacing: '0.06em',
  color: 'var(--color-text-muted)',
  textTransform: 'uppercase',
}

const inputStyle: React.CSSProperties = {
  background: 'var(--color-surface-2)',
  border: '1px solid var(--color-border)',
  borderRadius: 'var(--radius-md)',
  color: 'var(--color-text)',
  fontFamily: 'var(--font-sans)',
  fontSize: '13px',
  padding: '8px 12px',
  outline: 'none',
}

export default BuilderPanel
