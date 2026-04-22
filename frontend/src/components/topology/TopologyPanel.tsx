import { useState } from 'react'
import type { AgentSpec, Edge, EdgeType } from '../../types'
import { createEdgeApi, deleteEdge } from '../../api'

const TOPOLOGY_EDGE_TYPES = [
  'delegates_to',
  'next_in_chain',
  'parallel_with',
  'loops_back_to',
  'handles',
  'fallback_to',
]

// ─── Shared styles ────────────────────────────────────────────────────────────

const btnBase: React.CSSProperties = {
  fontSize: '11px', fontFamily: 'var(--font-sans)', fontWeight: 600,
  padding: '3px 8px', borderRadius: 'var(--radius-sm)', cursor: 'pointer',
  border: '1px solid var(--color-border)', background: 'var(--color-surface-2)',
  color: 'var(--color-text-muted)', lineHeight: 1.5,
}

const btnPrimary: React.CSSProperties = {
  ...btnBase,
  color: 'var(--color-accent)', borderColor: 'var(--color-accent)',
  background: 'color-mix(in srgb, var(--color-accent) 8%, transparent)',
}

const btnDanger: React.CSSProperties = {
  ...btnBase, color: '#EF4444', borderColor: '#FCA5A5', background: '#FFF5F5',
}

const selectStyle: React.CSSProperties = {
  fontSize: '11px', fontFamily: 'var(--font-sans)',
  padding: '4px 6px', borderRadius: 'var(--radius-sm)',
  border: '1px solid var(--color-border)',
  background: 'var(--color-surface-2)',
  color: 'var(--color-text)',
  cursor: 'pointer',
}

// ─── Agent card showing outbound topology edges ───────────────────────────────

function AgentCard({
  agent,
  outEdges,
  agentById,
  onDelete,
}: {
  agent: AgentSpec
  outEdges: Edge[]
  agentById: Record<string, AgentSpec>
  onDelete: (edgeId: string) => void
}) {
  return (
    <div style={{
      border: '1px solid var(--color-border)',
      borderRadius: 'var(--radius-md)',
      padding: '10px 12px',
      background: 'var(--color-surface-2)',
      minWidth: 200,
      flex: '1 1 200px',
      maxWidth: 300,
    }}>
      <div style={{
        fontSize: '12px', fontWeight: 700,
        color: 'var(--color-text)', fontFamily: 'var(--font-sans)',
        marginBottom: '8px',
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>
        {agent.icon ? `${agent.icon} ` : ''}{agent.name}
      </div>

      {outEdges.length === 0 ? (
        <div style={{ fontSize: '10px', color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)' }}>
          No topology edges
        </div>
      ) : (
        outEdges.map(edge => {
          const dstAgent = agentById[edge.dst]
          return (
            <div
              key={edge.id}
              style={{
                display: 'flex', alignItems: 'center', gap: '4px',
                fontSize: '11px', marginBottom: '4px',
                fontFamily: 'var(--font-sans)',
              }}
            >
              <span style={{
                color: 'var(--color-accent)', fontFamily: 'var(--font-mono)',
                fontSize: '10px', flexShrink: 0,
              }}>
                {edge.type}
              </span>
              <span style={{ color: 'var(--color-text-dim)', flexShrink: 0 }}>→</span>
              <span style={{
                color: 'var(--color-text)', overflow: 'hidden',
                textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1,
              }}>
                {dstAgent?.name ?? edge.dst.slice(0, 8)}
              </span>
              <button
                onClick={() => onDelete(edge.id)}
                style={{ ...btnDanger, padding: '0 4px', lineHeight: '14px', marginLeft: 'auto', flexShrink: 0 }}
                title="Remove edge"
              >
                ×
              </button>
            </div>
          )
        })
      )}
    </div>
  )
}

// ─── TopologyPanel ────────────────────────────────────────────────────────────

interface Props {
  agents: AgentSpec[]
  edges: Edge[]
  edgeTypes: EdgeType[]
  onEdgesChanged: () => void
}

export function TopologyPanel({ agents, edges, edgeTypes, onEdgesChanged }: Props) {
  const [srcId, setSrcId] = useState('')
  const [dstId, setDstId] = useState('')
  const [edgeType, setEdgeType] = useState('delegates_to')
  const [error, setError] = useState<string | null>(null)
  const [isAdding, setIsAdding] = useState(false)

  // Suppress unused-prop warning — edgeTypes passed for future use (custom types)
  void edgeTypes

  const topologyEdges = edges.filter(e => TOPOLOGY_EDGE_TYPES.includes(e.type))
  const agentById = Object.fromEntries(agents.map(a => [a.id, a]))

  async function handleCreateEdge() {
    if (!srcId || !dstId || srcId === dstId) return
    setError(null)
    setIsAdding(true)
    try {
      await createEdgeApi(srcId, dstId, edgeType)
      setSrcId('')
      setDstId('')
      setEdgeType('delegates_to')
      onEdgesChanged()
    } catch (e) {
      setError(String(e))
    } finally {
      setIsAdding(false)
    }
  }

  async function handleDeleteEdge(edgeId: string) {
    setError(null)
    try {
      await deleteEdge(edgeId)
      onEdgesChanged()
    } catch (e) {
      setError(String(e))
    }
  }

  const canAdd = Boolean(srcId && dstId && srcId !== dstId && !isAdding)

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', height: '100%',
      background: 'var(--color-bg)', fontFamily: 'var(--font-sans)',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        height: '44px', padding: '0 16px', flexShrink: 0,
        borderBottom: '1px solid var(--color-border)',
        background: 'var(--color-surface)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--color-text)' }}>
            Agent Topology
          </span>
          <span style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>
            <span style={{ color: 'var(--color-accent)', fontWeight: 700 }}>{topologyEdges.length}</span> edge{topologyEdges.length !== 1 ? 's' : ''}
          </span>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div style={{
          fontSize: '11px', color: '#EF4444', padding: '6px 16px',
          background: '#FFF5F5', borderBottom: '1px solid #FCA5A5',
          fontFamily: 'var(--font-sans)', flexShrink: 0,
        }}>
          {error}
        </div>
      )}

      {/* Agent cards */}
      <div style={{ flex: '1 1 auto', overflowY: 'auto', padding: '14px 16px' }}>
        {agents.length === 0 ? (
          <div style={{ textAlign: 'center', color: 'var(--color-text-dim)', fontSize: '13px', marginTop: '40px' }}>
            No agents yet — create agents first.
          </div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px' }}>
            {agents.map(agent => {
              const outEdges = topologyEdges.filter(e => e.src === agent.id)
              return (
                <AgentCard
                  key={agent.id}
                  agent={agent}
                  outEdges={outEdges}
                  agentById={agentById}
                  onDelete={handleDeleteEdge}
                />
              )
            })}
          </div>
        )}
      </div>

      {/* Add edge form */}
      <div style={{
        borderTop: '1px solid var(--color-border)',
        background: 'var(--color-surface)',
        padding: '12px 16px',
        flexShrink: 0,
      }}>
        <div style={{
          fontSize: '10px', fontFamily: 'var(--font-mono)',
          letterSpacing: '0.07em', textTransform: 'uppercase',
          color: 'var(--color-text-dim)', marginBottom: '8px',
        }}>
          Add topology edge
        </div>
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
          <select
            value={srcId}
            onChange={e => setSrcId(e.target.value)}
            style={selectStyle}
          >
            <option value=''>From agent…</option>
            {agents.map(a => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>

          <select
            value={edgeType}
            onChange={e => setEdgeType(e.target.value)}
            style={{ ...selectStyle, fontFamily: 'var(--font-mono)', fontSize: '10px' }}
          >
            {TOPOLOGY_EDGE_TYPES.map(et => (
              <option key={et} value={et}>{et}</option>
            ))}
          </select>

          <select
            value={dstId}
            onChange={e => setDstId(e.target.value)}
            style={selectStyle}
          >
            <option value=''>To agent…</option>
            {agents.map(a => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>

          <button
            onClick={handleCreateEdge}
            disabled={!canAdd}
            style={{
              ...btnPrimary,
              padding: '4px 12px',
              fontSize: '12px', fontWeight: 700,
              opacity: canAdd ? 1 : 0.45,
              cursor: canAdd ? 'pointer' : 'default',
            }}
          >
            {isAdding ? 'Adding…' : 'Add edge'}
          </button>
        </div>

        {srcId && dstId && srcId === dstId && (
          <div style={{ fontSize: '11px', color: '#F97316', marginTop: '6px', fontFamily: 'var(--font-sans)' }}>
            Source and destination must differ.
          </div>
        )}
      </div>
    </div>
  )
}

export default TopologyPanel
