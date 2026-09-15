import { api } from './client'
import type { RunResponse, RunSummary } from '../types/api'

/** 历史列表只返回摘要，避免把每条 run 的完整轨迹都传给前端。 */
export async function listRuns() {
  const { data } = await api.get<RunSummary[]>('/api/v1/runs')
  return data
}

/** 打开一条历史记录时才拉取完整轨迹（observations / steps / report）。 */
export async function getRun(runId: string) {
  const { data } = await api.get<RunResponse>(`/api/v1/runs/${runId}`)
  return data
}
