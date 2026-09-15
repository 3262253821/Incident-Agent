/**
 * HTTP 客户端：请求带 Token，响应按**状态码**分流（P1-5-4）。
 *
 * P1-5-4 之前只有请求拦截器，退出判据散落在视图里，而且是把**错误文案**当控制流：
 *
 * ```ts
 * if (apiErrorMessage(failure).includes('401')) auth.signOut()
 * ```
 *
 * 后端统一错误契约（`app/incident_agent/app_errors.py`）会把 `detail` 写成中文文案
 * （"登录状态无效或已过期"），所以这条 `includes('401')` 在真实响应上**根本不会命中**；
 * 更糟的是它把文案当接口——后端改一句话，登出就静默失效。
 *
 * 现在只有一条判据：**HTTP 状态码在不在 `{401, 403}` 里**（`isAuthFailure`），
 * 由响应拦截器统一触发 `onSessionExpired` 注册进来的处理函数（见 `src/main.ts`：
 * 清会话 + 带 `redirect` 跳登录页）。
 *
 * 关键区别：
 *
 * - **后端不可达**（没有 `response`，例如 `ERR_NETWORK`）与**请求超时**
 *   （`ECONNABORTED`/`ETIMEDOUT`）**都不清 Token**——网络抖动不该把人踢下线；
 * - 上游 5xx（DevAtlas 没起来 → Agent 返回 503）同理，只提示；
 * - 错误仍然原样抛给调用方（`detail`/`error_code` 都还在），所以界面提示、
 *   字段级校验、只读降级展示都不受影响。
 */
import axios from 'axios'
import type { AxiosError } from 'axios'

/** 本地保存令牌的键。请求拦截器、auth store 与路由守卫共用同一个键。 */
export const TOKEN_STORAGE_KEY = 'incident_agent_token'

/** 后端统一错误契约里出现的 HTTP 状态码 → 会话失效（`app_errors.STATUS_ERROR_CODES`）。 */
const SESSION_FAILURE_STATUSES = [401, 403] as const

/**
 * 会话失效时后端会给出的 `error_code`（`app_errors.STATUS_ERROR_CODES` 的 401/403，
 * 以及知识库代理把上游 401/403 归一化成的 `AUTH_UNAUTHORIZED`）。
 *
 * 只在**响应里带了** `error_code` 时用它交叉核对：状态码对但业务码明显是别的语义
 * （后端将来新增一个"401 但含义不同"的错误）时不要误登出。没有 `error_code` 的响应
 * （例如网关自己生成的 401）仍按状态码判定。
 */
const SESSION_FAILURE_CODES = ['UNAUTHORIZED', 'FORBIDDEN', 'AUTH_UNAUTHORIZED'] as const

/** 后端统一错误响应体（`detail` 可能是字符串，也可能是 422 的字段错误数组）。 */
export interface ApiErrorPayload {
  detail?: string | unknown[]
  error_code?: string
  request_id?: string
}

/**
 * 会话失效处理函数：清掉本地会话并带 `redirect` 跳登录页。
 *
 * 由 `src/main.ts` 在启动时注册。这里不 import router / store 是**有意的**：
 * `client.ts` 被每个 api 模块与 store 引用，反向 import 会把模块依赖拧成环
 * （router → views → stores → api → client → router），环在打包时不会报错、
 * 只在某个入口下变成运行时 `undefined`。
 */
export type SessionExpiredHandler = (error: unknown) => void

let sessionExpiredHandler: SessionExpiredHandler | null = null

/** 注册/替换会话失效处理函数；传 `null` 可解除（测试用）。 */
export function onSessionExpired(handler: SessionExpiredHandler | null) {
  sessionExpiredHandler = handler
}

export const api = axios.create({
  baseURL: import.meta.env.VITE_AGENT_API_URL || 'http://127.0.0.1:8001',
  timeout: 120_000,
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_STORAGE_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

/**
 * 这个错误是不是"登录态已失效"？
 *
 * 只看 `response.status`（会话失效一定伴随一个 HTTP 响应），并用后端统一契约的
 * `error_code` 交叉核对。**没有 response 的错误一律不是**：那说明请求没到服务端
 * （连不上/超时），此时清 Token 会让网络抖动变成强制登出。
 */
export function isAuthFailure(error: unknown): error is AxiosError<ApiErrorPayload> {
  if (!axios.isAxiosError(error)) return false
  const status = error.response?.status
  if (typeof status !== 'number') return false
  if (!(SESSION_FAILURE_STATUSES as readonly number[]).includes(status)) return false

  const code = error.response?.data?.error_code
  if (typeof code !== 'string') return true
  return (SESSION_FAILURE_CODES as readonly string[]).includes(code)
}

api.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    // 判据是 HTTP 状态码（+ error_code 交叉核对）；其余错误（含"连不上"）原样抛出。
    if (isAuthFailure(error)) {
      try {
        sessionExpiredHandler?.(error)
      } catch (failure) {
        // 清理/跳转失败不能吞掉原始错误——调用方仍需要看到 401 本身。
        console.error('[api] 会话失效处理失败', failure)
      }
    }
    return Promise.reject(error)
  },
)

/** 把任意异常转成给用户看的文案（字段级 422 的细化属 P1-5-6）。 */
export function apiErrorMessage(error: unknown) {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as ApiErrorPayload | undefined)?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return '请求参数校验失败，请检查输入。'
    if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
      return '请求超时，请检查模型或外部服务状态。'
    }
    if (!error.response) return '无法连接 Incident Agent API。'
    return `请求失败（HTTP ${error.response.status}）。`
  }
  return '发生未知错误，请稍后重试。'
}
