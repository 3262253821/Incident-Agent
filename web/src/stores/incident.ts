import { ref } from 'vue'
import { defineStore } from 'pinia'

import { analyzeIncident } from '../api/incidents'
import { apiErrorMessage } from '../api/client'
import { getRun, listRuns } from '../api/runs'
import type { RunHistoryQuery, RunResponse, RunSummary } from '../types/api'

export const useIncidentStore = defineStore('incident', () => {
  const result = ref<RunResponse | null>(null)
  const history = ref<RunSummary[]>([])
  /** 下一页游标；为 null 表示已经到底（P1-3-3 的服务端契约）。 */
  const nextCursor = ref<string | null>(null)
  const running = ref(false)
  const error = ref('')

  async function analyze(payload: { title: string; content: string; knowledge_base_id: number; top_k: number }) {
    running.value = true
    error.value = ''
    result.value = null
    try {
      result.value = await analyzeIncident(payload)
      return result.value
    } catch (failure) {
      error.value = apiErrorMessage(failure)
      throw failure
    } finally {
      running.value = false
    }
  }

  /** 重新加载第一页（打开抽屉、或筛选条件变化时调用）。 */
  async function loadHistory(params: RunHistoryQuery = {}) {
    const page = await listRuns(params)
    history.value = page.items
    nextCursor.value = page.next_cursor
    return history.value
  }

  /** 追加下一页。按 run_id 去重，避免翻页期间的新增记录造成重复行。 */
  async function loadMoreHistory() {
    if (!nextCursor.value) return history.value

    const page = await listRuns({ cursor: nextCursor.value })
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
    try {
      result.value = await getRun(run.run_id)
      return result.value
    } catch (failure) {
      error.value = apiErrorMessage(failure)
      throw failure
    }
  }

  return {
    result,
    history,
    nextCursor,
    running,
    error,
    analyze,
    loadHistory,
    loadMoreHistory,
    selectRun,
  }
})
