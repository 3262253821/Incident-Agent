import { ref } from 'vue'
import { defineStore } from 'pinia'

import { analyzeIncident } from '../api/incidents'
import { apiErrorMessage } from '../api/client'
import { listRuns } from '../api/runs'
import type { RunResponse } from '../types/api'

export const useIncidentStore = defineStore('incident', () => {
  const result = ref<RunResponse | null>(null)
  const history = ref<RunResponse[]>([])
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

  function selectRun(run: RunResponse) { result.value = run }

  return { result, history, running, error, analyze, loadHistory, selectRun }
})
