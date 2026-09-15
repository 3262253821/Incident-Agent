import { ref } from 'vue'
import { defineStore } from 'pinia'

import { analyzeIncident } from '../api/incidents'
import { apiErrorMessage } from '../api/client'
import { getRun, listRuns } from '../api/runs'
import type { RunResponse, RunSummary } from '../types/api'

export const useIncidentStore = defineStore('incident', () => {
  const result = ref<RunResponse | null>(null)
  const history = ref<RunSummary[]>([])
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

  async function loadHistory() {
    history.value = await listRuns()
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

  return { result, history, running, error, analyze, loadHistory, selectRun }
})
