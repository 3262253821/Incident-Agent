import { api } from './client'
import type { KnowledgeBaseOption } from '../types/api'

/**
 * 加载当前账号可选的知识库（前端下拉的数据源）。
 *
 * 浏览器不直连 DevAtlas：前端在 5174、DevAtlas 在 8000，直连需要给对方加 CORS。
 * 这里走 Agent 的只读代理端点，Token 由请求拦截器带上，DevAtlas 依旧按 Token 的
 * owner 过滤，Agent 只做转发与契约收窄。
 */
export async function listKnowledgeBases() {
  const { data } = await api.get<KnowledgeBaseOption[]>('/api/v1/knowledge-bases')
  return data
}
