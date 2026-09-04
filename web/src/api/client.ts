import axios from 'axios'

export const api = axios.create({
  baseURL: import.meta.env.VITE_AGENT_API_URL || 'http://127.0.0.1:8001',
  timeout: 120_000,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('incident_agent_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

export function apiErrorMessage(error: unknown) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return '请求参数校验失败，请检查输入。'
    if (error.code === 'ECONNABORTED') return '请求超时，请检查模型或外部服务状态。'
    if (!error.response) return '无法连接 Incident Agent API。'
    return `请求失败（HTTP ${error.response.status}）。`
  }
  return '发生未知错误，请稍后重试。'
}
