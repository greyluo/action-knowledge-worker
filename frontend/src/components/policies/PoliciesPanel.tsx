import { useState } from 'react'
import type { Policy, EntityType, EdgeType, BlockingCondition, ToolDef } from '../../types'
import { createPolicy, togglePolicy, deletePolicy, generatePolicy } from '../../api'

// ─── Shared styles ────────────────────────────────────────────────────────────

const btnBase: React.CSSProperties = {
  fontSize: '11px', fontFamily: 'var(--font-sans)', fontWeight: 600,
  padding: '3px 8px', borderRadius: 'var(--radius-sm)', cursor: 'pointer',
  border: '1px solid var(--color-border)', background: 'var(--color-surface-2)',
  color: 'var(--color-text-muted)', lineHeight: 1.5,
}
const btnDanger: React.CSSProperties = {
  ...btnBase, color: '#EF4444', borderColor: '#FCA5A5', background: '#FFF5F5',
}
const btnPrimary: React.CSSProperties = {
  ...btnBase, color: 'var(--color-accent)', borderColor: 'var(--color-accent)',
  background: 'color-mix(in srgb, var(--color-accent) 8%, transparent)',
}

// ─── Policy card ──────────────────────────────────────────────────────────────

function PolicyCard({ policy, onToggle, onDelete }: {
  policy: Policy
  onToggle: (id: string, enabled: boolean) => void
  onDelete: (id: string) => void
}) {
  const [confirmDelete, setConfirmDelete] = useState(false)

  return (
    <div style={{
      padding: '10px 12px', borderRadius: 'var(--radius-md)',
      background: 'var(--color-surface-2)', border: '1px solid var(--color-border)',
      marginBottom: '8px', opacity: policy.enabled ? 1 : 0.55,
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '8px', marginBottom: '6px' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--color-text)', fontFamily: 'var(--font-sans)', marginBottom: '2px' }}>
            {policy.name}
          </div>
          <code style={{ fontSize: '10px', color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)', background: 'var(--color-surface)', padding: '1px 4px', borderRadius: '3px', display: 'inline-block', maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {policy.tool_pattern}
          </code>
        </div>
        <div style={{ display: 'flex', gap: '4px', flexShrink: 0 }}>
          <button
            onClick={() => onToggle(policy.id, !policy.enabled)}
            style={{ ...btnBase, color: policy.enabled ? 'var(--color-accent)' : 'var(--color-text-dim)', borderColor: policy.enabled ? 'var(--color-accent)' : 'var(--color-border)' }}
          >
            {policy.enabled ? 'on' : 'off'}
          </button>
          {!confirmDelete
            ? <button onClick={() => setConfirmDelete(true)} style={btnDanger}>×</button>
            : (
              <div style={{ display: 'flex', gap: '3px', alignItems: 'center' }}>
                <button onClick={() => onDelete(policy.id)} style={{ ...btnDanger, padding: '2px 6px' }}>yes</button>
                <button onClick={() => setConfirmDelete(false)} style={{ ...btnBase, padding: '2px 6px' }}>no</button>
              </div>
            )
          }
        </div>
      </div>

      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '6px' }}>
        <span style={{ fontSize: '10px', padding: '1px 5px', borderRadius: '8px', background: '#EFF6FF', color: '#3B82F6', border: '1px solid #BFDBFE', fontFamily: 'var(--font-sans)', fontWeight: 600 }}>
          {policy.subject_type}
        </span>
        <span style={{ fontSize: '10px', color: 'var(--color-text-dim)', fontFamily: 'var(--font-mono)', alignSelf: 'center' }}>
          key: {policy.subject_key}
        </span>
      </div>

      {policy.blocking_conditions.map((cond, i) => (
        <div key={i} style={{ fontSize: '11px', fontFamily: 'var(--font-sans)', color: 'var(--color-text-muted)', background: 'var(--color-surface)', borderRadius: 'var(--radius-sm)', padding: '5px 8px', borderLeft: '2px solid #F97316' }}>
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-text)', fontWeight: 600 }}>{cond.edge_type}</span>
          {cond.target_type && <span> → <span style={{ fontFamily: 'var(--font-mono)', color: '#22C55E' }}>{cond.target_type}</span></span>}
          {Object.entries(cond.blocking_target_states).map(([k, vals]) => (
            <span key={k} style={{ marginLeft: '4px', color: 'var(--color-text-dim)' }}>
              [{k}: {(Array.isArray(vals) ? vals : [vals]).join(', ')}]
            </span>
          ))}
        </div>
      ))}
    </div>
  )
}

// ─── Policy draft preview (read-only card) ────────────────────────────────────

interface PolicyDraft {
  name: string
  tool_pattern: string
  subject_key: string
  subject_type: string
  subject_source: string
  blocking_conditions: BlockingCondition[]
}

function DraftPreview({ draft }: { draft: PolicyDraft }) {
  return (
    <div style={{
      padding: '10px 12px', borderRadius: 'var(--radius-md)',
      background: 'var(--color-surface-2)',
      border: '1px solid var(--color-accent)',
      marginBottom: '10px',
    }}>
      <div style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', letterSpacing: '0.07em', textTransform: 'uppercase', color: 'var(--color-accent)', marginBottom: '8px' }}>
        generated preview
      </div>
      <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--color-text)', fontFamily: 'var(--font-sans)', marginBottom: '4px' }}>
        {draft.name}
      </div>
      <code style={{ fontSize: '10px', color: 'var(--color-text-muted)', fontFamily: 'var(--font-mono)', background: 'var(--color-surface)', padding: '1px 4px', borderRadius: '3px', display: 'inline-block', marginBottom: '8px' }}>
        {draft.tool_pattern}
      </code>

      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '8px' }}>
        <span style={{ fontSize: '10px', padding: '1px 5px', borderRadius: '8px', background: draft.subject_source === 'actor' ? '#F0FDF4' : '#EFF6FF', color: draft.subject_source === 'actor' ? '#15803D' : '#3B82F6', border: `1px solid ${draft.subject_source === 'actor' ? '#BBF7D0' : '#BFDBFE'}`, fontFamily: 'var(--font-sans)', fontWeight: 600 }}>
          {draft.subject_source === 'actor' ? 'actor' : draft.subject_type || 'tool_input'}
        </span>
        {draft.subject_source !== 'actor' && (
          <span style={{ fontSize: '10px', color: 'var(--color-text-dim)', fontFamily: 'var(--font-mono)', alignSelf: 'center' }}>
            key: {draft.subject_key}
          </span>
        )}
      </div>

      {draft.blocking_conditions.map((cond, i) => (
        <div key={i} style={{ fontSize: '11px', fontFamily: 'var(--font-sans)', color: 'var(--color-text-muted)', background: 'var(--color-surface)', borderRadius: 'var(--radius-sm)', padding: '5px 8px', borderLeft: `2px solid ${cond.invert ? '#8B5CF6' : '#F97316'}`, marginBottom: '4px' }}>
          <span style={{ fontSize: '10px', color: cond.invert ? '#8B5CF6' : '#F97316', fontFamily: 'var(--font-mono)', marginRight: '4px' }}>
            {cond.invert ? 'block if absent' : 'block if present'}
          </span>
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-text)', fontWeight: 600 }}>{cond.edge_type}</span>
          {cond.target_type && <span> → <span style={{ fontFamily: 'var(--font-mono)', color: '#22C55E' }}>{cond.target_type}</span></span>}
          {Object.entries(cond.blocking_target_states).map(([k, vals]) => (
            <span key={k} style={{ marginLeft: '4px', color: 'var(--color-text-dim)' }}>
              [{k}: {(Array.isArray(vals) ? vals : [vals]).join(', ')}]
            </span>
          ))}
          {cond.message_template && (
            <div style={{ fontSize: '10px', color: 'var(--color-text-dim)', marginTop: '4px', fontStyle: 'italic' }}>
              {cond.message_template}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ─── AI-driven generation flow ────────────────────────────────────────────────

type GenMode = 'describe' | 'generating' | 'preview'

function GeneratePolicyFlow({ onSave, onCancel }: {
  onSave: (draft: PolicyDraft) => Promise<void>
  onCancel: () => void
}) {
  const [mode, setMode] = useState<GenMode>('describe')
  const [description, setDescription] = useState('')
  const [draft, setDraft] = useState<PolicyDraft | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState('')

  const handleGenerate = async () => {
    if (!description.trim()) return
    setMode('generating')
    setError('')
    try {
      const result = await generatePolicy(description.trim())
      setDraft(result as PolicyDraft)
      setMode('preview')
    } catch (e) {
      setError(String(e))
      setMode('describe')
    }
  }

  const handleCreate = async () => {
    if (!draft) return
    setIsSaving(true)
    setError('')
    try {
      await onSave(draft)
    } catch (e) {
      setError(String(e))
      setIsSaving(false)
    }
  }

  return (
    <div style={{ padding: '14px', borderTop: '1px solid var(--color-border)', background: 'var(--color-surface)' }}>
      <style>{`@keyframes pp-spin { to { transform: rotate(360deg); } }`}</style>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--color-text)', fontFamily: 'var(--font-sans)' }}>New Policy</span>
        <button onClick={onCancel} style={{ ...btnBase, padding: '2px 6px' }}>Cancel</button>
      </div>

      {(mode === 'describe' || mode === 'generating') && (
        <>
          <div style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', letterSpacing: '0.07em', textTransform: 'uppercase', color: 'var(--color-text-dim)', marginBottom: '6px' }}>
            describe the policy
          </div>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleGenerate() }}
            disabled={mode === 'generating'}
            placeholder="e.g. Block terminating employees who are assigned to active projects"
            rows={4}
            style={{
              fontSize: '12px', fontFamily: 'var(--font-sans)', padding: '8px 10px',
              borderRadius: 'var(--radius-md)', border: '1px solid var(--color-border)',
              background: 'var(--color-surface-2)', color: 'var(--color-text)',
              outline: 'none', width: '100%', boxSizing: 'border-box',
              resize: 'none', lineHeight: '1.55', marginBottom: '10px',
              opacity: mode === 'generating' ? 0.6 : 1,
            }}
          />
          {error && (
            <div style={{ fontSize: '11px', color: '#EF4444', marginBottom: '8px', fontFamily: 'var(--font-sans)' }}>
              {error}
            </div>
          )}
          <button
            onClick={handleGenerate}
            disabled={mode === 'generating' || !description.trim()}
            style={{
              ...btnPrimary, width: '100%', padding: '8px',
              fontSize: '12px', fontWeight: 700,
              opacity: (mode === 'generating' || !description.trim()) ? 0.45 : 1,
              cursor: (mode === 'generating' || !description.trim()) ? 'default' : 'pointer',
            }}
          >
            {mode === 'generating' ? (
              <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', border: '1.5px solid var(--color-accent)', borderTopColor: 'transparent', display: 'inline-block', animation: 'pp-spin 0.7s linear infinite' }} />
                Generating…
              </span>
            ) : 'Generate policy'}
          </button>
        </>
      )}

      {mode === 'preview' && draft && (
        <>
          <DraftPreview draft={draft} />
          {error && (
            <div style={{ fontSize: '11px', color: '#EF4444', marginBottom: '8px', fontFamily: 'var(--font-sans)' }}>
              {error}
            </div>
          )}
          <div style={{ display: 'flex', gap: '6px' }}>
            <button
              onClick={handleCreate}
              disabled={isSaving}
              style={{
                ...btnPrimary, flex: 1, padding: '7px',
                fontSize: '12px', fontWeight: 700,
                opacity: isSaving ? 0.45 : 1,
                cursor: isSaving ? 'default' : 'pointer',
              }}
            >
              {isSaving ? 'Creating…' : 'Create Policy'}
            </button>
            <button
              onClick={() => { setMode('describe'); setError('') }}
              style={{ ...btnBase, padding: '7px 12px' }}
            >
              Back
            </button>
          </div>
        </>
      )}
    </div>
  )
}

// ─── PoliciesPanel ────────────────────────────────────────────────────────────

export interface PoliciesPanelProps {
  policies: Policy[]
  entityTypes: EntityType[]
  edgeTypes: EdgeType[]
  tools: ToolDef[]
  onRefresh: () => void
}

export function PoliciesPanel({ policies, entityTypes, edgeTypes, tools, onRefresh }: PoliciesPanelProps) {
  const [isAdding, setIsAdding] = useState(false)
  const [error, setError] = useState('')

  const handleToggle = async (id: string, enabled: boolean) => {
    setError('')
    try { await togglePolicy(id, enabled); onRefresh() } catch (e) { setError(String(e)) }
  }

  const handleDelete = async (id: string) => {
    setError('')
    try { await deletePolicy(id); onRefresh() } catch (e) { setError(String(e)) }
  }

  const handleCreate = async (draft: PolicyDraft) => {
    await createPolicy({
      name: draft.name,
      tool_pattern: draft.tool_pattern,
      subject_key: draft.subject_key,
      subject_type: draft.subject_type,
      subject_source: draft.subject_source,
      blocking_conditions: draft.blocking_conditions,
    })
    setIsAdding(false)
    onRefresh()
  }

  // Suppress unused-prop warnings — these are passed through for future use
  void entityTypes; void edgeTypes; void tools

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--color-bg)', fontFamily: 'var(--font-sans)' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', height: '44px', padding: '0 16px', flexShrink: 0, borderBottom: '1px solid var(--color-border)', background: 'var(--color-surface)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--color-text)' }}>Policies</span>
          <span style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>
            <span style={{ color: 'var(--color-accent)', fontWeight: 700 }}>{policies.filter((p) => p.enabled).length}</span>/{policies.length} active
          </span>
        </div>
        {!isAdding && (
          <button onClick={() => setIsAdding(true)} style={{ ...btnPrimary, padding: '4px 10px' }}>
            + Policy
          </button>
        )}
      </div>

      {/* Body */}
      <div style={{ flex: '1 1 auto', overflowY: 'auto', padding: '14px 16px' }}>
        {error && (
          <div style={{ fontSize: '11px', color: '#EF4444', marginBottom: '10px', padding: '6px 10px', background: '#FFF5F5', borderRadius: 'var(--radius-sm)', border: '1px solid #FCA5A5' }}>
            {error}
          </div>
        )}
        {policies.length === 0 && !isAdding && (
          <div style={{ textAlign: 'center', color: 'var(--color-text-dim)', fontSize: '13px', marginTop: '40px' }}>
            No policies yet — describe one and let AI generate it.
          </div>
        )}
        {policies.map((p) => (
          <PolicyCard key={p.id} policy={p} onToggle={handleToggle} onDelete={handleDelete} />
        ))}
      </div>

      {isAdding && (
        <GeneratePolicyFlow
          onSave={handleCreate}
          onCancel={() => setIsAdding(false)}
        />
      )}
    </div>
  )
}

export default PoliciesPanel
