import { useMemo, useRef, useState, useEffect, useCallback } from 'react'
import { forceSimulation, forceManyBody, forceLink, forceCollide, forceCenter } from 'd3-force'
import type { SimulationNodeDatum, SimulationLinkDatum } from 'd3-force'
import type { Entity, Edge, EntityType, EdgeType, Run } from '../../types'
import {
  createEntity, updateEntityProps, deleteEntity,
  createEdgeApi, deleteEdge, createEntityType,
} from '../../api'

export interface OntologyViewProps {
  entities: Entity[]
  edges: Edge[]
  runs: Run[]
  entityTypes: EntityType[]
  edgeTypes: EdgeType[]
  onRefresh: () => void
}

// ─── Colors ──────────────────────────────────────────────────────────────────

const TYPE_COLORS: Record<string, { fill: string; stroke: string; text: string }> = {
  Person:   { fill: '#EFF6FF', stroke: '#3B82F6', text: '#1D4ED8' },
  Company:  { fill: '#F0FDF4', stroke: '#22C55E', text: '#15803D' },
  Deal:     { fill: '#FFF7ED', stroke: '#F97316', text: '#C2410C' },
  Task:     { fill: '#F5F3FF', stroke: '#8B5CF6', text: '#6D28D9' },
  Agent:    { fill: '#FFF1F2', stroke: '#F43F5E', text: '#BE123C' },
  Run:      { fill: '#F0F9FF', stroke: '#0EA5E9', text: '#0369A1' },
  Entity:   { fill: '#FAFAFA', stroke: '#A1A1AA', text: '#52525B' },
}

function typeColor(type: string) {
  return TYPE_COLORS[type] ?? { fill: '#F8FAFC', stroke: '#94A3B8', text: '#475569' }
}

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
const inputStyle: React.CSSProperties = {
  fontSize: '11px', fontFamily: 'var(--font-mono)', padding: '3px 6px',
  borderRadius: 'var(--radius-sm)', border: '1px solid var(--color-border)',
  background: 'var(--color-surface-2)', color: 'var(--color-text)',
  outline: 'none', width: '100%', boxSizing: 'border-box',
}

// ─── Force layout ─────────────────────────────────────────────────────────────

const NODE_RADIUS = 28
// Minimum gap between node edges (center distance = NODE_RADIUS * 2 + GAP)
const NODE_GAP = 24

interface NodeState { id: string; x: number; y: number; vx: number; vy: number; name: string; type: string }
type SimNode = NodeState & SimulationNodeDatum
type SimLink = SimulationLinkDatum<SimNode>

function resolveOverlaps(nodes: NodeState[], width: number, height: number): void {
  const minDist = NODE_RADIUS * 2 + NODE_GAP
  const pad = NODE_RADIUS + 8
  for (let iter = 0; iter < 20; iter++) {
    let moved = false
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dx = nodes[j].x - nodes[i].x
        const dy = nodes[j].y - nodes[i].y
        const dist = Math.sqrt(dx * dx + dy * dy) || 0.01
        if (dist < minDist) {
          const push = (minDist - dist) / 2 + 0.5
          const nx = (dx / dist) * push; const ny = (dy / dist) * push
          nodes[i].x = Math.max(pad, Math.min(width - pad, nodes[i].x - nx))
          nodes[i].y = Math.max(pad, Math.min(height - pad, nodes[i].y - ny))
          nodes[j].x = Math.max(pad, Math.min(width - pad, nodes[j].x + nx))
          nodes[j].y = Math.max(pad, Math.min(height - pad, nodes[j].y + ny))
          moved = true
        }
      }
    }
    if (!moved) break
  }
}

function runForce(nodes: NodeState[], edgeList: Array<{ src: string; dst: string }>, width: number, height: number): NodeState[] {
  if (nodes.length === 0) return []

  const simNodes: SimNode[] = nodes.map((n) => ({ ...n }))
  const nodeById = new Map(simNodes.map((n) => [n.id, n]))

  const links: SimLink[] = edgeList
    .filter((e) => nodeById.has(e.src) && nodeById.has(e.dst))
    .map((e) => ({ source: nodeById.get(e.src)! as SimNode, target: nodeById.get(e.dst)! as SimNode }))

  const sim = forceSimulation<SimNode>(simNodes)
    .force('charge', forceManyBody<SimNode>().strength(-800).distanceMin(NODE_RADIUS * 2))
    .force('link', forceLink<SimNode, SimLink>(links).distance(200).strength(0.15))
    .force('collide', forceCollide<SimNode>(NODE_RADIUS + NODE_GAP / 2 + 4).strength(1).iterations(6))
    .force('center', forceCenter<SimNode>(width / 2, height / 2))
    .stop()

  for (let i = 0; i < 500; i++) sim.tick()

  const pad = NODE_RADIUS + 8
  const result: NodeState[] = simNodes.map((n) => ({
    id: n.id, name: n.name, type: n.type,
    x: Math.max(pad, Math.min(width - pad, n.x ?? width / 2)),
    y: Math.max(pad, Math.min(height - pad, n.y ?? height / 2)),
    vx: 0, vy: 0,
  }))

  // Hard guarantee: push apart any still-overlapping nodes
  resolveOverlaps(result, width, height)
  return result
}

// ─── Graph canvas ─────────────────────────────────────────────────────────────

interface GraphCanvasProps {
  entities: Entity[]
  edges: Edge[]
  selectedId: string | null
  searchQuery: string
  width: number
  height: number
  onSelect: (id: string | null) => void
}

function GraphCanvas({ entities, edges, selectedId, searchQuery, width, height, onSelect }: GraphCanvasProps) {
  const [nodes, setNodes] = useState<NodeState[]>([])
  const [dragging, setDragging] = useState<string | null>(null)
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 })
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [scale, setScale] = useState(1)
  const isPanning = useRef(false)
  const panStart = useRef({ x: 0, y: 0 })
  const panOrigin = useRef({ x: 0, y: 0 })
  const svgRef = useRef<SVGSVGElement>(null)

  const entityIds = useMemo(() => new Set(entities.map((e) => e.id)), [entities])
  const visibleEdges = useMemo(() => edges.filter((e) => entityIds.has(e.src) && entityIds.has(e.dst)), [edges, entityIds])

  useEffect(() => {
    if (entities.length === 0) { setNodes([]); return }
    const initial: NodeState[] = entities.map((e) => ({
      id: e.id, x: width * 0.1 + Math.random() * width * 0.8, y: height * 0.1 + Math.random() * height * 0.8,
      vx: 0, vy: 0, name: e.name, type: e.type,
    }))
    setNodes(runForce(initial, visibleEdges.map((e) => ({ src: e.src, dst: e.dst })), width, height))
    setPan({ x: 0, y: 0 }); setScale(1)
  }, [entities, edges, width, height]) // eslint-disable-line react-hooks/exhaustive-deps

  const nodeMap = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])

  const toSvg = useCallback((clientX: number, clientY: number) => {
    const rect = svgRef.current?.getBoundingClientRect()
    if (!rect) return { x: 0, y: 0 }
    return { x: (clientX - rect.left - pan.x) / scale, y: (clientY - rect.top - pan.y) / scale }
  }, [pan, scale])

  const handleNodeMouseDown = useCallback((e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    const node = nodeMap.get(id); if (!node) return
    const pt = toSvg(e.clientX, e.clientY)
    setDragging(id); setDragOffset({ x: pt.x - node.x, y: pt.y - node.y })
  }, [nodeMap, toSvg])

  const handleNodeClick = useCallback((e: React.MouseEvent, id: string) => {
    e.stopPropagation()
    onSelect(selectedId === id ? null : id)
  }, [onSelect, selectedId])

  const handleSvgMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return
    isPanning.current = true
    panStart.current = { x: e.clientX, y: e.clientY }
    panOrigin.current = { ...pan }
  }, [pan])

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (dragging) {
      const pt = toSvg(e.clientX, e.clientY)
      setNodes((prev) => prev.map((n) => n.id === dragging ? { ...n, x: pt.x - dragOffset.x, y: pt.y - dragOffset.y } : n))
    } else if (isPanning.current) {
      setPan({ x: panOrigin.current.x + e.clientX - panStart.current.x, y: panOrigin.current.y + e.clientY - panStart.current.y })
    }
  }, [dragging, dragOffset, toSvg])

  const handleMouseUp = useCallback(() => { setDragging(null); isPanning.current = false }, [])
  const handleSvgClick = useCallback(() => onSelect(null), [onSelect])
  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault()
    setScale((s) => Math.max(0.2, Math.min(3, s * (e.deltaY < 0 ? 1.1 : 0.9))))
  }, [])

  if (entities.length === 0) {
    return (
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-dim)', fontSize: '13px', fontFamily: 'var(--font-sans)' }}>
        No entities match — try adjusting filters
      </div>
    )
  }

  const q = searchQuery.toLowerCase()

  return (
    <svg ref={svgRef} width={width} height={height}
      style={{ cursor: dragging ? 'grabbing' : 'grab', userSelect: 'none', display: 'block' }}
      onMouseDown={handleSvgMouseDown} onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp} onMouseLeave={handleMouseUp}
      onClick={handleSvgClick} onWheel={handleWheel}
    >
      <defs>
        <marker id="arr" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto">
          <path d="M0,0 L0,9 L9,4.5 z" fill="var(--color-border-2)" />
        </marker>
        <marker id="arr-d" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto">
          <path d="M0,0 L0,9 L9,4.5 z" fill="#D97706" opacity="0.8" />
        </marker>
      </defs>

      <g transform={`translate(${pan.x},${pan.y}) scale(${scale})`}>
        {(() => {
          const pairCount = new Map<string, number>()
          const edgeFanIdx = new Map<string, number>()
          for (const edge of visibleEdges) {
            const key = [edge.src, edge.dst].sort().join('|')
            const idx = pairCount.get(key) ?? 0
            edgeFanIdx.set(edge.id, idx)
            pairCount.set(key, idx + 1)
          }

          return visibleEdges.map((edge) => {
            const src = nodeMap.get(edge.src); const dst = nodeMap.get(edge.dst)
            if (!src || !dst) return null
            const r = 28
            const pairKey = [edge.src, edge.dst].sort().join('|')
            const n = pairCount.get(pairKey) ?? 1
            const idx = edgeFanIdx.get(edge.id) ?? 0
            const SPREAD = 38
            const offset = n === 1 ? 18 : (idx - (n - 1) / 2) * SPREAD
            const dx = dst.x - src.x; const dy = dst.y - src.y
            const len = Math.sqrt(dx * dx + dy * dy) || 1
            const mx = (src.x + dst.x) / 2; const my = (src.y + dst.y) / 2
            const cx = mx - (dy / len) * offset; const cy = my + (dx / len) * offset
            const tsd = Math.sqrt((cx - src.x) ** 2 + (cy - src.y) ** 2) || 1
            const sx = src.x + r * (cx - src.x) / tsd; const sy = src.y + r * (cy - src.y) / tsd
            const ted = Math.sqrt((dst.x - cx) ** 2 + (dst.y - cy) ** 2) || 1
            const ex = dst.x - r * (dst.x - cx) / ted; const ey = dst.y - r * (dst.y - cy) / ted
            const lx = 0.25 * sx + 0.5 * cx + 0.25 * ex
            const ly = 0.25 * sy + 0.5 * cy + 0.25 * ey
            const color = edge.derived ? '#D97706' : 'var(--color-border-2)'
            const textColor = edge.derived ? '#D97706' : 'var(--color-text-muted)'
            return (
              <g key={edge.id}>
                <path d={`M${sx},${sy} Q${cx},${cy} ${ex},${ey}`}
                  fill="none" stroke={color} strokeWidth={edge.derived ? 1 : 1.5}
                  strokeDasharray={edge.derived ? '4 3' : undefined}
                  markerEnd={edge.derived ? 'url(#arr-d)' : 'url(#arr)'}
                  opacity={edge.derived ? 0.7 : 1}
                />
                <rect x={lx - 28} y={ly - 9} width={56} height={13} rx={3} fill="var(--color-bg)" opacity={0.85} style={{ pointerEvents: 'none' }} />
                <text x={lx} y={ly} textAnchor="middle" dominantBaseline="middle" fontSize={10} fontFamily="var(--font-sans)" fill={textColor} style={{ pointerEvents: 'none' }}>
                  {edge.type}{edge.derived ? ' ↺' : ''}
                </text>
              </g>
            )
          })
        })()}

        {nodes.map((node) => {
          const colors = typeColor(node.type)
          const isSelected = node.id === selectedId
          const isMatch = q && node.name.toLowerCase().includes(q)
          const isDimmed = q ? !isMatch : false
          const r = 28
          return (
            <g key={node.id} transform={`translate(${node.x},${node.y})`}
              onMouseDown={(e) => handleNodeMouseDown(e, node.id)}
              onClick={(e) => handleNodeClick(e, node.id)}
              style={{ cursor: 'pointer' }} opacity={isDimmed ? 0.25 : 1}
            >
              {isSelected && <circle r={r + 5} fill="none" stroke={colors.stroke} strokeWidth={2} opacity={0.4} />}
              {isMatch && <circle r={r + 6} fill={colors.fill} stroke={colors.stroke} strokeWidth={2} opacity={0.5} />}
              <circle r={r} fill={colors.fill} stroke={colors.stroke} strokeWidth={isSelected ? 2.5 : 1.5} />
              <text y={-r - 6} textAnchor="middle" fontSize={10} fontFamily="var(--font-sans)" fontWeight={600} fill={colors.text} style={{ pointerEvents: 'none' }}>
                {node.type}
              </text>
              <text y={5} textAnchor="middle" fontSize={11} fontFamily="var(--font-sans)" fontWeight={500} fill={colors.text} style={{ pointerEvents: 'none' }}>
                {node.name.length > 16 ? node.name.slice(0, 15) + '…' : node.name}
              </text>
            </g>
          )
        })}
      </g>
    </svg>
  )
}

// ─── Detail panel ─────────────────────────────────────────────────────────────

interface DetailPanelProps {
  entity: Entity
  edgeTypes: EdgeType[]
  edges: Edge[]
  allEntities: Entity[]
  onDelete: (id: string) => Promise<void>
  onUpdate: (id: string, props: Record<string, unknown>) => Promise<void>
  onDeleteEdge: (edgeId: string) => Promise<void>
  onAddEdge: (srcId: string, dstId: string, edgeTypeName: string) => Promise<void>
}

function DetailPanel({ entity, edgeTypes, edges, allEntities, onDelete, onUpdate, onDeleteEdge, onAddEdge }: DetailPanelProps) {
  const colors = typeColor(entity.type)
  const entityMap = useMemo(() => new Map(allEntities.map((e) => [e.id, e])), [allEntities])

  const [isEditing, setIsEditing] = useState(false)
  const [editPairs, setEditPairs] = useState<{ k: string; v: string }[]>([])
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [isAddingEdge, setIsAddingEdge] = useState(false)
  const [newEdgeType, setNewEdgeType] = useState('')
  const [newEdgeDst, setNewEdgeDst] = useState('')
  const [newEdgeDir, setNewEdgeDir] = useState<'out' | 'in'>('out')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  // Reset local state when selected entity changes
  useEffect(() => {
    setIsEditing(false); setConfirmDelete(false); setIsAddingEdge(false); setError('')
  }, [entity.id])

  const connections = useMemo(() => {
    const out = edges.filter((e) => e.src === entity.id).map((e) => ({ dir: 'out' as const, edge: e, peer: entityMap.get(e.dst) }))
    const inc = edges.filter((e) => e.dst === entity.id).map((e) => ({ dir: 'in' as const, edge: e, peer: entityMap.get(e.src) }))
    return [...out, ...inc]
  }, [edges, entity.id, entityMap])

  const storedEdgeTypes = useMemo(() => edgeTypes.filter((et) => !et.is_transitive), [edgeTypes])

  const startEdit = () => {
    setEditPairs(Object.entries(entity.properties).map(([k, v]) => ({ k, v: String(v) })))
    setIsEditing(true)
    setError('')
  }

  const saveEdit = async () => {
    const props: Record<string, unknown> = {}
    for (const { k, v } of editPairs) {
      if (k.trim()) props[k.trim()] = v
    }
    setBusy(true); setError('')
    try {
      await onUpdate(entity.id, props)
      setIsEditing(false)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async () => {
    setBusy(true); setError('')
    try {
      await onDelete(entity.id)
    } catch (e) {
      setError(String(e))
      setBusy(false)
    }
  }

  const handleDeleteEdge = async (edgeId: string) => {
    setError('')
    try { await onDeleteEdge(edgeId) } catch (e) { setError(String(e)) }
  }

  const handleAddEdge = async () => {
    if (!newEdgeType || !newEdgeDst) return
    const [src, dst] = newEdgeDir === 'out' ? [entity.id, newEdgeDst] : [newEdgeDst, entity.id]
    setBusy(true); setError('')
    try {
      await onAddEdge(src, dst, newEdgeType)
      setIsAddingEdge(false); setNewEdgeType(''); setNewEdgeDst('')
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  const otherEntities = useMemo(
    () => allEntities.filter((e) => e.id !== entity.id),
    [allEntities, entity.id],
  )

  if (isEditing) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        <div style={{ padding: '10px 14px 8px', borderBottom: '1px solid var(--color-border)', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--color-text)', fontFamily: 'var(--font-sans)' }}>Edit Properties</span>
          <button onClick={() => setIsEditing(false)} style={{ ...btnBase, padding: '2px 6px' }}>Cancel</button>
        </div>
        <div style={{ flex: '1 1 auto', overflowY: 'auto', padding: '10px 14px' }}>
          {editPairs.map((pair, i) => (
            <div key={i} style={{ display: 'flex', gap: '4px', marginBottom: '5px', alignItems: 'center' }}>
              <input
                value={pair.k} placeholder="key"
                onChange={(e) => setEditPairs((prev) => prev.map((p, j) => j === i ? { ...p, k: e.target.value } : p))}
                style={{ ...inputStyle, width: '80px', flexShrink: 0 }}
              />
              <input
                value={pair.v} placeholder="value"
                onChange={(e) => setEditPairs((prev) => prev.map((p, j) => j === i ? { ...p, v: e.target.value } : p))}
                style={{ ...inputStyle, flex: 1 }}
              />
              <button onClick={() => setEditPairs((prev) => prev.filter((_, j) => j !== i))}
                style={{ ...btnBase, padding: '2px 5px', color: '#EF4444', flexShrink: 0 }}>×</button>
            </div>
          ))}
          <button onClick={() => setEditPairs((prev) => [...prev, { k: '', v: '' }])} style={{ ...btnBase, width: '100%', marginTop: '4px' }}>
            + Add property
          </button>
          {error && <div style={{ fontSize: '11px', color: '#EF4444', marginTop: '6px', fontFamily: 'var(--font-sans)' }}>{error}</div>}
        </div>
        <div style={{ padding: '10px 14px', borderTop: '1px solid var(--color-border)', flexShrink: 0 }}>
          <button onClick={saveEdit} disabled={busy} style={{ ...btnPrimary, width: '100%' }}>
            {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Header */}
      <div style={{ padding: '12px 14px 10px', borderBottom: '1px solid var(--color-border)', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', marginBottom: '4px' }}>
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: colors.stroke, display: 'inline-block', flexShrink: 0, marginTop: 2 }} />
          <span style={{ fontSize: '13px', fontWeight: 600, color: 'var(--color-text)', fontFamily: 'var(--font-sans)', wordBreak: 'break-word', flex: 1 }}>{entity.name}</span>
        </div>
        <div style={{ fontSize: '11px', fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase', color: colors.text, fontFamily: 'var(--font-sans)', marginBottom: '6px' }}>{entity.type}</div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--color-text-dim)', background: 'var(--color-surface-2)', borderRadius: 'var(--radius-sm)', padding: '3px 6px', wordBreak: 'break-all', marginBottom: '8px' }}>
          {entity.id}
        </div>
        <div style={{ display: 'flex', gap: '5px' }}>
          <button onClick={startEdit} style={btnBase}>Edit</button>
          {!confirmDelete
            ? <button onClick={() => setConfirmDelete(true)} style={btnDanger}>Delete</button>
            : (
              <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                <span style={{ fontSize: '11px', color: '#EF4444', fontFamily: 'var(--font-sans)' }}>Sure?</span>
                <button onClick={handleDelete} disabled={busy} style={{ ...btnDanger, padding: '2px 6px' }}>{busy ? '…' : 'Yes'}</button>
                <button onClick={() => setConfirmDelete(false)} style={{ ...btnBase, padding: '2px 6px' }}>No</button>
              </div>
            )
          }
        </div>
        {error && <div style={{ fontSize: '11px', color: '#EF4444', marginTop: '5px', fontFamily: 'var(--font-sans)' }}>{error}</div>}
      </div>

      <div style={{ flex: '1 1 auto', overflowY: 'auto', padding: '10px 14px 16px' }}>
        {/* Properties */}
        {Object.keys(entity.properties).length > 0 && (
          <>
            <div style={{ fontSize: '11px', fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)', marginBottom: '7px' }}>Properties</div>
            {Object.entries(entity.properties).filter(([k]) => k !== 'name' && k !== 'title').map(([k, v]) => (
              <div key={k} style={{ marginBottom: '5px' }}>
                <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--color-text-muted)' }}>{k}: </span>
                <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', color: 'var(--color-text)', wordBreak: 'break-word' }}>{String(v)}</span>
              </div>
            ))}
          </>
        )}

        {/* Relationships */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', margin: '12px 0 7px' }}>
          <div style={{ fontSize: '11px', fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)' }}>
            Relationships ({connections.length})
          </div>
          <button onClick={() => { setIsAddingEdge(true); setNewEdgeType(storedEdgeTypes[0]?.name ?? ''); setNewEdgeDst(''); setNewEdgeDir('out'); setError('') }}
            style={{ ...btnBase, padding: '2px 7px', fontSize: '11px' }}>+ Add</button>
        </div>

        {isAddingEdge && (
          <div style={{ padding: '8px 10px', background: 'var(--color-surface-2)', borderRadius: 'var(--radius-md)', marginBottom: '8px', border: '1px solid var(--color-border)' }}>
            <div style={{ display: 'flex', gap: '4px', marginBottom: '5px' }}>
              {(['out', 'in'] as const).map((d) => (
                <button key={d} onClick={() => setNewEdgeDir(d)}
                  style={{ ...btnBase, padding: '2px 8px', background: newEdgeDir === d ? 'color-mix(in srgb, var(--color-accent) 12%, transparent)' : undefined, color: newEdgeDir === d ? 'var(--color-accent)' : undefined, borderColor: newEdgeDir === d ? 'var(--color-accent)' : undefined }}>
                  {d === 'out' ? 'this →' : '← this'}
                </button>
              ))}
            </div>
            <select value={newEdgeType} onChange={(e) => setNewEdgeType(e.target.value)}
              style={{ ...inputStyle, marginBottom: '5px', appearance: 'auto' }}>
              {storedEdgeTypes.map((et) => <option key={et.name} value={et.name}>{et.name}</option>)}
            </select>
            <select value={newEdgeDst} onChange={(e) => setNewEdgeDst(e.target.value)}
              style={{ ...inputStyle, marginBottom: '7px', appearance: 'auto' }}>
              <option value="">— select entity —</option>
              {otherEntities.map((e) => <option key={e.id} value={e.id}>{e.name} ({e.type})</option>)}
            </select>
            <div style={{ display: 'flex', gap: '5px' }}>
              <button onClick={handleAddEdge} disabled={busy || !newEdgeType || !newEdgeDst} style={{ ...btnPrimary, flex: 1 }}>
                {busy ? 'Saving…' : 'Create edge'}
              </button>
              <button onClick={() => { setIsAddingEdge(false); setError('') }} style={btnBase}>Cancel</button>
            </div>
            {error && <div style={{ fontSize: '11px', color: '#EF4444', marginTop: '5px', fontFamily: 'var(--font-sans)' }}>{error}</div>}
          </div>
        )}

        {connections.map(({ dir, edge, peer }) => (
          <div key={edge.id} style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', marginBottom: '5px', padding: '5px 8px', background: 'var(--color-surface-2)', borderRadius: 'var(--radius-sm)' }}>
            <span style={{ fontSize: '10px', color: 'var(--color-text-dim)', fontFamily: 'var(--font-mono)', flexShrink: 0, marginTop: '2px' }}>{dir === 'out' ? '→' : '←'}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <span style={{ fontSize: '11px', fontFamily: 'var(--font-mono)', fontWeight: 600, color: edge.derived ? 'var(--color-warning)' : 'var(--color-accent)' }}>{edge.type}</span>
              {edge.derived && <span style={{ fontSize: '10px', color: 'var(--color-warning)', opacity: 0.8, marginLeft: '3px' }}>derived</span>}
              {peer ? (
                <div style={{ fontSize: '11px', fontFamily: 'var(--font-sans)', color: 'var(--color-text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {peer.name}<span style={{ fontFamily: 'var(--font-mono)', fontSize: '10px', color: 'var(--color-text-dim)', marginLeft: '3px' }}>{peer.type}</span>
                </div>
              ) : (
                <div style={{ fontSize: '10px', fontFamily: 'var(--font-mono)', color: 'var(--color-text-dim)' }}>{(dir === 'out' ? edge.dst : edge.src).slice(0, 8)}</div>
              )}
            </div>
            {!edge.derived && (
              <button onClick={() => handleDeleteEdge(edge.id)}
                title="Delete this edge"
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-dim)', fontSize: '13px', padding: '0 2px', flexShrink: 0, lineHeight: 1 }}>×</button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Add entity form ──────────────────────────────────────────────────────────

function AddEntityForm({ entityTypes, onSave, onCancel }: {
  entityTypes: EntityType[]
  onSave: (typeName: string, props: Record<string, unknown>) => Promise<void>
  onCancel: () => void
}) {
  const [typeName, setTypeName] = useState(entityTypes[0]?.name ?? '')
  const [pairs, setPairs] = useState<{ k: string; v: string }[]>([{ k: 'name', v: '' }])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const handleSave = async () => {
    const props: Record<string, unknown> = {}
    for (const { k, v } of pairs) {
      if (k.trim()) props[k.trim()] = v
    }
    setBusy(true); setError('')
    try { await onSave(typeName, props) } catch (e) { setError(String(e)); setBusy(false) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: '10px 14px 8px', borderBottom: '1px solid var(--color-border)', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--color-text)', fontFamily: 'var(--font-sans)' }}>New Entity</span>
        <button onClick={onCancel} style={{ ...btnBase, padding: '2px 6px' }}>Cancel</button>
      </div>
      <div style={{ flex: '1 1 auto', overflowY: 'auto', padding: '10px 14px' }}>
        <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)', marginBottom: '4px' }}>Type</div>
        <select value={typeName} onChange={(e) => setTypeName(e.target.value)}
          style={{ ...inputStyle, marginBottom: '12px', appearance: 'auto' }}>
          {entityTypes.map((et) => <option key={et.name} value={et.name}>{et.name}</option>)}
        </select>

        <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)', marginBottom: '4px' }}>Properties</div>
        {pairs.map((pair, i) => (
          <div key={i} style={{ display: 'flex', gap: '4px', marginBottom: '5px', alignItems: 'center' }}>
            <input value={pair.k} placeholder="key"
              onChange={(e) => setPairs((prev) => prev.map((p, j) => j === i ? { ...p, k: e.target.value } : p))}
              style={{ ...inputStyle, width: '80px', flexShrink: 0 }} />
            <input value={pair.v} placeholder="value"
              onChange={(e) => setPairs((prev) => prev.map((p, j) => j === i ? { ...p, v: e.target.value } : p))}
              style={{ ...inputStyle, flex: 1 }} />
            <button onClick={() => setPairs((prev) => prev.filter((_, j) => j !== i))}
              style={{ ...btnBase, padding: '2px 5px', color: '#EF4444', flexShrink: 0 }}>×</button>
          </div>
        ))}
        <button onClick={() => setPairs((prev) => [...prev, { k: '', v: '' }])} style={{ ...btnBase, width: '100%', marginTop: '4px' }}>
          + Add property
        </button>
        {error && <div style={{ fontSize: '11px', color: '#EF4444', marginTop: '6px', fontFamily: 'var(--font-sans)' }}>{error}</div>}
      </div>
      <div style={{ padding: '10px 14px', borderTop: '1px solid var(--color-border)', flexShrink: 0 }}>
        <button onClick={handleSave} disabled={busy} style={{ ...btnPrimary, width: '100%' }}>
          {busy ? 'Creating…' : 'Create Entity'}
        </button>
      </div>
    </div>
  )
}

const EXCLUDED_TYPES = new Set(['Run', 'Task', 'Agent'])

// ─── Schema panel ─────────────────────────────────────────────────────────────

function Tag({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <span style={{ fontSize: '10px', padding: '1px 5px', borderRadius: '8px', background: color + '18', color, border: `1px solid ${color}30`, fontFamily: 'var(--font-sans)', fontWeight: 600 }}>
      {children}
    </span>
  )
}

function SchemaPanel({ entityTypes, edgeTypes, onRefresh }: { entityTypes: EntityType[]; edgeTypes: EdgeType[]; onRefresh: () => void }) {
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [canonicalKey, setCanonicalKey] = useState('')
  const [description, setDescription] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleAdd = async () => {
    if (!name.trim()) return
    setSaving(true); setError(null)
    try {
      await createEntityType(name.trim(), canonicalKey.trim() || undefined, description.trim() || undefined)
      setName(''); setCanonicalKey(''); setDescription(''); setAdding(false)
      onRefresh()
    } catch (e) { setError(String(e)) }
    finally { setSaving(false) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <div style={{ padding: '10px 14px 8px', fontSize: '11px', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', borderBottom: '1px solid var(--color-border)', flexShrink: 0 }}>Schema</div>
      <div style={{ flex: '1 1 auto', overflowY: 'auto', padding: '10px 14px 16px' }}>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
          <div style={{ fontSize: '11px', fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)' }}>Entity Types</div>
          {!adding && (
            <button onClick={() => setAdding(true)} style={{ ...btnBase, padding: '1px 7px', fontSize: '10px' }}>+ add</button>
          )}
        </div>

        {adding && (
          <div style={{ marginBottom: '10px', padding: '8px 10px', background: 'var(--color-surface-2)', borderRadius: 'var(--radius-md)', border: '1px solid var(--color-border)', display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <input style={inputStyle} placeholder="Type name (e.g. Product)" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
            <input style={inputStyle} placeholder="Canonical key (e.g. sku) — optional" value={canonicalKey} onChange={(e) => setCanonicalKey(e.target.value)} />
            <input style={inputStyle} placeholder="Description — optional" value={description} onChange={(e) => setDescription(e.target.value)} />
            {error && <div style={{ fontSize: '10px', color: '#EF4444', fontFamily: 'var(--font-sans)' }}>{error}</div>}
            <div style={{ display: 'flex', gap: '5px' }}>
              <button style={btnPrimary} onClick={handleAdd} disabled={saving || !name.trim()}>{saving ? 'Saving…' : 'Save'}</button>
              <button style={btnBase} onClick={() => { setAdding(false); setError(null) }}>Cancel</button>
            </div>
          </div>
        )}

        {entityTypes.filter((et) => !EXCLUDED_TYPES.has(et.name)).map((et) => {
          const c = typeColor(et.name)
          return (
            <div key={et.name} style={{ marginBottom: '7px', padding: '7px 10px', background: 'var(--color-surface-2)', borderRadius: 'var(--radius-md)', borderLeft: `3px solid ${c.stroke}` }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: et.description ? '3px' : 0 }}>
                <span style={{ fontSize: '12px', fontWeight: 600, fontFamily: 'var(--font-sans)', color: 'var(--color-text)' }}>{et.name}</span>
                {et.canonical_key && (
                  <span style={{ fontSize: '10px', padding: '1px 5px', borderRadius: '8px', background: c.stroke + '18', color: c.text, border: `1px solid ${c.stroke}30`, fontFamily: 'var(--font-sans)', fontWeight: 600 }}>
                    key: {et.canonical_key}
                  </span>
                )}
              </div>
              {et.description && <div style={{ fontSize: '11px', color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)', lineHeight: 1.5 }}>{et.description}</div>}
            </div>
          )
        })}

        <div style={{ fontSize: '11px', fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase', color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)', margin: '14px 0 8px' }}>Edge Types</div>
        {edgeTypes.map((et) => (
          <div key={et.name} style={{ marginBottom: '5px', padding: '6px 10px', background: 'var(--color-surface-2)', borderRadius: 'var(--radius-md)', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '5px' }}>
            <span style={{ fontSize: '12px', fontWeight: 600, fontFamily: 'var(--font-mono)', color: 'var(--color-text)' }}>{et.name}</span>
            {et.is_transitive && <Tag color="#8B5CF6">transitive</Tag>}
            {et.is_inverse_of && <Tag color="#0EA5E9">↔ {et.is_inverse_of}</Tag>}
            {et.domain && <Tag color="#6B7280">{et.domain} →</Tag>}
            {et.range && <Tag color="#6B7280">→ {et.range}</Tag>}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── OntologyView ─────────────────────────────────────────────────────────────

export function OntologyView({ entities, edges, runs: _runs, entityTypes, edgeTypes, onRefresh }: OntologyViewProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [dims, setDims] = useState({ width: 800, height: 500 })
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set())
  const [isAddingEntity, setIsAddingEntity] = useState(false)

  useEffect(() => {
    const el = containerRef.current; if (!el) return
    const obs = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect
      setDims({ width, height })
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  const allTypes = useMemo(() => Array.from(new Set(entities.map((e) => e.type))).filter((t) => !EXCLUDED_TYPES.has(t)).sort(), [entities])
  const filteredEntities = useMemo(() => entities.filter((e) => !EXCLUDED_TYPES.has(e.type) && !hiddenTypes.has(e.type)), [entities, hiddenTypes])
  const selectedEntity = useMemo(() => entities.find((e) => e.id === selectedId) ?? null, [entities, selectedId])

  const toggleType = (type: string) => {
    setHiddenTypes((prev) => { const next = new Set(prev); next.has(type) ? next.delete(type) : next.add(type); return next })
    setSelectedId(null)
  }

  const handleSelect = useCallback((id: string | null) => {
    setSelectedId(id)
    if (id) setIsAddingEntity(false)
  }, [])

  // ─── Mutation handlers ────────────────────────────────────────────────────

  const handleDeleteEntity = useCallback(async (id: string) => {
    await deleteEntity(id)
    setSelectedId(null)
    onRefresh()
  }, [onRefresh])

  const handleUpdateEntity = useCallback(async (id: string, props: Record<string, unknown>) => {
    await updateEntityProps(id, props)
    onRefresh()
  }, [onRefresh])

  const handleDeleteEdge = useCallback(async (edgeId: string) => {
    await deleteEdge(edgeId)
    onRefresh()
  }, [onRefresh])

  const handleAddEdge = useCallback(async (srcId: string, dstId: string, edgeTypeName: string) => {
    await createEdgeApi(srcId, dstId, edgeTypeName)
    onRefresh()
  }, [onRefresh])

  const handleCreateEntity = useCallback(async (typeName: string, props: Record<string, unknown>) => {
    await createEntity(typeName, props)
    setIsAddingEntity(false)
    onRefresh()
  }, [onRefresh])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--color-bg)', overflow: 'hidden', fontFamily: 'var(--font-sans)' }}>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', height: '44px', padding: '0 14px', flexShrink: 0, borderBottom: '1px solid var(--color-border)', background: 'var(--color-surface)' }}>
        <div style={{ position: 'relative', flexShrink: 0 }}>
          <svg style={{ position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} width="12" height="12" viewBox="0 0 12 12" fill="none">
            <circle cx="5" cy="5" r="3.5" stroke="var(--color-text-dim)" strokeWidth="1.2" />
            <line x1="8" y1="8" x2="11" y2="11" stroke="var(--color-text-dim)" strokeWidth="1.2" strokeLinecap="round" />
          </svg>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search entities…"
            style={{ paddingLeft: 26, paddingRight: 8, height: 28, width: 160, fontSize: '12px', fontFamily: 'var(--font-sans)', background: 'var(--color-surface-2)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', color: 'var(--color-text)', outline: 'none' }}
          />
        </div>

        <div style={{ display: 'flex', gap: '5px', flexWrap: 'nowrap', overflow: 'hidden' }}>
          {allTypes.map((type) => {
            const c = typeColor(type)
            const active = !hiddenTypes.has(type)
            return (
              <button key={type} onClick={() => toggleType(type)}
                style={{ padding: '3px 9px', fontSize: '11px', fontFamily: 'var(--font-sans)', fontWeight: 600, borderRadius: '20px', cursor: 'pointer', border: `1px solid ${active ? c.stroke : 'var(--color-border)'}`, background: active ? c.fill : 'transparent', color: active ? c.text : 'var(--color-text-dim)', transition: 'all 100ms ease', whiteSpace: 'nowrap' }}>
                {type}
              </button>
            )
          })}
        </div>

        <div style={{ display: 'flex', gap: '10px', marginLeft: 'auto', alignItems: 'center', flexShrink: 0 }}>
          {[{ n: filteredEntities.length, label: 'entities' }, { n: edges.length, label: 'edges' }].map(({ n, label }) => (
            <span key={label} style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>
              <span style={{ color: 'var(--color-accent)', fontWeight: 700 }}>{n}</span> {label}
            </span>
          ))}
          <button
            onClick={() => { setIsAddingEntity(true); setSelectedId(null) }}
            style={{ ...btnPrimary, padding: '4px 10px', whiteSpace: 'nowrap' }}>
            + Entity
          </button>
        </div>
      </div>

      {/* Body */}
      <div style={{ display: 'flex', flex: '1 1 auto', overflow: 'hidden' }}>
        <div ref={containerRef} style={{ flex: '1 1 auto', overflow: 'hidden', position: 'relative' }}>
          <GraphCanvas
            entities={filteredEntities} edges={edges}
            selectedId={selectedId} searchQuery={search}
            width={dims.width} height={dims.height}
            onSelect={handleSelect}
          />
        </div>

        <div style={{ width: '240px', flexShrink: 0, borderLeft: '1px solid var(--color-border)', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          {isAddingEntity ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 14px', borderBottom: '1px solid var(--color-border)', flexShrink: 0 }}>
                <span style={{ fontSize: '11px', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)' }}>Add Entity</span>
                <button onClick={() => setIsAddingEntity(false)} style={{ fontSize: '14px', lineHeight: 1, color: 'var(--color-text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: '2px 4px' }}>×</button>
              </div>
              <div style={{ flex: '1 1 auto', overflow: 'hidden' }}>
                <AddEntityForm entityTypes={entityTypes} onSave={handleCreateEntity} onCancel={() => setIsAddingEntity(false)} />
              </div>
            </>
          ) : selectedEntity ? (
            <>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 14px', borderBottom: '1px solid var(--color-border)', flexShrink: 0 }}>
                <span style={{ fontSize: '11px', fontWeight: 600, letterSpacing: '0.06em', textTransform: 'uppercase', color: 'var(--color-text-muted)', fontFamily: 'var(--font-sans)' }}>Details</span>
                <button onClick={() => setSelectedId(null)} style={{ fontSize: '14px', lineHeight: 1, color: 'var(--color-text-muted)', background: 'none', border: 'none', cursor: 'pointer', padding: '2px 4px' }}>×</button>
              </div>
              <div style={{ flex: '1 1 auto', overflow: 'hidden' }}>
                <DetailPanel
                  entity={selectedEntity}
                  edgeTypes={edgeTypes}
                  edges={edges}
                  allEntities={entities}
                  onDelete={handleDeleteEntity}
                  onUpdate={handleUpdateEntity}
                  onDeleteEdge={handleDeleteEdge}
                  onAddEdge={handleAddEdge}
                />
              </div>
            </>
          ) : (
            <SchemaPanel entityTypes={entityTypes} edgeTypes={edgeTypes} onRefresh={onRefresh} />
          )}
        </div>
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '14px', padding: '5px 14px', borderTop: '1px solid var(--color-border)', background: 'var(--color-surface)', flexShrink: 0 }}>
        <span style={{ fontSize: '11px', color: 'var(--color-text-dim)' }}>Click node for details · Drag · Scroll to zoom</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <svg width="24" height="8"><line x1="0" y1="4" x2="24" y2="4" stroke="var(--color-border-2)" strokeWidth="1.5" /></svg>
          <span style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>stored</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <svg width="24" height="8"><line x1="0" y1="4" x2="24" y2="4" stroke="#D97706" strokeWidth="1.5" strokeDasharray="4 3" /></svg>
          <span style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>derived</span>
        </div>
      </div>
    </div>
  )
}

export default OntologyView
