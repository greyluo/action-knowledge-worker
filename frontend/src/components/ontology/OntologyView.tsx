import { useMemo, useRef, useState, useEffect, useCallback } from 'react'
import { forceSimulation, forceManyBody, forceLink, forceCollide, forceCenter } from 'd3-force'
import type { SimulationNodeDatum, SimulationLinkDatum } from 'd3-force'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
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
  ...btnBase, color: '#EF4444', border: '1px solid #FCA5A5', background: '#FFF5F5',
}
const btnPrimary: React.CSSProperties = {
  ...btnBase, color: 'var(--color-accent)', border: '1px solid var(--color-accent)',
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
  for (let iter = 0; iter < 60; iter++) {
    let moved = false
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dx = nodes[j].x - nodes[i].x
        const dy = nodes[j].y - nodes[i].y
        const dist = Math.sqrt(dx * dx + dy * dy)
        if (dist < minDist) {
          // When nodes are exactly coincident (dist ≈ 0), dx/dy are both zero so the
          // unit vector is (0,0) and the push goes nowhere. Use a golden-angle spread
          // keyed on i so each coincident pair gets a unique separation direction.
          let ux: number, uy: number
          if (dist < 0.001) {
            const angle = i * 2.39996  // golden angle in radians
            ux = Math.cos(angle); uy = Math.sin(angle)
          } else {
            ux = dx / dist; uy = dy / dist
          }
          const push = (minDist - dist) / 2 + 1
          const ix0 = nodes[i].x, iy0 = nodes[i].y
          const jx0 = nodes[j].x, jy0 = nodes[j].y
          nodes[i].x = Math.max(pad, Math.min(width - pad, nodes[i].x - ux * push))
          nodes[i].y = Math.max(pad, Math.min(height - pad, nodes[i].y - uy * push))
          nodes[j].x = Math.max(pad, Math.min(width - pad, nodes[j].x + ux * push))
          nodes[j].y = Math.max(pad, Math.min(height - pad, nodes[j].y + uy * push))
          if (nodes[i].x !== ix0 || nodes[i].y !== iy0 || nodes[j].x !== jx0 || nodes[j].y !== jy0) moved = true
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

// Like runForce but pins existing nodes in place — only free nodes move.
type PinnableSimNode = SimNode & { fx?: number | null; fy?: number | null }

function runForcePartial(
  nodes: NodeState[],
  edgeList: Array<{ src: string; dst: string }>,
  width: number,
  height: number,
  freeNodeIds: Set<string>,
): NodeState[] {
  if (nodes.length === 0) return []

  const simNodes: PinnableSimNode[] = nodes.map((n) => ({
    ...n,
    fx: freeNodeIds.has(n.id) ? null : n.x,
    fy: freeNodeIds.has(n.id) ? null : n.y,
  }))
  const nodeById = new Map(simNodes.map((n) => [n.id, n]))

  const links: SimLink[] = edgeList
    .filter((e) => nodeById.has(e.src) && nodeById.has(e.dst))
    .map((e) => ({ source: nodeById.get(e.src)! as SimNode, target: nodeById.get(e.dst)! as SimNode }))

  const sim = forceSimulation<PinnableSimNode>(simNodes)
    .force('charge', forceManyBody<PinnableSimNode>().strength(-800).distanceMin(NODE_RADIUS * 2))
    .force('link', forceLink<PinnableSimNode, SimLink>(links).distance(200).strength(0.15))
    .force('collide', forceCollide<PinnableSimNode>(NODE_RADIUS + NODE_GAP / 2 + 4).strength(1).iterations(6))
    .stop()

  for (let i = 0; i < 300; i++) sim.tick()

  const pad = NODE_RADIUS + 8
  const result: NodeState[] = simNodes.map((n) => ({
    id: n.id, name: n.name, type: n.type,
    x: Math.max(pad, Math.min(width - pad, n.x ?? width / 2)),
    y: Math.max(pad, Math.min(height - pad, n.y ?? height / 2)),
    vx: 0, vy: 0,
  }))

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
  const savedPositionsRef = useRef<Map<string, { x: number; y: number }>>(new Map())
  const initializedRef = useRef(false)

  const entityIds = useMemo(() => new Set(entities.map((e) => e.id)), [entities])
  const visibleEdges = useMemo(() => edges.filter((e) => entityIds.has(e.src) && entityIds.has(e.dst)), [edges, entityIds])

  // Keep saved positions in sync with current node positions (including drags)
  useEffect(() => {
    for (const n of nodes) savedPositionsRef.current.set(n.id, { x: n.x, y: n.y })
  }, [nodes])

  useEffect(() => {
    if (entities.length === 0) {
      setNodes([])
      initializedRef.current = false
      savedPositionsRef.current.clear()
      return
    }

    const saved = savedPositionsRef.current
    const edgeList = visibleEdges.map((e) => ({ src: e.src, dst: e.dst }))

    if (!initializedRef.current) {
      const initial: NodeState[] = entities.map((e) => ({
        id: e.id, x: width * 0.1 + Math.random() * width * 0.8, y: height * 0.1 + Math.random() * height * 0.8,
        vx: 0, vy: 0, name: e.name, type: e.type,
      }))
      setNodes(runForce(initial, edgeList, width, height))
      setPan({ x: 0, y: 0 }); setScale(1)
      initializedRef.current = true
      return
    }

    // Incremental update: seed existing nodes from saved positions
    const newNodeIds = new Set(entities.filter((e) => !saved.has(e.id)).map((e) => e.id))
    const nodeList: NodeState[] = entities.map((e) => {
      const pos = saved.get(e.id)
      return {
        id: e.id,
        x: pos?.x ?? width / 2 + (Math.random() - 0.5) * 200,
        y: pos?.y ?? height / 2 + (Math.random() - 0.5) * 200,
        vx: 0, vy: 0, name: e.name, type: e.type,
      }
    })

    if (newNodeIds.size === 0) {
      setNodes(nodeList)
    } else {
      setNodes(runForcePartial(nodeList, edgeList, width, height, newNodeIds))
    }
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

function hashFloat(str: string): number {
  let h = 0
  for (let i = 0; i < str.length; i++) h = (Math.imul(31, h) + str.charCodeAt(i)) >>> 0
  return h / 0xffffffff
}

// ─── 3D label sprite ─────────────────────────────────────────────────────────

function makeNodeLabel(text: string, color: string): THREE.Sprite {
  const label = text.length > 18 ? text.slice(0, 17) + '…' : text
  const canvas = document.createElement('canvas')
  canvas.width = 256; canvas.height = 40
  const ctx = canvas.getContext('2d')!
  ctx.font = 'bold 20px system-ui, sans-serif'
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.shadowColor = 'rgba(0,0,0,0.9)'; ctx.shadowBlur = 8
  ctx.fillStyle = color
  ctx.fillText(label, 128, 20)
  const tex = new THREE.CanvasTexture(canvas)
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false })
  const sprite = new THREE.Sprite(mat)
  sprite.scale.set(64, 10, 1)
  return sprite
}

// ─── 3D Graph canvas ──────────────────────────────────────────────────────────

interface Graph3DCanvasProps {
  entities: Entity[]
  edges: Edge[]
  selectedId: string | null
  width: number
  height: number
  onSelect: (id: string | null) => void
}

interface ThreeState {
  renderer: THREE.WebGLRenderer
  scene: THREE.Scene
  camera: THREE.PerspectiveCamera
  controls: OrbitControls
  rafId: number
}

function Graph3DCanvas({ entities, edges, selectedId, width, height, onSelect }: Graph3DCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const threeRef = useRef<ThreeState | null>(null)
  const nodeMeshesRef = useRef<Map<string, THREE.Mesh>>(new Map())
  const onSelectRef = useRef(onSelect)
  const selectedIdRef = useRef(selectedId)

  useEffect(() => { onSelectRef.current = onSelect }, [onSelect])
  useEffect(() => { selectedIdRef.current = selectedId }, [selectedId])

  // Compute 3D positions: d3-force for x/y, type-cluster for z
  const nodePositions = useMemo(() => {
    if (entities.length === 0) return new Map<string, THREE.Vector3>()
    const types = Array.from(new Set(entities.map((e) => e.type))).sort()
    const mid = (types.length - 1) / 2
    const zByType = Object.fromEntries(types.map((t, i) => [t, (i - mid) * 100]))
    const edgeList = edges.map((e) => ({ src: e.src, dst: e.dst }))
    const initial: NodeState[] = entities.map((e) => ({
      id: e.id, name: e.name, type: e.type,
      x: hashFloat(e.id) * 600, y: hashFloat(e.id + 'y') * 600, vx: 0, vy: 0,
    }))
    const laid = runForce(initial, edgeList, 600, 600)
    const positions = new Map<string, THREE.Vector3>()
    for (const n of laid) {
      positions.set(n.id, new THREE.Vector3((n.x - 300) * 1.2, (300 - n.y) * 1.2, zByType[n.type] ?? 0))
    }
    return positions
  }, [entities, edges])

  // Mount Three.js scene once
  useEffect(() => {
    if (!containerRef.current) return

    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x0d0d1a)

    const camera = new THREE.PerspectiveCamera(60, width / height, 1, 5000)
    camera.position.set(0, 0, 900)

    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setSize(width, height)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    containerRef.current.appendChild(renderer.domElement)

    scene.add(new THREE.AmbientLight(0xffffff, 0.5))
    const dir = new THREE.DirectionalLight(0xffffff, 1.0)
    dir.position.set(200, 300, 200)
    scene.add(dir)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.08

    let rafId = 0
    function animate() {
      rafId = requestAnimationFrame(animate)
      controls.update()
      renderer.render(scene, camera)
    }
    animate()
    threeRef.current = { renderer, scene, camera, controls, rafId }

    // Click detection — ignore drags
    let mouseDownX = 0, mouseDownY = 0
    const raycaster = new THREE.Raycaster()
    const mouse = new THREE.Vector2()
    const onMouseDown = (e: MouseEvent) => { mouseDownX = e.clientX; mouseDownY = e.clientY }
    const onClick = (e: MouseEvent) => {
      if (Math.hypot(e.clientX - mouseDownX, e.clientY - mouseDownY) > 5) return
      const rect = renderer.domElement.getBoundingClientRect()
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1
      raycaster.setFromCamera(mouse, camera)
      const hits = raycaster.intersectObjects(Array.from(nodeMeshesRef.current.values()))
      if (hits.length > 0) {
        const id = (hits[0].object as THREE.Mesh).userData.entityId as string
        onSelectRef.current(selectedIdRef.current === id ? null : id)
      } else {
        onSelectRef.current(null)
      }
    }
    renderer.domElement.addEventListener('mousedown', onMouseDown)
    renderer.domElement.addEventListener('click', onClick)

    return () => {
      cancelAnimationFrame(rafId)
      controls.dispose()
      renderer.domElement.removeEventListener('mousedown', onMouseDown)
      renderer.domElement.removeEventListener('click', onClick)
      renderer.dispose()
      containerRef.current?.removeChild(renderer.domElement)
      threeRef.current = null
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Rebuild scene graph whenever data or positions change
  useEffect(() => {
    const state = threeRef.current
    if (!state) return
    const { scene } = state

    // Remove and dispose all previous graph objects
    const toRemove = scene.children.filter((c) => c.userData.graph)
    for (const obj of toRemove) {
      if (obj instanceof THREE.Mesh || obj instanceof THREE.LineSegments) {
        obj.geometry.dispose()
        ;(obj.material as THREE.Material).dispose()
      } else if (obj instanceof THREE.Sprite) {
        const mat = obj.material as THREE.SpriteMaterial
        mat.map?.dispose()
        mat.dispose()
      }
      scene.remove(obj)
    }
    nodeMeshesRef.current.clear()

    if (entities.length === 0) return

    const nodeIds = new Set(entities.map((e) => e.id))
    const visibleEdges = edges.filter((e) => nodeIds.has(e.src) && nodeIds.has(e.dst))

    // Edges as line segments
    const edgeVerts: number[] = []
    const edgeColors: number[] = []
    for (const edge of visibleEdges) {
      const sp = nodePositions.get(edge.src)
      const ep = nodePositions.get(edge.dst)
      if (!sp || !ep) continue
      edgeVerts.push(sp.x, sp.y, sp.z, ep.x, ep.y, ep.z)
      const c = new THREE.Color(edge.derived ? '#D97706' : '#334455')
      edgeColors.push(c.r, c.g, c.b, c.r, c.g, c.b)

      // Label at midpoint
      const labelColor = edge.derived ? '#D97706' : '#94A3B8'
      const edgeLabel = makeNodeLabel(edge.type, labelColor)
      edgeLabel.position.set((sp.x + ep.x) / 2, (sp.y + ep.y) / 2, (sp.z + ep.z) / 2)
      edgeLabel.scale.set(48, 8, 1)
      edgeLabel.userData = { graph: true }
      scene.add(edgeLabel)
    }
    if (edgeVerts.length > 0) {
      const geo = new THREE.BufferGeometry()
      geo.setAttribute('position', new THREE.Float32BufferAttribute(edgeVerts, 3))
      geo.setAttribute('color', new THREE.Float32BufferAttribute(edgeColors, 3))
      const lines = new THREE.LineSegments(geo, new THREE.LineBasicMaterial({ vertexColors: true, opacity: 0.5, transparent: true }))
      lines.userData.graph = true
      scene.add(lines)
    }

    // Nodes as spheres
    const sphereGeo = new THREE.SphereGeometry(10, 32, 24)
    for (const entity of entities) {
      const pos = nodePositions.get(entity.id)
      if (!pos) continue
      const isSelected = entity.id === selectedId
      const col = typeColor(entity.type)

      const mat = new THREE.MeshStandardMaterial({
        color: new THREE.Color(col.stroke),
        emissive: new THREE.Color(col.stroke),
        emissiveIntensity: isSelected ? 0.7 : 0.35,
        roughness: 0.35,
        metalness: 0.1,
        transparent: true,
        opacity: 0.5,
      })
      const mesh = new THREE.Mesh(sphereGeo, mat)
      mesh.position.copy(pos)
      mesh.userData = { graph: true, entityId: entity.id }
      scene.add(mesh)
      nodeMeshesRef.current.set(entity.id, mesh)

      const sprite = makeNodeLabel(entity.name, col.fill)
      ;(sprite.material as THREE.SpriteMaterial).depthTest = false
      sprite.position.set(pos.x, pos.y, pos.z)
      sprite.userData = { graph: true }
      scene.add(sprite)
    }
  }, [entities, edges, nodePositions, selectedId])

  // Resize
  useEffect(() => {
    const state = threeRef.current
    if (!state) return
    state.renderer.setSize(width, height)
    state.camera.aspect = width / height
    state.camera.updateProjectionMatrix()
  }, [width, height])

  return <div ref={containerRef} />
}

// ─── Detail panel ─────────────────────────────────────────────────────────────

interface DetailPanelProps {
  entity: Entity
  edgeTypes: EdgeType[]
  edges: Edge[]
  allEntities: Entity[]
  readOnly?: boolean
  onDelete: (id: string) => Promise<void>
  onUpdate: (id: string, props: Record<string, unknown>) => Promise<void>
  onDeleteEdge: (edgeId: string) => Promise<void>
  onAddEdge: (srcId: string, dstId: string, edgeTypeName: string) => Promise<void>
}

function DetailPanel({ entity, edgeTypes, edges, allEntities, readOnly = false, onDelete, onUpdate, onDeleteEdge, onAddEdge }: DetailPanelProps) {
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

  useEffect(() => {
    if (readOnly) { setIsEditing(false); setIsAddingEdge(false) }
  }, [readOnly])

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
          {readOnly
            ? <span style={{ fontSize: '11px', color: 'var(--color-text-dim)', fontFamily: 'var(--font-sans)', fontStyle: 'italic' }}>read-only in 3D mode</span>
            : <>
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
              </>
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
          {!readOnly && (
            <button onClick={() => { setIsAddingEdge(true); setNewEdgeType(storedEdgeTypes[0]?.name ?? ''); setNewEdgeDst(''); setNewEdgeDir('out'); setError('') }}
              style={{ ...btnBase, padding: '2px 7px', fontSize: '11px' }}>+ Add</button>
          )}
        </div>

        {isAddingEdge && (
          <div style={{ padding: '8px 10px', background: 'var(--color-surface-2)', borderRadius: 'var(--radius-md)', marginBottom: '8px', border: '1px solid var(--color-border)' }}>
            <div style={{ display: 'flex', gap: '4px', marginBottom: '5px' }}>
              {(['out', 'in'] as const).map((d) => (
                <button key={d} onClick={() => setNewEdgeDir(d)}
                  style={{ ...btnBase, padding: '2px 8px', background: newEdgeDir === d ? 'color-mix(in srgb, var(--color-accent) 12%, transparent)' : undefined, color: newEdgeDir === d ? 'var(--color-accent)' : undefined, border: newEdgeDir === d ? '1px solid var(--color-accent)' : btnBase.border }}>
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
            {!edge.derived && !readOnly && (
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

const EXCLUDED_TYPES = new Set(['Run', 'Task', 'Handoff'])

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
  const [dims, setDims] = useState<{ width: number; height: number } | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [shownTypes, setShownTypes] = useState<Set<string>>(new Set())
  const [isAddingEntity, setIsAddingEntity] = useState(false)
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('2d')

  const toggleViewMode = useCallback((mode: '2d' | '3d') => {
    if (mode === '3d') setIsAddingEntity(false)
    setViewMode(mode)
  }, [])

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
  const filteredEntities = useMemo(() => entities.filter((e) => !EXCLUDED_TYPES.has(e.type) && shownTypes.has(e.type)), [entities, shownTypes])

  // Auto-show types that appear for the first time (don't override explicit user unchecks)
  useEffect(() => {
    setShownTypes((prev) => {
      const next = new Set(prev)
      let changed = false
      for (const t of allTypes) {
        if (!next.has(t)) { next.add(t); changed = true }
      }
      return changed ? next : prev
    })
  }, [allTypes])
  const selectedEntity = useMemo(() => entities.find((e) => e.id === selectedId) ?? null, [entities, selectedId])

  const toggleType = (type: string) => {
    setShownTypes((prev: Set<string>) => { const next = new Set(prev); next.has(type) ? next.delete(type) : next.add(type); return next })
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

        <div style={{ display: 'flex', gap: '5px', flexWrap: 'nowrap', overflow: 'hidden', alignItems: 'center' }}>
          <button
            onClick={() => {
              if (shownTypes.size === allTypes.length) {
                setShownTypes(new Set())
                setSelectedId(null)
              } else {
                setShownTypes(new Set(allTypes))
              }
            }}
            style={{ padding: '3px 9px', fontSize: '11px', fontFamily: 'var(--font-sans)', fontWeight: 600, borderRadius: '20px', cursor: 'pointer', border: '1px solid var(--color-border)', background: shownTypes.size === allTypes.length ? 'var(--color-surface-2)' : 'transparent', color: 'var(--color-text-muted)', transition: 'all 100ms ease', whiteSpace: 'nowrap' }}>
            {shownTypes.size === allTypes.length ? 'None' : 'All'}
          </button>
          {allTypes.map((type) => {
            const c = typeColor(type)
            const active = shownTypes.has(type)
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
          <div style={{ display: 'flex', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
            {(['2d', '3d'] as const).map((m) => (
              <button key={m} onClick={() => toggleViewMode(m)}
                style={{ ...(viewMode === m ? btnPrimary : btnBase), border: 'none', borderRadius: 0, padding: '3px 10px', textTransform: 'uppercase', fontSize: '11px' }}>
                {m}
              </button>
            ))}
          </div>
          <button
            onClick={() => { setIsAddingEntity(true); setSelectedId(null) }}
            disabled={viewMode === '3d'}
            style={{ ...btnPrimary, padding: '4px 10px', whiteSpace: 'nowrap', opacity: viewMode === '3d' ? 0.4 : 1 }}>
            + Entity
          </button>
        </div>
      </div>

      {/* Body */}
      <div style={{ display: 'flex', flex: '1 1 auto', overflow: 'hidden' }}>
        <div ref={containerRef} style={{ flex: '1 1 auto', overflow: 'hidden', position: 'relative' }}>
          {dims && (viewMode === '3d'
            ? <Graph3DCanvas
                entities={filteredEntities} edges={edges}
                selectedId={selectedId}
                width={dims.width} height={dims.height}
                onSelect={handleSelect}
              />
            : <GraphCanvas
                entities={filteredEntities} edges={edges}
                selectedId={selectedId} searchQuery={search}
                width={dims.width} height={dims.height}
                onSelect={handleSelect}
              />
          )}
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
                  readOnly={viewMode === '3d'}
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
        <span style={{ fontSize: '11px', color: 'var(--color-text-dim)' }}>
          Click node for details · {viewMode === '3d' ? 'Drag to rotate' : 'Drag'} · Scroll to zoom
        </span>
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
