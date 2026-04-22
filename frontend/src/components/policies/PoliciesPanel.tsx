import { useState } from 'react'
import type { Policy, EntityType, EdgeType, BlockingCondition } from '../../types'
import { createPolicy, togglePolicy, deletePolicy } from '../../api'

// ─── Shared styles (matching OntologyView conventions) ────────────────────────

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
const inputStyle: React.CSSProperties = {
  fontSize: '11px', fontFamily: 'var(--font-mono)', padding: '4px 7px',
  borderRadius: 'var(--radius-sm)', border: '1px solid var(--color-border)',
  background: 'var(--color-surface-2)', color: 'var(--color-text)',
  outline: 'none', width: '100%', boxSizing: 'border-box',
}
const labelStyle: React.CSSProperties = {
  fontSize: '11px', fontWeight: 600, color: 'var(--color-text-dim)',
  fontFamily: 'var(--font-sans)', marginBottom: '3px', display: 'block',
}

// ─── Policy card ──────────────────────────────────────────────────────────────

function PolicyCard({
  policy,
  onToggle,
  onDelete,
}: {
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
              [{k}: {vals.join(', ')}]
            </span>
          ))}
        </div>
      ))}
    </div>
  )
}

// ─── Add policy form ──────────────────────────────────────────────────────────

const DEFAULT_TEMPLATE =
  '{subject} is assigned to {count} active project(s): {targets}. ' +
  'Termination is blocked until their project assignments are resolved.'

function AddPolicyForm({
  entityTypes,
  edgeTypes,
  onSave,
  onCancel,
}: {
  entityTypes: EntityType[]
  edgeTypes: EdgeType[]
  onSave: (policy: Omit<Policy, 'id' | 'created_at'>) => Promise<void>
  onCancel: () => void
}) {
  const [name, setName] = useState('')
  const [toolPattern, setToolPattern] = useState('')
  const [subjectKey, setSubjectKey] = useState('employee_name')
  const [subjectType, setSubjectType] = useState(entityTypes[0]?.name ?? '')
  const [edgeType, setEdgeType] = useState(edgeTypes[0]?.name ?? '')
  const [targetType, setTargetType] = useState('')
  const [stateKey, setStateKey] = useState('status')
  const [stateValues, setStateValues] = useState('pending, in_progress, active')
  const [messageTemplate, setMessageTemplate] = useState(DEFAULT_TEMPLATE)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const handleSave = async () => {
    if (!name.trim() || !toolPattern.trim() || !subjectKey.trim() || !subjectType || !edgeType) {
      setError('Name, tool pattern, subject key, subject type, and edge type are required.')
      return
    }
    const condition: BlockingCondition = {
      edge_type: edgeType,
      target_type: targetType || null,
      blocking_target_states: stateKey.trim()
        ? { [stateKey.trim()]: stateValues.split(',').map((v) => v.trim()).filter(Boolean) }
        : {},
      message_template: messageTemplate,
    }
    setBusy(true)
    setError('')
    try {
      await onSave({
        name: name.trim(),
        tool_pattern: toolPattern.trim(),
        subject_key: subjectKey.trim(),
        subject_type: subjectType,
        blocking_conditions: [condition],
        enabled: true,
      })
    } catch (e) {
      setError(String(e))
      setBusy(false)
    }
  }

  return (
    <div style={{ padding: '14px', borderTop: '1px solid var(--color-border)', background: 'var(--color-surface)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--color-text)', fontFamily: 'var(--font-sans)' }}>New Policy</span>
        <button onClick={onCancel} style={{ ...btnBase, padding: '2px 6px' }}>Cancel</button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '10px' }}>
        <div style={{ gridColumn: '1 / -1' }}>
          <label style={labelStyle}>Name</label>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Block termination with active projects" style={inputStyle} />
        </div>
        <div style={{ gridColumn: '1 / -1' }}>
          <label style={labelStyle}>Tool pattern (regex)</label>
          <input value={toolPattern} onChange={(e) => setToolPattern(e.target.value)} placeholder="terminate_employee|fire_employee" style={inputStyle} />
        </div>
        <div>
          <label style={labelStyle}>Subject type</label>
          <select value={subjectType} onChange={(e) => setSubjectType(e.target.value)} style={{ ...inputStyle, appearance: 'auto' }}>
            {entityTypes.map((et) => <option key={et.name} value={et.name}>{et.name}</option>)}
          </select>
        </div>
        <div>
          <label style={labelStyle}>Subject key in tool input</label>
          <input value={subjectKey} onChange={(e) => setSubjectKey(e.target.value)} placeholder="employee_name" style={inputStyle} />
        </div>
      </div>

      <div style={{ fontSize: '11px', fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)', marginBottom: '6px' }}>
        Blocking condition
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '8px' }}>
        <div>
          <label style={labelStyle}>Edge type</label>
          <select value={edgeType} onChange={(e) => setEdgeType(e.target.value)} style={{ ...inputStyle, appearance: 'auto' }}>
            {edgeTypes.map((et) => <option key={et.name} value={et.name}>{et.name}</option>)}
          </select>
        </div>
        <div>
          <label style={labelStyle}>Target type (optional)</label>
          <select value={targetType} onChange={(e) => setTargetType(e.target.value)} style={{ ...inputStyle, appearance: 'auto' }}>
            <option value="">— any —</option>
            {entityTypes.map((et) => <option key={et.name} value={et.name}>{et.name}</option>)}
          </select>
        </div>
        <div>
          <label style={labelStyle}>Blocking state property</label>
          <input value={stateKey} onChange={(e) => setStateKey(e.target.value)} placeholder="status" style={inputStyle} />
        </div>
        <div>
          <label style={labelStyle}>Blocking values (comma-separated)</label>
          <input value={stateValues} onChange={(e) => setStateValues(e.target.value)} placeholder="pending, in_progress" style={inputStyle} />
        </div>
        <div style={{ gridColumn: '1 / -1' }}>
          <label style={labelStyle}>Message template</label>
          <input value={messageTemplate} onChange={(e) => setMessageTemplate(e.target.value)} style={inputStyle} />
          <div style={{ fontSize: '10px', color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)', marginTop: '2px' }}>
            Placeholders: {'{'} subject {'}'} {'{'} count {'}'} {'{'} targets {'}'}
          </div>
        </div>
      </div>

      {error && <div style={{ fontSize: '11px', color: '#EF4444', marginBottom: '8px', fontFamily: 'var(--font-sans)' }}>{error}</div>}

      <button onClick={handleSave} disabled={busy} style={{ ...btnPrimary, width: '100%' }}>
        {busy ? 'Creating…' : 'Create Policy'}
      </button>
    </div>
  )
}

// ─── PoliciesPanel ────────────────────────────────────────────────────────────

export interface PoliciesPanelProps {
  policies: Policy[]
  entityTypes: EntityType[]
  edgeTypes: EdgeType[]
  onRefresh: () => void
}

export function PoliciesPanel({ policies, entityTypes, edgeTypes, onRefresh }: PoliciesPanelProps) {
  const [isAdding, setIsAdding] = useState(false)
  const [error, setError] = useState('')

  const handleToggle = async (id: string, enabled: boolean) => {
    setError('')
    try {
      await togglePolicy(id, enabled)
      onRefresh()
    } catch (e) {
      setError(String(e))
    }
  }

  const handleDelete = async (id: string) => {
    setError('')
    try {
      await deletePolicy(id)
      onRefresh()
    } catch (e) {
      setError(String(e))
    }
  }

  const handleCreate = async (data: Omit<Policy, 'id' | 'created_at'>) => {
    await createPolicy({
      name: data.name,
      tool_pattern: data.tool_pattern,
      subject_key: data.subject_key,
      subject_type: data.subject_type,
      blocking_conditions: data.blocking_conditions,
    })
    setIsAdding(false)
    onRefresh()
  }

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
            No policies yet — add one to enforce graph-based constraints before tool execution.
          </div>
        )}

        {policies.map((p) => (
          <PolicyCard key={p.id} policy={p} onToggle={handleToggle} onDelete={handleDelete} />
        ))}
      </div>

      {/* Add form pinned to bottom */}
      {isAdding && (
        <AddPolicyForm
          entityTypes={entityTypes}
          edgeTypes={edgeTypes}
          onSave={handleCreate}
          onCancel={() => setIsAdding(false)}
        />
      )}
    </div>
  )
}

export default PoliciesPanel
