import { api } from './client'
import type { IncidentRequest, RunResponse } from '../types/api'

export async function analyzeIncident(payload: IncidentRequest) {
  const { data } = await api.post<RunResponse>('/api/v1/incidents/analyze', payload)
  return data
}

