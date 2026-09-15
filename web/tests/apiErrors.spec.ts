/**
 * 失败信息解读与历史筛选参数的单测（P1-5-5 / P1-5-6）。
 *
 * 设计文档章节：§13.3 API 状态码、§13.3.2 历史分页与过滤、§13.4 Web UI。
 *
 * 这一层是纯函数，所以能把"界面显示什么"钉死而不依赖 DOM。用真实的后端形状当输入：
 * `detail` 数组来自 `app_errors.py` 的 `RequestValidationError` 处理器（`loc`/`msg`/
 * `type`），`status` 过滤值来自 `routers/runs.py` 的 `KNOWN_STATUSES`。
 */
import { AxiosError } from 'axios'
import { describe, expect, it } from 'vitest'

import {
  FAILED_STATUSES,
  explainFailure,
  fieldErrorHints,
  historyQuery,
  startedAfterFor,
  statusFilterValues,
} from '../src/utils/apiErrors'
import { failedSteps, failedTools, failureDetail, failureKind, isFailureStatus } from '../src/utils/failingRun'
import { RUN_STATUS } from '../src/constants/status'
import type { RunResponse, RunSummary } from '../src/types/api'
import { makeRun } from './helpers'

/** 构造一个真实形状的 axios 错误（含后端统一契约的 `detail`/`error_code`）。 */
function apiError(status: number, data: unknown) {
  const config = { headers: {} } as never
  return new AxiosError(
    `Request failed with status code ${status}`,
    status >= 500 ? AxiosError.ERR_BAD_RESPONSE : AxiosError.ERR_BAD_REQUEST,
    config,
    undefined,
    { data, status, statusText: '', headers: {}, config } as never,
  )
}

/** 后端 422 的真实响应体（`detail` 是数组）。 */
function validationError(items: unknown[]) {
  return apiError(422, {
    detail: items,
    error_code: 'VALIDATION_ERROR',
    request_id: 'req-1',
  })
}

describe('422 字段级提示（P1-5-6）', () => {
  it('按 loc 把错误映射到对应字段（标题 / 日志 / 知识库 / 召回数量）', () => {
    const hints = fieldErrorHints(
      validationError([
        { loc: ['body', 'title'], msg: 'String should have at least 1 character', type: 'string_too_short' },
        { loc: ['body', 'knowledge_base_id'], msg: 'Input should be greater than 0', type: 'greater_than' },
      ]),
    )

    expect(hints.fields.title).toBe('故障标题不能为空')
    expect(hints.fields.knowledge_base_id).toBe('知识库必须大于 0')
    expect(hints.general).toBe('')
  })

  it('缺字段（missing）与超长各有自己的文案，而不是一律「参数校验失败」', () => {
    const hints = fieldErrorHints(
      validationError([
        { loc: ['body', 'content'], msg: 'Field required', type: 'missing' },
        { loc: ['body', 'title'], msg: 'String should have at most 200 characters', type: 'string_too_long' },
        { loc: ['body', 'top_k'], msg: 'Input should be less than or equal to 10', type: 'less_than_equal' },
      ]),
    )

    expect(hints.fields.content).toBe('请填写日志 / 现象')
    expect(hints.fields.title).toBe('故障标题超出长度上限')
    expect(hints.fields.top_k).toBe('召回数量取值不合法')
  })

  it('同一字段多条错误只留第一条（先出现的更接近根因）', () => {
    const hints = fieldErrorHints(
      validationError([
        { loc: ['body', 'title'], type: 'missing' },
        { loc: ['body', 'title'], type: 'string_too_short' },
      ]),
    )
    expect(hints.fields.title).toBe('请填写故障标题')
  })

  it('定位不到字段时给一句通用提示，不静默丢失错误', () => {
    const hints = fieldErrorHints(
      validationError([{ loc: ['body'], msg: 'Extra inputs are not permitted', type: 'extra_forbidden' }]),
    )
    expect(hints.fields).toEqual({})
    expect(hints.general).toBe('请求参数校验失败，请检查输入。')
  })

  it('不是 422（例如 401/503/断连）时不产生字段提示', () => {
    expect(fieldErrorHints(apiError(503, { detail: '依赖服务暂不可用', error_code: 'DEPENDENCY_UNAVAILABLE' })).fields).toEqual({})
    expect(fieldErrorHints(apiError(401, { detail: '登录状态无效或已过期', error_code: 'UNAUTHORIZED' })).fields).toEqual({})
    expect(fieldErrorHints(new Error('Network Error')).fields).toEqual({})
    expect(fieldErrorHints(undefined).fields).toEqual({})
  })

  it('detail 是字符串时不算字段错误（后端固定文案那条路径）', () => {
    const hints = fieldErrorHints(apiError(422, { detail: '请求参数校验失败' }))
    expect(hints.fields).toEqual({})
    expect(hints.general).toBe('')
  })
})

describe('失败大类解释（P1-5-6）', () => {
  it('连不上（没有 response）时说"无法连接"，并明确登录状态不会被清', () => {
    const explanation = explainFailure(new Error('Network Error'))
    expect(explanation.summary).toBe('无法连接分析服务')
    expect(explanation.hint).toContain('登录状态不会被清除')
  })

  it('422 / 503 / 502 / 5xx 各有不同解释（不再都是同一句）', () => {
    expect(explainFailure(validationError([])).summary).toBe('请求参数没有通过服务端校验')
    expect(explainFailure(apiError(503, { error_code: 'DEPENDENCY_UNAVAILABLE' })).hint).toContain('DevAtlas')
    expect(explainFailure(apiError(502, { error_code: 'UPSTREAM_ERROR' })).summary).toBe('上游服务返回了错误')
    expect(explainFailure(apiError(500, { error_code: 'AGENT_INTERNAL_ERROR' })).summary).toBe('服务内部错误')
    expect(explainFailure(apiError(429, { error_code: 'RATE_LIMITED' })).summary).toBe('请求过于频繁')
  })

  it('其他 4xx 用后端给的 detail 原文，而不是自己编一句', () => {
    expect(explainFailure(apiError(400, { detail: 'started_after 不能晚于 started_before' })).summary).toBe(
      'started_after 不能晚于 started_before',
    )
    // 404 有自己的固定文案（后端对资源不存在统一用这句，不泄露"是否存在"）。
    expect(explainFailure(apiError(404, { detail: '运行记录不存在' })).summary).toBe('请求的资源不存在')
  })
})

describe('历史筛选参数（P1-5-5）', () => {
  it('"失败"档展开成 KNOWN_STATUSES 里的五个失败状态（completed 不在其中）', () => {
    expect(statusFilterValues('failed')).toEqual(FAILED_STATUSES)
    expect(FAILED_STATUSES).toContain(RUN_STATUS.DEGRADED)
    expect(FAILED_STATUSES).toContain(RUN_STATUS.MAX_ITERATIONS)
    expect(FAILED_STATUSES).not.toContain(RUN_STATUS.COMPLETED)
    expect(statusFilterValues('completed')).toEqual([RUN_STATUS.COMPLETED])
    expect(statusFilterValues('all')).toEqual([])
  })

  it('时间档位换算成 started_after（"不限"不下发参数）', () => {
    const now = new Date('2026-09-15T12:00:00.000Z')
    expect(startedAfterFor('all', now)).toBeNull()
    expect(startedAfterFor('24h', now)).toBe('2026-09-14T12:00:00.000Z')
    expect(startedAfterFor('7d', now)).toBe('2026-09-08T12:00:00.000Z')
    expect(startedAfterFor('30d', now)).toBe('2026-08-16T12:00:00.000Z')
  })

  it('historyQuery 只带非空条件（空数组不能变成 `status=` 这种空参数）', () => {
    const now = new Date('2026-09-15T12:00:00.000Z')
    expect(historyQuery('all', 'all', now)).toEqual({})
    expect(historyQuery('failed', 'all', now)).toEqual({ status: FAILED_STATUSES })
    expect(historyQuery('all', '24h', now)).toEqual({ started_after: '2026-09-14T12:00:00.000Z' })
    expect(historyQuery('completed', '7d', now)).toEqual({
      status: [RUN_STATUS.COMPLETED],
      started_after: '2026-09-08T12:00:00.000Z',
    })
  })
})

describe('失败状态细分（P1-5-5）', () => {
  it('每个状态给出各自的"哪种失败"，被中断优先于服务端的 degraded', () => {
    expect(failureKind(makeRun({ status: 'degraded' }))).toBe('工具执行失败')
    expect(failureKind(makeRun({ status: 'degraded', interrupted: true }))).toBe('已中断')
    expect(failureKind(makeRun({ status: 'report_validation_failed' }))).toBe('报告未通过校验')
    expect(failureKind(makeRun({ status: 'max_iterations' }))).toBe('达到循环上限')
    expect(failureKind(makeRun({ status: 'insufficient_evidence' }))).toBe('证据不足')
    expect(failureKind(makeRun({ status: 'running' }))).toBe('未结束（可能已被回收）')
    expect(failureKind(makeRun({ status: 'completed' }))).toBe('成功')
    expect(failureKind(makeRun({ status: 'something_new' }))).toBe('其他失败')
  })

  it('失败明细只用摘要里真实有的字段', () => {
    expect(failureDetail(makeRun({ status: 'max_iterations', iteration: 6, max_iterations: 6 }))).toContain('6/6')
    expect(failureDetail(makeRun({ status: 'report_validation_failed' }))).toContain('未通过校验')
    expect(
      failureDetail(makeRun({ status: 'degraded', interrupted: true })),
    ).toContain('进程在分析结束前退出')
    // 成功的一条不该编出失败原因。
    expect(failureDetail(makeRun({ status: 'completed' }))).toBe('')
  })

  it('"失败"归属与后端过滤值一致：running 与 completed 都不算失败', () => {
    expect(isFailureStatus(makeRun({ status: 'completed' }))).toBe(false)
    expect(isFailureStatus(makeRun({ status: 'running' }))).toBe(false)
    expect(isFailureStatus(makeRun({ status: 'degraded' }))).toBe(true)
    // 服务端把被回收的运行写成 degraded，所以"完成"与"被中断"不会同时出现。
    expect(isFailureStatus(makeRun({ status: 'degraded', interrupted: true }))).toBe(true)
  })

  it('失败工具与失败步骤只有打开详情后才拿得到（列表拿不到就返回空）', () => {
    expect(failedTools(null)).toEqual([])
    const detail = {
      degraded_summary: { failed_tools: ['search_knowledge'], successful_tools: [] },
      steps: [
        { step_index: 1, error_code: null },
        { step_index: 2, error_code: 'RAG_TIMEOUT' },
        { step_index: 3, error_code: 'INVALID_TOOL_RESULT' },
      ],
    } as unknown as RunResponse
    expect(failedTools(detail)).toEqual(['search_knowledge'])
    expect(failedSteps(detail)).toEqual([
      { step_index: 2, error_code: 'RAG_TIMEOUT' },
      { step_index: 3, error_code: 'INVALID_TOOL_RESULT' },
    ])
  })
})
