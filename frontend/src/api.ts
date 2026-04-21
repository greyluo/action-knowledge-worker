import type { AgentSpec, Entity, Edge, Run, OntologyEvent, Task, Message, EntityType, EdgeType } from './types'

const BASE = 'http://localhost:8001'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`)
  return res.json()
}

export const getAgents = (): Promise<AgentSpec[]> => get('/agents')
export const getAgentTasks = (agentId: string): Promise<Task[]> => get(`/agents/${agentId}/tasks`)
export const getTaskMessages = (taskId: string): Promise<Message[]> => get(`/tasks/${taskId}/messages`)
export const getEntities = (type?: string): Promise<Entity[]> =>
  get(`/entities${type ? `?type=${type}` : ''}`)
export const getEdges = (): Promise<Edge[]> => get('/edges')
export const getRuns = (): Promise<Run[]> => get('/runs')
export const getRunEvents = (runId: string): Promise<OntologyEvent[]> => get(`/runs/${runId}/events`)
export const getEntityTypes = (): Promise<EntityType[]> => get('/schema/entity-types')
export const getEdgeTypes = (): Promise<EdgeType[]> => get('/schema/edge-types')

export interface ChatCallbacks {
  onToolCall?: (tool: string, args: Record<string, unknown>) => void
  onMessage?: (content: string) => void
  onDone?: (runId: string, taskId: string) => void
  onError?: (detail: string) => void
}

export function streamChat(
  agentId: string,
  taskId: string | null,
  message: string,
  callbacks: ChatCallbacks,
): () => void {
  const controller = new AbortController()

  fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent_id: agentId, task_id: taskId, message }),
    signal: controller.signal,
  })
    .then((res) => parseSseStream(res, (type, data) => {
      if (type === 'tool_call') callbacks.onToolCall?.(data.tool as string, data.args as Record<string, unknown>)
      else if (type === 'message') callbacks.onMessage?.(data.content as string)
      else if (type === 'done') callbacks.onDone?.(data.run_id as string, data.task_id as string)
      else if (type === 'error') callbacks.onError?.(data.detail as string)
    }))
    .catch((err) => { if (err.name !== 'AbortError') callbacks.onError?.(String(err)) })

  return () => controller.abort()
}

export async function generateAgentSpec(description: string): Promise<{
  name: string
  system_prompt: string
  capabilities: string[]
}> {
  const res = await fetch(`${BASE}/builder/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description }),
  })
  if (!res.ok) throw new Error(`Generate failed: ${res.status}`)
  return res.json()
}

export async function createAgent(
  name: string,
  system_prompt: string,
  capabilities: string[],
): Promise<AgentSpec> {
  const res = await fetch(`${BASE}/agents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, system_prompt, capabilities }),
  })
  if (!res.ok) throw new Error(`Create agent failed: ${res.status}`)
  return res.json()
}

export async function updateAgent(
  id: string,
  patch: { name?: string; system_prompt?: string; capabilities?: string[] },
): Promise<AgentSpec> {
  const res = await fetch(`${BASE}/agents/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
  if (!res.ok) throw new Error(`Update agent failed: ${res.status}`)
  return res.json()
}

async function parseSseStream(
  res: Response,
  onEvent: (type: string, data: Record<string, unknown>) => void,
): Promise<void> {
  if (!res.ok) {
    const text = await res.text()
    onEvent('error', { detail: `HTTP ${res.status}: ${text}` })
    return
  }
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() ?? ''
    for (const event of events) {
      const lines = event.split('\n')
      const eventLine = lines.find((l) => l.startsWith('event:'))
      const dataLine = lines.find((l) => l.startsWith('data:'))
      if (eventLine && dataLine) {
        const type = eventLine.slice('event:'.length).trim()
        const data = JSON.parse(dataLine.slice('data:'.length).trim())
        onEvent(type, data)
      }
    }
  }
}
