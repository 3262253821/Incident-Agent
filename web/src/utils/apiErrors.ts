/**
 * 失败信息的结构化解读（P1-5-6）。
 *
 * 这一层存在的理由：后端把"哪一步失败了"表达得很细，而界面前只拿到一句
 * `apiErrorMessage()` 的整句文案——于是"422 到底哪个字段错了""这次是超时、
 * 断连还是上游挂了"都看不出来。这里把两类信息从**真实契约**里取出来：
 *
 * - **422 的字段级错误**：后端 `app_errors` 保留 `detail` 为数组（`loc`/`msg`/`type`），
 *   前端按 `loc` 的最后一个元素映射到表单字段（`title`/`content`/
 *   `knowledge_base_id`/`top_k`），其余落回一句通用提示；
 * - **失败大类**：HTTP 状态码 + axios 错误码。401/403 不在这里处理（会话失效由
 *   响应拦截器统一管，见 `api/client.ts`），这里只回答"这次失败该怎么向用户解释"。
 *
 * 有意不展示后端的英文 `msg`（`Field required`）与 `input`（可能含用户日志原文）：
 * 前者对用户没信息量，后者会把日志回显进错误提示。
 */
import { apiErrorPayload, validationErrors } from '../api/client'
import type { ValidationErrorItem } from '../api/client'
import { RUN_STATUS } from '../constants/status'

/** 表单里能定位到控件的字段。 */
export type FormField = 'title' | 'content' | 'knowledge_base_id' | 'top_k'

/** 字段中文名（与 `IncidentForm.vue` 的标签一致），用于通用文案。 */
export const FIELD_LABELS: Record<FormField, string> = {
  title: '故障标题',
  content: '日志 / 现象',
  knowledge_base_id: '知识库',
  top_k: '召回数量',
}

const FORM_FIELDS: FormField[] = ['title', 'content', 'knowledge_base_id', 'top_k']

/** `loc` 里除了路径前缀（body/query）之外的那个字段名。 */
function fieldFromLocation(loc: unknown[] | undefined): FormField | null {
  if (!Array.isArray(loc)) return null
  for (let index = loc.length - 1; index >= 0; index -= 1) {
    const part = loc[index]
    if (typeof part === 'string' && (FORM_FIELDS as string[]).includes(part)) {
      return part as FormField
    }
  }
  return null
}

/** 错误种类 → 中文短句；未知种类退回字段名 + 通用提示。 */
function describeValidationItem(field: FormField, item: ValidationErrorItem): string {
  switch (item.type) {
    case 'missing':
      return `请填写${FIELD_LABELS[field]}`
    case 'string_too_short':
      return `${FIELD_LABELS[field]}不能为空`
    case 'string_too_long':
      return `${FIELD_LABELS[field]}超出长度上限`
    case 'greater_than':
    case 'greater_than_equal':
      return `${FIELD_LABELS[field]}必须大于 0`
    case 'less_than_equal':
    case 'int_parsing':
      return `${FIELD_LABELS[field]}取值不合法`
    default:
      return `${FIELD_LABELS[field]}不符合要求`
  }
}

export interface FieldErrorHints {
  /** 能定位到具体控件的错误。 */
  fields: Partial<Record<FormField, string>>
  /** 定位不到字段的错误（合并成一句，保证不静默丢失）。 */
  general: string
}

/**
 * 把 422 的 `detail` 数组拆成"字段级提示 + 通用提示"。
 *
 * 同一个字段出现多条错误时**保留第一条**（Pydantic 对同一字段通常是
 * `missing` + 其它，先出现的更接近根因）。
 */
export function fieldErrorHints(error: unknown): FieldErrorHints {
  const hints: FieldErrorHints = { fields: {}, general: '' }
  const items = validationErrors(error)

  for (const item of items) {
    const field = fieldFromLocation(item.loc)
    if (field && !hints.fields[field]) {
      hints.fields[field] = describeValidationItem(field, item)
    }
  }

  if (items.length && !Object.keys(hints.fields).length) {
    hints.general = '请求参数校验失败，请检查输入。'
  }
  return hints
}

export interface FailureExplanation {
  /** 一句"这次是什么失败"。 */
  summary: string
  /** 一句"可以怎么办"；没有建议时为空串。 */
  hint: string
}

/**
 * 按 HTTP 状态码 / axios 错误码给出失败解释。
 *
 * 401/403 刻意**不在**这里：它们意味着会话失效，由响应拦截器统一清会话并跳登录页，
 * 界面不该再用一句"失败原因"盖过去。
 */
export function explainFailure(error: unknown): FailureExplanation {
  const payload = apiErrorPayload(error)
  const status = errorStatus(error)

  if (status === null) {
    return {
      summary: '无法连接分析服务',
      hint: '确认 Agent 服务已启动后重试；你的登录状态不会被清除。',
    }
  }
  if (status === 422) {
    return { summary: '请求参数没有通过服务端校验', hint: '请按字段提示修正后重新提交。' }
  }
  if (status === 503) {
    return {
      summary: '依赖服务暂时不可用',
      hint: '通常是 DevAtlas（鉴权 / 检索）没起来，稍后重试即可。',
    }
  }
  if (status === 502) {
    return { summary: '上游服务返回了错误', hint: '稍后重试；若持续出现请查看服务端日志。' }
  }
  if (status === 429) {
    return { summary: '请求过于频繁', hint: '等待一会儿再提交。' }
  }
  if (status !== null && status >= 500) {
    return { summary: '服务内部错误', hint: '这是服务端问题，可以带上请求编号反馈。' }
  }
  if (status === 404) {
    return { summary: '请求的资源不存在', hint: '刷新页面后重试。' }
  }
  return {
    summary: typeof payload?.detail === 'string' ? payload.detail : '分析失败',
    hint: '',
  }
}

/** 错误上的 HTTP 状态码；连接失败/超时返回 `null`。 */
function errorStatus(error: unknown): number | null {
  const status = (error as { response?: { status?: unknown } })?.response?.status
  return typeof status === 'number' ? status : null
}

/**
 * 失败大类（用于历史抽屉的筛选）。后端只认 `KNOWN_STATUSES` 里的精确值，
 * 而"失败"是五个状态，所以这里映射成一组可重复传的 `status=` 参数。
 */
export const FAILED_STATUSES: string[] = [
  RUN_STATUS.DEGRADED,
  RUN_STATUS.INSUFFICIENT_EVIDENCE,
  RUN_STATUS.REPORT_VALIDATION_FAILED,
  RUN_STATUS.MAX_ITERATIONS,
]

/** 抽屉里的状态筛选档位。 */
export type StatusFilter = 'all' | 'failed' | 'completed' | 'interrupted'

/** 把档位翻译成后端的 `status` 过滤值（`interrupted` 只能切片后再过滤）。 */
export function statusFilterValues(filter: StatusFilter): string[] {
  switch (filter) {
    case 'failed':
      return FAILED_STATUSES
    case 'completed':
      return [RUN_STATUS.COMPLETED]
    default:
      return []
  }
}

/** 时间范围档位（小时）。0 表示不限。 */
export type TimeRangeFilter = 'all' | '24h' | '7d' | '30d'

const TIME_RANGE_HOURS: Record<TimeRangeFilter, number> = {
  all: 0,
  '24h': 24,
  '7d': 24 * 7,
  '30d': 24 * 30,
}

/** 时间档位 → `started_after`（ISO 8601，带时区偏移）。`all` 返回 null。 */
export function startedAfterFor(range: TimeRangeFilter, now: Date = new Date()): string | null {
  const hours = TIME_RANGE_HOURS[range] ?? 0
  if (!hours) return null
  return new Date(now.getTime() - hours * 3_600_000).toISOString()
}

/** 请求参数 → `listRuns` 的查询参数（空值一律不下发，避免 `status=` 这种空值）。 */
export function historyQuery(
  statusFilter: StatusFilter,
  timeRange: TimeRangeFilter,
  now: Date = new Date(),
): { status?: string[]; started_after?: string } {
  const query: { status?: string[]; started_after?: string } = {}
  const statuses = statusFilterValues(statusFilter)
  if (statuses.length) query.status = statuses
  const startedAfter = startedAfterFor(timeRange, now)
  if (startedAfter) query.started_after = startedAfter
  return query
}
