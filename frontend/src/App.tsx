import { useState, useCallback, useEffect } from 'react'
import { TopBar } from './components/layout/TopBar'
import { Divider } from './components/layout/Divider'
import { BuilderPanel } from './components/builder/BuilderPanel'
import { SpacePanel } from './components/space/SpacePanel'
import { OntologyView } from './components/ontology/OntologyView'
import { RunsView } from './components/runs/RunsView'
import {
  getAgents, getAgentTasks, getTaskMessages,
  getEntities, getEdges, getRuns,
  streamChat,
} from './api'
import { EVENTS } from './mock/runs'
import type { AgentSpec, Message, Task, Entity, Edge, Run, OntologyEvent } from './types'
import './styles/tokens.css'
import './App.css'

type Tab = 'workspace' | 'ontology' | 'runs'
type PanelState = 'normal' | 'expanded' | 'collapsed'

export default function App() {
  const [tab, setTab] = useState<Tab>('workspace')
  const [agents, setAgents] = useState<AgentSpec[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState<string>('')
  const [tasks, setTasks] = useState<Record<string, Task[]>>({})
  const [selectedTaskIds, setSelectedTaskIds] = useState<Record<string, string>>({})
  const [messages, setMessages] = useState<Record<string, Message[]>>({})
  const [entities, setEntities] = useState<Entity[]>([])
  const [edges, setEdges] = useState<Edge[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [events] = useState<OntologyEvent[]>(EVENTS)

  const [builderState, setBuilderState] = useState<PanelState>('normal')
  const [spaceState, setSpaceState] = useState<PanelState>('normal')
  const [splitPercent, setSplitPercent] = useState(44)

  useEffect(() => {
    getAgents().then((loaded) => {
      if (loaded.length > 0) {
        setAgents(loaded)
        setSelectedAgentId(loaded[0].id)
      }
    }).catch(console.error)
    getEntities().then(setEntities).catch(console.error)
    getEdges().then(setEdges).catch(console.error)
    getRuns().then(setRuns).catch(console.error)
  }, [])

  useEffect(() => {
    if (!selectedAgentId) return
    getAgentTasks(selectedAgentId).then((loaded) => {
      setTasks((prev) => ({ ...prev, [selectedAgentId]: loaded }))
      if (loaded.length > 0 && !selectedTaskIds[selectedAgentId]) {
        setSelectedTaskIds((prev) => ({ ...prev, [selectedAgentId]: loaded[0].id }))
      }
    }).catch(console.error)
  }, [selectedAgentId])

  const selectedTaskId = selectedTaskIds[selectedAgentId] ?? ''

  useEffect(() => {
    if (!selectedTaskId) return
    getTaskMessages(selectedTaskId).then((loaded) => {
      setMessages((prev) => ({ ...prev, [selectedTaskId]: loaded }))
    }).catch(console.error)
  }, [selectedTaskId])

  const selectedAgent = agents.find((a) => a.id === selectedAgentId) ?? agents[0]
  const currentMessages = messages[selectedTaskId] ?? []

  const handleBuilderExpand = () => {
    if (builderState === 'expanded') { setBuilderState('normal'); setSpaceState('normal') }
    else { setBuilderState('expanded'); setSpaceState('collapsed') }
  }

  const handleBuilderCollapse = () => {
    if (builderState === 'collapsed') { setBuilderState('normal'); setSpaceState('normal') }
    else { setBuilderState('collapsed'); setSpaceState('expanded') }
  }

  const handleSpaceExpand = () => {
    if (spaceState === 'expanded') { setSpaceState('normal'); setBuilderState('normal') }
    else { setSpaceState('expanded'); setBuilderState('collapsed') }
  }

  const handleSpaceCollapse = () => {
    if (spaceState === 'collapsed') { setSpaceState('normal'); setBuilderState('normal') }
    else { setSpaceState('collapsed'); setBuilderState('expanded') }
  }

  const handleDividerResize = useCallback((delta: number) => {
    setSplitPercent((prev) => {
      const containerH = window.innerHeight - 48 - 5
      const newPx = (prev / 100) * containerH + delta
      const newPct = (newPx / containerH) * 100
      return Math.max(15, Math.min(85, newPct))
    })
  }, [])

  const handleSend = (text: string) => {
    const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    const userMsg: Message = { id: `msg-${Date.now()}`, role: 'user', content: text, timestamp: now }
    setMessages((prev) => ({
      ...prev,
      [selectedTaskId]: [...(prev[selectedTaskId] ?? []), userMsg],
    }))

    const stopStream = streamChat(selectedAgentId, selectedTaskId || null, text, {
      onMessage: (content) => {
        const agentMsg: Message = {
          id: `msg-${Date.now()}-agent`,
          role: 'agent',
          content,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        }
        setMessages((prev) => ({
          ...prev,
          [selectedTaskId]: [...(prev[selectedTaskId] ?? []), agentMsg],
        }))
      },
      onDone: (_runId, taskId) => {
        getEntities().then(setEntities).catch(console.error)
        getRuns().then(setRuns).catch(console.error)
        if (taskId) {
          getTaskMessages(taskId).then((loaded) => {
            setMessages((prev) => ({ ...prev, [taskId]: loaded }))
          }).catch(console.error)
        }
        getAgentTasks(selectedAgentId).then((loaded) => {
          setTasks((prev) => ({ ...prev, [selectedAgentId]: loaded }))
        }).catch(console.error)
      },
      onError: (detail) => console.error('Agent error:', detail),
    })

    void stopStream
  }

  const handleAgentUpdate = (updated: AgentSpec) => {
    setAgents((prev) => prev.map((a) => (a.id === updated.id ? updated : a)))
  }

  const handleAgentSelect = (id: string) => {
    setSelectedAgentId(id)
    if (!selectedTaskIds[id]) {
      const agentTasks = tasks[id] ?? []
      if (agentTasks.length > 0) {
        setSelectedTaskIds((prev) => ({ ...prev, [id]: agentTasks[0].id }))
      }
    }
  }

  const builderHeight = builderState === 'expanded' ? 'calc(100% - 5px)'
    : builderState === 'collapsed' ? '40px'
    : `${splitPercent}%`

  const spaceStyle: React.CSSProperties = builderState === 'expanded'
    ? { display: 'none' }
    : spaceState === 'collapsed'
    ? { height: '40px', flexShrink: 0, flex: 'none' }
    : { flex: '1 1 auto' }

  return (
    <div className="app">
      <TopBar activeTab={tab} onTabChange={setTab} />

      {tab === 'workspace' && (
        <div className="workspace">
          <BuilderPanel
            agents={agents}
            selectedId={selectedAgentId}
            onSelect={handleAgentSelect}
            onUpdate={handleAgentUpdate}
            expanded={builderState === 'expanded'}
            collapsed={builderState === 'collapsed'}
            onExpand={handleBuilderExpand}
            onCollapse={handleBuilderCollapse}
            style={{ height: builderHeight, flexShrink: 0 }}
          />

          {builderState !== 'expanded' && (
            <Divider onResize={handleDividerResize} />
          )}

          <SpacePanel
            agent={selectedAgent}
            tasks={tasks[selectedAgentId] ?? []}
            selectedTaskId={selectedTaskId}
            messages={currentMessages}
            entities={entities}
            onTaskSelect={(id) => setSelectedTaskIds((prev) => ({ ...prev, [selectedAgentId]: id }))}
            onSend={handleSend}
            expanded={spaceState === 'expanded'}
            collapsed={spaceState === 'collapsed'}
            onExpand={handleSpaceExpand}
            onCollapse={handleSpaceCollapse}
            style={spaceStyle}
          />
        </div>
      )}

      {tab === 'ontology' && (
        <OntologyView entities={entities} edges={edges} runs={runs} />
      )}

      {tab === 'runs' && (
        <RunsView runs={runs} events={events} agents={agents} />
      )}
    </div>
  )
}
