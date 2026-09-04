export interface User {
  id: number
  username: string
  role: string
  is_active: boolean
}

export interface LoginResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: User
}

export interface IncidentRequest {
  title: string
  content: string
  knowledge_base_id: number
  top_k: number
}

export interface Observation {
  iteration: number
  tool_name: string
  tool_call_id: string | null
  result: {
    ok: boolean
    data?: Record<string, unknown>
    error_code?: string | null
    error?: string | null
  }
}

export interface AgentStep {
  step_index?: number
  iteration: number
  node: string
  action: string
  tool_name?: string | null
  status: string
  ok?: boolean
  error_code?: string | null
}

export interface IncidentReport {
  summary: string
  category: string
  evidence: Array<{
    source: string
    detail: string
    filename?: string | null
    document_id?: number | null
    version_id?: number | null
    chunk_index?: number | null
  }>
  possible_causes: string[]
  troubleshooting_steps: string[]
  references: string[]
  confidence: string
}

export interface RunResponse {
  run_id: string
  status: string
  report: IncidentReport | null
  observations: Observation[]
  steps: AgentStep[]
  error: string | null
}
