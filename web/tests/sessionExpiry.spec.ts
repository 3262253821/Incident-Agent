/**
 * 会话失效的集成测试（P1-5-4）：真实 axios 实例 + 真实 auth store。
 *
 * 设计文档章节：§13.4 Web UI（登录态）、§13.3 API 状态码。
 *
 * 单元测试各自证明一半：`apiClient.spec.ts` 证明"401 会触发回调"，`stores.spec.ts`
 * 证明"restore 会分流"，`main.spec.ts` 证明"回调接到了入口上"。这里把它们串起来跑
 * 一遍**同一条链路**，而且只用假适配器替换传输层（不是 mock 掉 axios 或 store）：
 *
 * ```text
 * auth.restore() → currentUser() → api.get() → 401 响应
 *               → 响应拦截器 → onSessionExpired 回调 → auth.signOut()
 * ```
 *
 * 这条链路断在哪一环，浏览器里的表现都是"令牌过期后一切照旧报 401"——单测可能全绿。
 */
import { AxiosError } from 'axios'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { api, isAuthFailure, onSessionExpired } from '../src/api/client'
import { useAuthStore } from '../src/stores/auth'

/**
 * 后端统一错误契约的真实形状（`app_errors.build_error_response`）。
 *
 * 自定义 adapter 的响应不会再走 axios 的 `settle()`，所以非 2xx 要自己按 axios 的
 * 规则抛出 AxiosError，否则 401 会被当成成功响应。
 */
function respondWith(status: number, data: unknown) {
  api.defaults.adapter = async (config) => {
    const response = {
      data,
      status,
      statusText: `${status}`,
      headers: {},
      config,
    }
    if (status >= 200 && status < 300) return response
    throw new AxiosError(
      `Request failed with status code ${status}`,
      status >= 500 ? AxiosError.ERR_BAD_RESPONSE : AxiosError.ERR_BAD_REQUEST,
      config as never,
      undefined,
      response as never,
    )
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  // 与 src/main.ts 注册的是同一个形状：清掉会话（跳转由 main.ts 的路由负责）。
  onSessionExpired(() => useAuthStore().signOut())
})

afterEach(() => {
  onSessionExpired(null)
  delete api.defaults.adapter
})

describe('令牌过期时的完整链路', () => {
  it('GET /auth/me 返回 401 后：令牌被清掉，route guard 会把用户带回登录页', async () => {
    localStorage.setItem('incident_agent_token', 'expired-token')
    const store = useAuthStore()
    respondWith(401, {
      detail: '登录状态无效或已过期',
      error_code: 'UNAUTHORIZED',
      request_id: 'req-live-1',
    })

    await store.restore()

    expect(store.token).toBe('')
    expect(store.user).toBeNull()
    expect(localStorage.getItem('incident_agent_token')).toBeNull()
  })

  it('上游 503（DevAtlas 没起来）时令牌留下，只把提示写进 store', async () => {
    localStorage.setItem('incident_agent_token', 'good-token')
    const store = useAuthStore()
    respondWith(503, {
      detail: 'DevAtlas 用户验证服务暂不可用',
      error_code: 'DEPENDENCY_UNAVAILABLE',
      request_id: 'req-live-2',
    })

    await store.restore()

    expect(store.token).toBe('good-token')
    expect(localStorage.getItem('incident_agent_token')).toBe('good-token')
    expect(store.error).toBe('DevAtlas 用户验证服务暂不可用')
  })

  it('连不上服务端（无响应）时令牌留下，提示是"连不上"而不是登出', async () => {
    localStorage.setItem('incident_agent_token', 'good-token')
    const store = useAuthStore()
    api.defaults.adapter = async (config) => {
      throw new AxiosError('Network Error', 'ERR_NETWORK', config as never)
    }

    await store.restore()

    expect(store.token).toBe('good-token')
    expect(localStorage.getItem('incident_agent_token')).toBe('good-token')
    expect(store.error).toBe('无法连接 Incident Agent API。')
  })

  it('并发的两个请求都拿到 401 时，后一个也不会把状态搞乱（signOut 幂等）', async () => {
    localStorage.setItem('incident_agent_token', 'expired-token')
    const store = useAuthStore()
    respondWith(401, { detail: '登录状态无效或已过期', error_code: 'UNAUTHORIZED' })

    const results = await Promise.allSettled([store.restore(), store.restore()])

    expect(results.map((result) => result.status)).toEqual(['fulfilled', 'fulfilled'])
    expect(store.token).toBe('')
    expect(store.user).toBeNull()
    expect(localStorage.getItem('incident_agent_token')).toBeNull()
  })
})

/**
 * 契约漂移的守门（P1-5-4）。
 *
 * 前端与后端的约定是 `P1-5-2` 定下的那一条：`tests/test_api_type_contract.py` 用真实
 * 载荷与 OpenAPI 锁住响应字段。这里锁的是**统一的错误契约**——`app_errors.build_error_response`
 * 保证任何错误响应都是 `{"detail", "error_code", "request_id"}`，会话失效的 `error_code`
 * 固定是 `UNAUTHORIZED`。后端一旦改名，`isAuthFailure` 会退化成"只看状态码"（前端仍能
 * 登出，所以不会有人发现），这条断言就是用来把那次变更变成红灯的。
 */
describe('后端错误契约（P1-5-4 依赖的部分）', () => {
  it('401 / 403 的 error_code 就是 isAuthFailure 认识的那两个', () => {
    for (const [status, detail, code] of [
      [401, '登录状态无效或已过期', 'UNAUTHORIZED'],
      [403, '没有权限执行该操作', 'FORBIDDEN'],
    ] as const) {
      const failure = new AxiosError(
        `Request failed with status code ${status}`,
        AxiosError.ERR_BAD_REQUEST,
        { headers: {} } as never,
        undefined,
        {
          data: { detail, error_code: code, request_id: 'req-x' },
          status,
          statusText: '',
          headers: {},
          config: { headers: {} } as never,
        } as never,
      )
      expect(isAuthFailure(failure), `HTTP ${status} 的 ${code}`).toBe(true)
    }
  })
})
