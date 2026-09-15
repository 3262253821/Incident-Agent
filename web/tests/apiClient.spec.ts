/**
 * HTTP 客户端与登录态统一的单测（P1-5-4）。
 *
 * 设计文档章节：§13.4 Web UI（登录态）、§13.3 API 状态码。响应拦截器按**HTTP 状态**
 * 与后端统一错误契约的 `error_code` 分流，是 2026-09-15 的 P1-5-4（设计文档只要求
 * "登录态"，没写实现方式）。
 *
 * 为什么这个文件必须存在（而不是只测 `apiErrorMessage()`）：P1-5-4 之前的退出判据
 * 是 `apiErrorMessage(failure).includes('401')`——把**错误文案**当控制流，`apiErrorMessage`
 * 一旦优先返回后端的中文 `detail`（"登录状态无效或已过期"），这条判断就永远不成立。
 * 所以这里测的是**真实的 axios 实例**：拦截器真的挂在 `api` 上、真的按状态码触发
 * 会话失效回调，而不是"某个函数被调用过"。
 *
 * 适配器（adapter）是 axios 的传输层替身：给它返回值就等于"服务端返回了这个响应"，
 * 因此这些用例不碰网络，但走的仍是 axios 真实的 `settle` → 拦截器链。
 */
import { AxiosError, AxiosHeaders } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api, apiErrorMessage, isAuthFailure, onSessionExpired } from '../src/api/client'

/**
 * 后端统一错误契约的真实形状（`app/incident_agent/app_errors.py`）。
 *
 * 三个键一定同时存在：`detail` 给用户看、`error_code` 给程序分流、`request_id` 用于
 * 与日志关联。P1-5-4 的分流读的就是这里的状态码与 `error_code`。
 */
function backendError(status: number, errorCode: string, detail = '登录状态无效或已过期') {
  return { detail, error_code: errorCode, request_id: 'req-test-1' }
}

/**
 * 让 api 实例的下一次请求直接得到这个响应（含 4xx/5xx）。
 *
 * 自定义 adapter 拿到的响应**不会**再经过 `settle()`（那是 adapters 自己的职责），
 * 所以这里显式按 axios 的规则生成 AxiosError——否则一个 401 会被当成功响应返回，
 * 测出来的就不是生产行为。
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

/** 让下一次请求像"连不上服务端"一样失败：没有 response，只有 axios 的错误码。 */
function failWith(code: string, message: string) {
  api.defaults.adapter = async (config) => {
    throw new AxiosError(message, code, config as never)
  }
}

/** 构造 axios 错误（不经过传输层），用于纯函数 `isAuthFailure` 的逐分支验证。 */
function axiosError(options: {
  status?: number
  data?: unknown
  code?: string
  withResponse?: boolean
}) {
  const config = { headers: new AxiosHeaders() } as never
  const response =
    options.withResponse === false
      ? undefined
      : {
          data: options.data,
          status: options.status ?? 401,
          statusText: '',
          headers: {},
          config,
        }
  return new AxiosError('失败', options.code, config, undefined, response as never)
}

let sessionExpired: ReturnType<typeof vi.fn>

beforeEach(() => {
  sessionExpired = vi.fn()
  onSessionExpired(sessionExpired)
  localStorage.clear()
})

afterEach(() => {
  onSessionExpired(null)
  // 不把假适配器留给下一个用例（同一模块实例在整个文件里共享）。
  delete api.defaults.adapter
})

describe('会话失效的唯一判据（isAuthFailure）', () => {
  it('401 是会话失效：真实后端契约的 error_code 为 UNAUTHORIZED', () => {
    expect(
      isAuthFailure(axiosError({ status: 401, data: backendError(401, 'UNAUTHORIZED') })),
    ).toBe(true)
  })

  it('403 也按会话失效处理（后端对 403 同样下发 WWW-Authenticate: Bearer）', () => {
    expect(
      isAuthFailure(axiosError({ status: 403, data: backendError(403, 'FORBIDDEN', '没有权限') })),
    ).toBe(true)
  })

  it('其他状态码不退出：业务错误（404/422/500/503）必须只提示', () => {
    for (const status of [400, 404, 409, 422, 429, 500, 502, 503]) {
      expect(
        isAuthFailure(axiosError({ status, data: backendError(status, 'HTTP_X') })),
        `HTTP ${status} 不该被当成会话失效`,
      ).toBe(false)
    }
  })

  it('请求超时（ECONNABORTED / ETIMEDOUT）不退出', () => {
    expect(isAuthFailure(axiosError({ code: 'ECONNABORTED', withResponse: false }))).toBe(false)
    expect(isAuthFailure(axiosError({ code: 'ETIMEDOUT', withResponse: false }))).toBe(false)
  })

  it('后端不可达（没有 response）不退出', () => {
    expect(isAuthFailure(axiosError({ code: 'ERR_NETWORK', withResponse: false }))).toBe(false)
  })

  it('非 axios 错误不退出', () => {
    expect(isAuthFailure(new Error('需要有效的 Bearer Token'))).toBe(false)
    expect(isAuthFailure('401')).toBe(false)
    expect(isAuthFailure(null)).toBe(false)
  })

  it('状态码是 401 但 error_code 明显是别的语义时不退出（防止误登出）', () => {
    expect(
      isAuthFailure(axiosError({ status: 401, data: backendError(401, 'SOMETHING_ELSE') })),
    ).toBe(false)
  })

  it('状态码不是 401/403 时，即使 error_code 撞上会话失效词也不退出（状态码优先）', () => {
    // 反证 E5 用的就是这个用例：把状态码判断删掉后，这里会从 false 变成 true，
    // 于是一个"上游 503 但错误码恰好是 AUTH_UNAUTHORIZED"的响应会把用户强制登出。
    expect(
      isAuthFailure(axiosError({ status: 503, data: backendError(503, 'AUTH_UNAUTHORIZED') })),
    ).toBe(false)
    expect(
      isAuthFailure(axiosError({ status: 500, data: backendError(500, 'UNAUTHORIZED') })),
    ).toBe(false)
    expect(
      isAuthFailure(axiosError({ status: 404, data: backendError(404, 'FORBIDDEN') })),
    ).toBe(false)
  })

  it('没有 error_code 的 401（网关自己生成的）仍按状态码判定', () => {
    expect(isAuthFailure(axiosError({ status: 401, data: {} }))).toBe(true)
    expect(isAuthFailure(axiosError({ status: 401, data: undefined }))).toBe(true)
  })
})

describe('响应拦截器（真实 axios 实例）', () => {
  it('后端返回 401 时触发会话失效回调，并保留真实错误给调用方', async () => {
    respondWith(401, backendError(401, 'UNAUTHORIZED', '登录状态无效或已过期'))

    const failure = await api.get('/api/v1/auth/me').catch((error) => error)

    expect(failure.response.status).toBe(401)
    expect(sessionExpired).toHaveBeenCalledTimes(1)
    // 保留了后端契约：调用方/界面仍能读到 detail 与 error_code（不是被拦截器吞掉）。
    expect(failure.response.data.error_code).toBe('UNAUTHORIZED')
    expect(failure.response.data.detail).toBe('登录状态无效或已过期')
    expect(apiErrorMessage(failure)).toBe('登录状态无效或已过期')
  })

  it('后端返回 403 时同样触发会话失效回调', async () => {
    respondWith(403, backendError(403, 'FORBIDDEN', '没有权限执行该操作'))

    await expect(api.get('/api/v1/runs')).rejects.toMatchObject({ response: { status: 403 } })

    expect(sessionExpired).toHaveBeenCalledTimes(1)
  })

  it('后端不可达时**不**触发会话失效（网络抖动不能把用户踢下线）', async () => {
    failWith('ERR_NETWORK', 'Network Error')

    await expect(api.get('/api/v1/runs')).rejects.toMatchObject({ code: 'ERR_NETWORK' })

    expect(sessionExpired).not.toHaveBeenCalled()
  })

  it('上游 503（例如 DevAtlas 没起来）不触发会话失效', async () => {
    respondWith(503, backendError(503, 'DEPENDENCY_UNAVAILABLE', '依赖服务暂不可用，请稍后重试'))

    await expect(api.get('/api/v1/runs')).rejects.toMatchObject({ response: { status: 503 } })

    expect(sessionExpired).not.toHaveBeenCalled()
  })

  it('业务性 422 不触发会话失效（字段级提示要靠它继续工作）', async () => {
    respondWith(422, {
      detail: [{ loc: ['body', 'title'], msg: 'field required', type: 'missing' }],
      error_code: 'VALIDATION_ERROR',
      request_id: 'req-test-2',
    })

    await expect(api.post('/api/v1/incidents/analyze', {})).rejects.toMatchObject({
      response: { status: 422 },
    })

    expect(sessionExpired).not.toHaveBeenCalled()
  })

  it('只在拿到 401/403 之后才回调一次（多个接口同时失败不会重复触发）', async () => {
    respondWith(401, backendError(401, 'UNAUTHORIZED'))

    await Promise.allSettled([api.get('/api/v1/runs'), api.get('/api/v1/knowledge-bases')])

    expect(sessionExpired).toHaveBeenCalledTimes(2)
  })
})

describe('apiErrorMessage：按状态码分流，不再靠文案', () => {
  it('后端有 detail 时原样展示（含 401 的中文文案）', () => {
    expect(
      apiErrorMessage(axiosError({ status: 401, data: backendError(401, 'UNAUTHORIZED') })),
    ).toBe('登录状态无效或已过期')
  })

  it('422 的数组 detail 仍然给出字段级提示的兜底文案（P1-5-6 会细化到字段）', () => {
    expect(
      apiErrorMessage(
        axiosError({
          status: 422,
          data: { detail: [{ loc: ['body', 'title'] }], error_code: 'VALIDATION_ERROR' },
        }),
      ),
    ).toBe('请求参数校验失败，请检查输入。')
  })

  it('后端不可达给出可行动的提示，而不是 HTTP 状态码', () => {
    expect(apiErrorMessage(axiosError({ code: 'ERR_NETWORK', withResponse: false }))).toBe(
      '无法连接 Incident Agent API。',
    )
  })

  it('请求超时（有或没有响应）都说超时，而不是说连不上', () => {
    expect(apiErrorMessage(axiosError({ code: 'ECONNABORTED', withResponse: false }))).toBe(
      '请求超时，请检查模型或外部服务状态。',
    )
    expect(
      apiErrorMessage(axiosError({ status: 504, code: 'ECONNABORTED', data: {} })),
    ).toBe('请求超时，请检查模型或外部服务状态。')
  })

  it('没有 detail 的 4xx/5xx 回落到状态码文案', () => {
    expect(apiErrorMessage(axiosError({ status: 500, data: {} }))).toBe('请求失败（HTTP 500）。')
  })

  it('非 axios 错误给出通用文案', () => {
    expect(apiErrorMessage(new Error('boom'))).toBe('发生未知错误，请稍后重试。')
  })
})
