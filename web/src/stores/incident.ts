import { ref } from 'vue'
import { defineStore } from 'pinia'

import { analyzeIncident } from '../api/incidents'
import { apiErrorMessage } from '../api/client'
import { getRun, listRuns } from '../api/runs'
import { explainFailure, fieldErrorHints } from '../utils/apiErrors'
import type { FieldErrorHints, FailureExplanation } from '../utils/apiErrors'
import type { RunHistoryQuery, RunResponse, RunSummary } from '../types/api'

export const useIncidentStore = defineStore('incident', () => {
  const result = ref<RunResponse | null>(null)
  const history = ref<RunSummary[]>([])
  /** 下一页游标；为 null 表示已经到底（P1-3-3 的服务端契约）。 */
  const nextCursor = ref<string | null>(null)
  const running = ref(false)
  const error = ref('')
  /**
   * 422 的字段级提示（P1-5-6）。与整句 `error` 并存：整句给页面顶部的告警区，
   * 字段级提示交给表单贴到对应控件上。
   */
  const fieldErrors = ref<FieldErrorHints>({ fields: {}, general: '' })
  /** 失败大类与建议（P1-5-6）：回答"这次是超时、断连还是上游挂了"。 */
  const failureHint = ref<FailureExplanation>({ summary: '', hint: '' })
  /**
   * 当前这一页历史用的查询参数（P1-5-5）。
   *
   * "加载更多"必须带上**同一组**筛选条件，否则第二页会把被筛掉的记录混进来；
   * 而列表接口只回传游标，所以条件只能由 store 自己记着。
   */
  const historyQuery = ref<RunHistoryQuery>({})

  function resetFailure() {
    fieldErrors.value = { fields: {}, general: '' }
    failureHint.value = { summary: '', hint: '' }
  }

  function rememberFailure(failure: unknown) {
    fieldErrors.value = fieldErrorHints(failure)
    failureHint.value = explainFailure(failure)
  }

  async function analyze(payload: { title: string; content: string; knowledge_base_id: number; top_k: number }) {
    running.value = true
    error.value = ''
    result.value = null
    resetFailure()
    try {
      result.value = await analyzeIncident(payload)
      return result.value
    } catch (failure) {
      error.value = apiErrorMessage(failure)
      rememberFailure(failure)
      throw failure
    } finally {
      running.value = false
    }
  }

  /** 重新加载第一页（打开抽屉、或筛选条件变化时调用）。 */
  async function loadHistory(params: RunHistoryQuery = {}) {
    historyQuery.value = { ...params }
    const page = await listRuns(params)
    history.value = page.items
    nextCursor.value = page.next_cursor
    return history.value
  }

  /** 追加下一页。按 run_id 去重，避免翻页期间的新增记录造成重复行。 */
  async function loadMoreHistory() {
    if (nextCursor.value === null) return history.value

    // 必须带上当前这一页的筛选条件：只传 cursor 的话，第二页会把被筛掉的记录混回来。
    const params: RunHistoryQuery = { ...historyQuery.value, cursor: nextCursor.value }
    const page = await listRuns(params)
    const known = new Set(history.value.map((item) => item.run_id))
    history.value = [
      ...history.value,
      ...page.items.filter((item) => !known.has(item.run_id)),
    ]
    nextCursor.value = page.next_cursor
    return history.value
  }

  /**
   * 列表只有摘要，因此点开一条历史记录必须再拉一次详情，
   * 否则轨迹、报告和降级摘要都会是空的。
   */
  async function selectRun(run: RunSummary) {
    error.value = ''
    resetFailure()
    try {
      result.value = await getRun(run.run_id)
      return result.value
    } catch (failure) {
      error.value = apiErrorMessage(failure)
      rememberFailure(failure)
      throw failure
    }
  }

  return {
    result,
    history,
    nextCursor,
    running,
    error,
    fieldErrors,
    failureHint,
    historyQuery,
    analyze,
    loadHistory,
    loadMoreHistory,
    selectRun,
  }
})
