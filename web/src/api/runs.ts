import { api } from './client'
import type { RunResponse } from '../types/api'

export async function listRuns() {
  const { data } = await api.get<RunResponse[]>('/api/v1/runs')
  return data
}
