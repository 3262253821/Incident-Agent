import { api } from './client'
import type { RunHistoryPage, RunHistoryQuery, RunResponse } from '../types/api'

/**
 * 历史列表只返回摘要，避免把每条 run 的完整轨迹都传给前端。
 *
 * `paramsSerializer.indexes = null` 让数组参数序列化成重复键
 * （`?status=a&status=b`），而不是 axios 默认的 `status[]=a`——FastAPI 的
 * `Query(list[str])` 只认前一种形状。
 */
export async function listRuns(params: RunHistoryQuery = {}) {
  const { data } = await api.get<RunHistoryPage>('/api/v1/runs', {
    params,
    paramsSerializer: { indexes: null },
  })
  return data
}

/** 打开一条历史记录时才拉取完整轨迹（observations / steps / report）。 */
export async function getRun(runId: string) {
  const { data } = await api.get<RunResponse>(`/api/v1/runs/${runId}`)
  return data
}
