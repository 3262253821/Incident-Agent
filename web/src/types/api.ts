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

/**
 * `GET /api/v1/knowledge-bases` 返回的一条可选知识库。
 *
 * Agent 代理 DevAtlas 的列表接口，只下发 `id`/`name`/`description`：`owner_id`
 * 与时间戳属于 DevAtlas 的内部字段，不进浏览器契约。
 */
export interface KnowledgeBaseOption {
  id: number
  name: string
  description: string | null
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

export interface DegradedLogSignal {
  type: string
  matched_text: string
  line_number?: number | null
}

export interface DegradedKnowledgeBaseSource {
  document_id?: number | null
  version_id?: number | null
  version_number?: number | null
  chunk_index?: number | null
  filename?: string | null
}

export interface DegradedSummary {
  reason: string
  text: string
  failed_tools: string[]
  successful_tools: string[]
  log_signals: DegradedLogSignal[]
  knowledge_base_sources: DegradedKnowledgeBaseSource[]
  service_statuses: string[]
  suggestions: string[]
}

/**
 * Lightweight row returned by `GET /api/v1/runs`.
 *
 * The list endpoint deliberately omits `observations`, `steps`, `report` and
 * `degraded_summary`: those only arrive through `GET /api/v1/runs/{run_id}` when
 * a row is opened.
 */
export interface RunSummary {
  run_id: string
  title: string
  status: string
  knowledge_base_id: number
  iteration: number
  max_iterations: number
  steps_count: number
  observations_count: number
  interrupted?: boolean
  error: string | null
  started_at: string | null
  completed_at: string | null
  /** 服务端派生的分析耗时；未结束或已被回收的中断运行是 null。 */
  duration_ms: number | null
}

/**
 * 历史列表的一页（P1-3-3）。
 *
 * `next_cursor` 是服务端给的不透明游标：为 null 表示没有更多记录。用游标而不是
 * offset，是因为历史是"不断新增"的列表，翻页期间新增一条 run 会让 offset 分页
 * 重复或漏掉记录。
 */
export interface RunHistoryPage {
  items: RunSummary[]
  next_cursor: string | null
}

export interface RunHistoryQuery {
  limit?: number
  /** 可重复传：`?status=degraded&status=max_iterations`。 */
  status?: string[]
  /** 包含边界（>=），ISO 8601。 */
  started_after?: string
  /** 不包含边界（<），ISO 8601。 */
  started_before?: string
  cursor?: string
}

export interface RunResponse {
  run_id: string
  title: string
  status: string
  started_at: string | null
  completed_at: string | null
  duration_ms: number | null
  report: IncidentReport | null
  observations: Observation[]
  steps: AgentStep[]
  error: string | null
  degraded_summary?: DegradedSummary | null
  interrupted?: boolean
}
