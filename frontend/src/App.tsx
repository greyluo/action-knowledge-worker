import { useState, useCallback, useEffect } from 'react'
import { TopBar } from './components/layout/TopBar'
import { BuilderPanel } from './components/builder/BuilderPanel'
import { SpacePanel } from './components/space/SpacePanel'
import { OntologyView } from './components/ontology/OntologyView'
import { PoliciesPanel } from './components/policies/PoliciesPanel'
import {
  getAgents, getAgentTasks, getTaskMessages,
  getEntities, getEdges, getRuns,
  getEntityTypes, getEdgeTypes,
  getPolicies, getTools, deleteTask,
  streamChat,
} from './api'
import type { AgentSpec, Message, Task, Entity, Edge, Run, EntityType, EdgeType, Policy, ToolDef } from './types'
import './styles/tokens.css'
import './App.css'

type Tab = 'workspace' | 'ontology' | 'policies'

export default function App() {
  const [tab, setTab] = useState<Tab>('workspace')
  const [builderOpen, setBuilderOpen] = useState(true)

  const [agents, setAgents] = useState<AgentSpec[]>([])
  const [selectedAgentId, setSelectedAgentId] = useState<string>('')
  const [tasks, setTasks] = useState<Record<string, Task[]>>({})
  const [selectedTaskIds, setSelectedTaskIds] = useState<Record<string, string>>({})
  const [messages, setMessages] = useState<Record<string, Message[]>>({})
  const [entities, setEntities] = useState<Entity[]>([])
  const [edges, setEdges] = useState<Edge[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [entityTypes, setEntityTypes] = useState<EntityType[]>([])
  const [edgeTypes, setEdgeTypes] = useState<EdgeType[]>([])
  const [policies, setPolicies] = useState<Policy[]>([])
  const [tools, setTools] = useState<ToolDef[]>([])
  const [isAgentStreaming, setIsAgentStreaming] = useState(false)

  const loadEdges = useCallback(() => {
    getEdges().then(setEdges).catch(console.error)
  }, [])

  useEffect(() => {
    getAgents().then((loaded) => {
      if (loaded.length > 0) { setAgents(loaded); setSelectedAgentId(loaded[0].id) }
    }).catch(console.error)
    getEntities().then(setEntities).catch(console.error)
    loadEdges()
    getEntityTypes().then(setEntityTypes).catch(console.error)
    getEdgeTypes().then(setEdgeTypes).catch(console.error)
    getRuns().then(setRuns).catch(console.error)
    getPolicies().then(setPolicies).catch(console.error)
    getTools().then(setTools).catch(console.error)
  }, [loadEdges])

  useEffect(() => {
    if (!selectedAgentId) return
    getAgentTasks(selectedAgentId).then((loaded) => {
      setTasks((prev) => ({ ...prev, [selectedAgentId]: loaded }))
      if (loaded.length > 0 && !selectedTaskIds[selectedAgentId]) {
        setSelectedTaskIds((prev) => ({ ...prev, [selectedAgentId]: loaded[0].id }))
      }
    }).catch(console.error)
  }, [selectedAgentId]) // eslint-disable-line react-hooks/exhaustive-deps

  const selectedTaskId = selectedTaskIds[selectedAgentId] ?? ''

  useEffect(() => {
    if (!selectedTaskId) return
    getTaskMessages(selectedTaskId).then((loaded) => {
      setMessages((prev) => ({ ...prev, [selectedTaskId]: loaded }))
    }).catch(console.error)
  }, [selectedTaskId])

  const selectedAgent = agents.find((a) => a.id === selectedAgentId) ?? agents[0]
  const currentMessages = messages[selectedTaskId] ?? []

  const taskRuns = runs.filter((r) => r.task_id === selectedTaskId)
  const taskRunIds = new Set(taskRuns.map((r) => r.id))
  const taskEntities = selectedTaskId
    ? entities.filter((e) => e.created_in_run_id && taskRunIds.has(e.created_in_run_id))
    : []
  const currentRunId = taskRuns.length > 0 ? taskRuns[taskRuns.length - 1].id : undefined

  const refreshOntology = useCallback(() => {
    getEntities().then(setEntities).catch(console.error)
    getEdges().then(setEdges).catch(console.error)
    getEntityTypes().then(setEntityTypes).catch(console.error)
    getEdgeTypes().then(setEdgeTypes).catch(console.error)
  }, [])

  const handleSend = (text: string) => {
    const sentTaskId = selectedTaskId
    const now = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    const userMsg: Message = { id: `msg-${Date.now()}`, role: 'user', content: text, timestamp: now }
    setMessages((prev) => ({ ...prev, [sentTaskId]: [...(prev[sentTaskId] ?? []), userMsg] }))
    setIsAgentStreaming(true)

    streamChat(selectedAgentId, sentTaskId || null, text, {
      onMessage: (content) => {
        const agentMsg: Message = {
          id: `msg-${Date.now()}-agent`, role: 'agent', content,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        }
        setMessages((prev) => ({ ...prev, [sentTaskId]: [...(prev[sentTaskId] ?? []), agentMsg] }))
      },
      onDone: (_runId, taskId) => {
        setIsAgentStreaming(false)
        getEntities().then(setEntities).catch(console.error)
        getEdges().then(setEdges).catch(console.error)
        getRuns().then(setRuns).catch(console.error)
        getAgentTasks(selectedAgentId).then((loaded) => {
          setTasks((prev) => ({ ...prev, [selectedAgentId]: loaded }))
        }).catch(console.error)
        if (taskId) {
          getTaskMessages(taskId).then((loaded) => {
            const visible = loaded.filter((m) => m.content.trim() || (m.tool_calls && m.tool_calls.length > 0))
            setMessages((prev) => {
              const next = { ...prev, [taskId]: visible }
              if (sentTaskId === '') delete next['']
              return next
            })
            setSelectedTaskIds((prev) => {
              const current = prev[selectedAgentId]
              if (current === sentTaskId || sentTaskId === '') {
                return { ...prev, [selectedAgentId]: taskId }
              }
              return prev
            })
          }).catch(console.error)
        }
      },
      onError: (detail) => { setIsAgentStreaming(false); console.error('Agent error:', detail) },
    })
  }

  const handleDeleteTask = async (taskId: string) => {
    await deleteTask(taskId).catch(console.error)
    setTasks((prev) => ({ ...prev, [selectedAgentId]: (prev[selectedAgentId] ?? []).filter((t) => t.id !== taskId) }))
    setMessages((prev) => { const next = { ...prev }; delete next[taskId]; return next })
    if (selectedTaskIds[selectedAgentId] === taskId) {
      const remaining = (tasks[selectedAgentId] ?? []).filter((t) => t.id !== taskId)
      setSelectedTaskIds((prev) => ({ ...prev, [selectedAgentId]: remaining[0]?.id ?? '' }))
    }
  }

  const handleAgentUpdate = (updated: AgentSpec) => {
    setAgents((prev) => {
      const exists = prev.some((a) => a.id === updated.id)
      return exists ? prev.map((a) => (a.id === updated.id ? updated : a)) : [...prev, updated]
    })
    setSelectedAgentId(updated.id)
  }

  const handleAgentDelete = (id: string) => {
    setAgents((prev) => {
      const remaining = prev.filter((a) => a.id !== id)
      if (selectedAgentId === id) setSelectedAgentId(remaining[0]?.id ?? '')
      return remaining
    })
  }

  const handleAgentSelect = (id: string) => {
    setSelectedAgentId(id)
    if (!selectedTaskIds[id]) {
      const agentTasks = tasks[id] ?? []
      if (agentTasks.length > 0) setSelectedTaskIds((prev) => ({ ...prev, [id]: agentTasks[0].id }))
    }
  }

  return (
    <div className="app">
      <TopBar activeTab={tab} onTabChange={setTab} />

      {tab === 'workspace' && (
        <div className="workspace">
          {/* Builder sidebar — width animates open/closed */}
          <div style={{
            width: builderOpen ? 264 : 0,
            flexShrink: 0,
            overflow: 'hidden',
            transition: 'width 220ms cubic-bezier(0.4, 0, 0.2, 1)',
            borderRight: builderOpen ? '1px solid var(--color-border)' : 'none',
          }}>
            <BuilderPanel
              agents={agents}
              selectedId={selectedAgentId}
              onSelect={handleAgentSelect}
              onUpdate={handleAgentUpdate}
              onDelete={handleAgentDelete}
            />
          </div>

          <SpacePanel
            agent={selectedAgent}
            tasks={tasks[selectedAgentId] ?? []}
            selectedTaskId={selectedTaskId}
            messages={currentMessages}
            entities={taskEntities}
            isStreaming={isAgentStreaming}
            currentRunId={currentRunId}
            onTaskSelect={(id) => setSelectedTaskIds((prev) => ({ ...prev, [selectedAgentId]: id }))}
            onDeleteTask={handleDeleteTask}
            onSend={handleSend}
            builderOpen={builderOpen}
            onToggleBuilder={() => setBuilderOpen((v) => !v)}
          />
        </div>
      )}

      {tab === 'ontology' && (
        <OntologyView
          entities={entities}
          edges={edges}
          runs={runs}
          entityTypes={entityTypes}
          edgeTypes={edgeTypes}
          onRefresh={refreshOntology}
        />
      )}

      {tab === 'policies' && (
        <PoliciesPanel
          policies={policies}
          entityTypes={entityTypes}
          edgeTypes={edgeTypes}
          tools={tools}
          onRefresh={() => getPolicies().then(setPolicies).catch(console.error)}
        />
      )}

    </div>
  )
}
