import { api } from './client'

export async function checkHealth() {
  const { data } = await api.get<{ status: string; service: string }>('/health')
  return data
}
