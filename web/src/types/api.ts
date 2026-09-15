/**
 * 后端契约的前端镜像（P1-5-2）。
 *
 * 两条约定由 `tests/test_api_type_contract.py` 在 CI 里强制：
 *
 * 1. **字段集合必须与后端完全相等**：后端会返回而这里缺失（真实漂移）与这里存在
 *    而后端不返回（死字段）都算失败；字段的可空性与枚举取值也必须一致。
 *    `RunResponse.steps` / `observations` 在后端是 JSON dict（OpenAPI 只能描述成
 *    `array<object>`），所以这两个类型由该测试用**真实载荷**比对，而不是 schema。
 * 2. **响应字段一律不写 `?`**：FastAPI 会把模型声明的每个键都下发（没有值就是
 *    `null`），所以"可选"只适用于请求参数与查询参数，不适用于响应；写成可选会让
 *    "字段其实不存在"和"值是 null"看起来一样。
 */

export interface User {
  id: number
  username: string
  role: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface LoginResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  user: User
}

/** `POST /api/v1/incidents/analyze` 的请求体。`top_k` 省略时由服务端配置注入。 */
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

/**
 * 统一工具结果（后端 `schemas/tool.py::ToolResult`）。
 *
 * `data` 在服务端是 `dict[str, Any]` 且默认空字典，**不会**是 `null`；
 * `error_code` 与 `error` 两个键一定存在（失败时才有值）。
 */
export interface ToolResult {
  ok: boolean
  data: Record<string, unknown>
  error_code: string | null
  error: string | null
}

/** 一次工具调用观察（`RunResponse.observations` 的一项）。 */
export interface Observation {
  iteration: number
  tool_name: string
  tool_call_id: string | null
  result: ToolResult
}

/**
 * 运行轨迹里的一步（后端 `services/step_payload.py::STEP_PAYLOAD_FIELDS`）。
 *
 * `step_index` 是 1..N 的持久化序号，`POST /analyze` 与 `GET /runs/{id}` 都会返回
 * 它——P1-5-2 之前 analyze 响应不返回该字段，前端拿它当列表 key 时永远是
 * `undefined`。
 */
export interface AgentStep {
  step_index: number
  iteration: number
  node: string
  action: string
  tool_name: string | null
  tool_call_id: string | null
  /** 只保存长度与计数，绝不含原始日志或 query（P1-1-2）。 */
  arguments_summary: Record<string, unknown> | null
  result_summary: Record<string, unknown> | null
  status: string
  error_code: string | null
  duration_ms: number | null
}

/** 报告里的一条证据（后端 `EvidenceItem`）。 */
export interface EvidenceItem {
  source: 'fault_log' | 'knowledge_base' | 'service_status' | 'tool_error'
  detail: string
  document_id: number | null
  version_id: number | null
  version_number: number | null
  chunk_index: number | null
  filename: string | null
}

/** 服务端核验后剔除、仅用于诊断的证据（后端 `UnverifiedEvidenceItem`）。 */
export interface UnverifiedEvidenceItem {
  source: string
  detail: string
  document_id: number | null
  version_id: number | null
  chunk_index: number | null
}

export interface IncidentReport {
  summary: string
  category: 'database' | 'network' | 'application' | 'dependency' | 'unknown'
  evidence: EvidenceItem[]
  possible_causes: string[]
  troubleshooting_steps: string[]
  references: string[]
  confidence: 'low' | 'medium' | 'high'
  /** 由服务端核验写入，模型不能填（P0-3-2）。 */
  unverified_evidence: UnverifiedEvidenceItem[]
}

export interface DegradedLogSignal {
  type: string
  matched_text: string
  line_number: number | null
}

export interface DegradedKnowledgeBaseSource {
  document_id: number | null
  version_id: number | null
  version_number: number | null
  chunk_index: number | null
  filename: string | null
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
  interrupted: boolean
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

/** `GET /api/v1/runs` 的查询参数；全部可选，所以这里可以用 `?`。 */
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
  degraded_summary: DegradedSummary | null
  interrupted: boolean
}
