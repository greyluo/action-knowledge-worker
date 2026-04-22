import type { AgentSpec, Entity, Edge, Run, OntologyEvent, Task, Message, EntityType, EdgeType, Policy, BlockingCondition } from './types'

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

export async function deleteAgent(id: string): Promise<void> {
  const res = await fetch(`${BASE}/agents/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Delete agent failed: ${res.status}`)
}

export async function deleteTask(id: string): Promise<void> {
  const res = await fetch(`${BASE}/tasks/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Delete task failed: ${res.status}`)
}

export async function createEntityType(name: string, canonical_key?: string, description?: string): Promise<EntityType> {
  const res = await fetch(`${BASE}/schema/entity-types`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, canonical_key: canonical_key || null, description: description || null }),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Create entity type failed: ${res.status} ${text}`)
  }
  return res.json()
}

export async function createEntity(type_name: string, properties: Record<string, unknown>): Promise<Entity> {
  const res = await fetch(`${BASE}/entities`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ type_name, properties }),
  })
  if (!res.ok) throw new Error(`Create entity failed: ${res.status}`)
  return res.json()
}

export async function updateEntityProps(id: string, properties: Record<string, unknown>): Promise<Entity> {
  const res = await fetch(`${BASE}/entities/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ properties }),
  })
  if (!res.ok) throw new Error(`Update entity failed: ${res.status}`)
  return res.json()
}

export async function deleteEntity(id: string): Promise<void> {
  const res = await fetch(`${BASE}/entities/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Delete entity failed: ${res.status}`)
}

export async function createEdgeApi(src_id: string, dst_id: string, edge_type_name: string): Promise<Edge> {
  const res = await fetch(`${BASE}/edges`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ src_id, dst_id, edge_type_name }),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Create edge failed: ${res.status} ${text}`)
  }
  return res.json()
}

export async function deleteEdge(id: string): Promise<void> {
  const res = await fetch(`${BASE}/edges/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Delete edge failed: ${res.status}`)
}

export const getPolicies = (): Promise<Policy[]> => get('/policies')

export async function createPolicy(data: {
  name: string
  tool_pattern: string
  subject_key: string
  subject_type: string
  blocking_conditions: BlockingCondition[]
}): Promise<Policy> {
  const res = await fetch(`${BASE}/policies`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error(`Create policy failed: ${res.status}`)
  return res.json()
}

export async function togglePolicy(id: string, enabled: boolean): Promise<Policy> {
  const res = await fetch(`${BASE}/policies/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  })
  if (!res.ok) throw new Error(`Update policy failed: ${res.status}`)
  return res.json()
}

export async function deletePolicy(id: string): Promise<void> {
  const res = await fetch(`${BASE}/policies/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Delete policy failed: ${res.status}`)
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
