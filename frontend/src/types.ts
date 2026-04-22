export interface AgentSpec {
  id: string
  name: string
  system_prompt: string
  allowed_tools: string[]
  max_turns: number
  status: string
  icon: string
  entity_type_scope: string[]
}

export interface Task {
  id: string
  spec_id: string
  title: string
  status: string
  session_count: number
  entity_count: number
  outcome_summary: string | null
}

export interface Message {
  id: string
  role: 'user' | 'agent'
  content: string
  timestamp: string
  tool_calls?: Array<{ id: string; tool: string; args: Record<string, unknown> }>
}

export interface Entity {
  id: string
  type: string
  name: string
  properties: Record<string, unknown>
  source_refs: unknown[]
  created_in_run_id: string | null
}

export interface Edge {
  id: string
  src: string
  dst: string
  type: string
  derived: boolean
}

export interface Run {
  id: string
  spec_id: string
  task_id: string | null
  status: string
  started_at: string
  ended_at: string | null
  tool_call_count: number
  entity_count: number
}

export interface EntityType {
  name: string
  canonical_key: string | null
  description: string | null
}

export interface EdgeType {
  name: string
  is_transitive: boolean
  is_inverse_of: string | null
  domain: string | null
  range: string | null
}

export interface OntologyEvent {
  id: string
  event_type: string
  actor: string
  run_id: string
  entity_name: string | null
  payload: Record<string, unknown>
  created_at: string
}

export interface BlockingCondition {
  edge_type: string
  target_type: string | null
  blocking_target_states: Record<string, string[]>
  message_template: string
}

export interface Policy {
  id: string
  name: string
  tool_pattern: string
  subject_key: string
  subject_type: string
  blocking_conditions: BlockingCondition[]
  enabled: boolean
  created_at: string
}
