/**
 * Pinia store 的单测（P1-5-3）。
 *
 * 设计文档章节：§13.4 Web UI（登录态、运行中状态、运行历史）、§13.3.2 历史分页
 * （游标与"是否还有下一页"）；组件与 store 的自动化测试本身是 P1-5-3，设计文档未涉及。
 *
 * 覆盖的是**有真实分支、且只有靠组件才能触发**的那部分逻辑：分页去重、游标到底后
 * 不再请求、详情加载与错误落库。API 模块被 mock 掉——这里验证的是 store 的状态
 * 迁移，不是 axios 的序列化（后者属于后端契约测试）。
 *
 * P1-5-4 起 `restore()` 的失败分支按"是不是认证失败"分流：401/403 交给会话失效
 * 回调（响应拦截器，见 `apiClient.spec.ts`），**网络故障只提示、保留 Token**。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useAuthStore } from '../src/stores/auth'
import { useIncidentStore } from '../src/stores/incident'
import { makeRun } from './helpers'

vi.mock('../src/api/incidents', () => ({ analyzeIncident: vi.fn() }))
vi.mock('../src/api/runs', () => ({ getRun: vi.fn(), listRuns: vi.fn() }))
vi.mock('../src/api/auth', () => ({ currentUser: vi.fn(), login: vi.fn() }))
vi.mock('../src/api/client', () => ({
  TOKEN_STORAGE_KEY: 'incident_agent_token',
  apiErrorMessage: (error: unknown) =>
    error instanceof Error ? error.message : '发生未知错误，请稍后重试。',
  // 与生产同一条判据：`response.status` 才是 HTTP 状态（见 apiClient.spec.ts）。
  isAuthFailure: (error: unknown) =>
    [401, 403].includes((error as { response?: { status?: number } })?.response?.status ?? 0),
  onSessionExpired: vi.fn(),
}))

const { analyzeIncident } = await import('../src/api/incidents')
const { getRun, listRuns } = await import('../src/api/runs')
const { currentUser } = await import('../src/api/auth')
const { onSessionExpired } = await import('../src/api/client')

/** 模拟真实 axios 错误的最小形状：`response.status` 才是 HTTP 状态。 */
function httpError(status: number, message: string) {
  return Object.assign(new Error(message), { response: { status } })
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('incident store', () => {
  it('分析成功时把结果写进 state，并在结束时清掉 running', async () => {
    const detail = { run_id: 'run-1', steps: [], observations: [] }
    vi.mocked(analyzeIncident).mockResolvedValue(detail as never)

    const store = useIncidentStore()
    const promise = store.analyze({
      title: 't',
      content: 'c',
      knowledge_base_id: 4,
      top_k: 5,
    })

    // 请求还没回来时界面必须处于 running（加载态与禁用提交按钮都依赖它）。
    expect(store.running).toBe(true)
    await promise
    expect(store.running).toBe(false)
    expect(store.result).toEqual(detail)
    expect(store.error).toBe('')
  })

  it('分析失败时把错误文案写进 state，并照旧抛出（会话失效由拦截器统一处理，不靠文案）', async () => {
    vi.mocked(analyzeIncident).mockRejectedValue(new Error('需要有效的 Bearer Token'))

    const store = useIncidentStore()
    await expect(
      store.analyze({ title: 't', content: 'c', knowledge_base_id: 4, top_k: 5 }),
    ).rejects.toThrow('需要有效的 Bearer Token')
    expect(store.error).toBe('需要有效的 Bearer Token')
    expect(store.running).toBe(false)
    expect(store.result).toBeNull()
  })

  it('重新加载第一页会整体替换列表与游标（不是追加）', async () => {
    vi.mocked(listRuns).mockResolvedValue({
      items: [makeRun({ run_id: 'a' })],
      next_cursor: 'cursor-1',
    } as never)

    const store = useIncidentStore()
    await store.loadHistory()
    expect(store.history.map((item) => item.run_id)).toEqual(['a'])
    expect(store.nextCursor).toBe('cursor-1')

    vi.mocked(listRuns).mockResolvedValue({
      items: [makeRun({ run_id: 'b' })],
      next_cursor: null,
    } as never)
    await store.loadHistory()
    expect(store.history.map((item) => item.run_id)).toEqual(['b'])
    expect(store.nextCursor).toBeNull()
  })

  it('加载更多时带上游标，并在翻页期间新增记录的情况下按 run_id 去重', async () => {
    const store = useIncidentStore()
    store.history = [makeRun({ run_id: 'a' }), makeRun({ run_id: 'b' })]
    store.nextCursor = 'cursor-1'

    vi.mocked(listRuns).mockResolvedValue({
      // 第二页里混进一条已经在列表里的 run（翻页期间有新运行写入时会这样）。
      items: [makeRun({ run_id: 'b' }), makeRun({ run_id: 'c' })],
      next_cursor: null,
    } as never)

    await store.loadMoreHistory()

    expect(listRuns).toHaveBeenCalledWith({ cursor: 'cursor-1' })
    expect(store.history.map((item) => item.run_id)).toEqual(['a', 'b', 'c'])
    expect(store.nextCursor).toBeNull()
  })

  it('已经到底（next_cursor 为 null）时不再发请求', async () => {
    const store = useIncidentStore()
    store.history = [makeRun({ run_id: 'a' })]
    store.nextCursor = null

    await store.loadMoreHistory()

    expect(listRuns).not.toHaveBeenCalled()
  })

  it('点开一条历史记录时拉详情；失败时把错误写进 state 并抛出', async () => {
    vi.mocked(getRun).mockResolvedValue({ run_id: 'a', steps: [] } as never)
    const store = useIncidentStore()
    await store.selectRun(makeRun({ run_id: 'a' }))
    expect(getRun).toHaveBeenCalledWith('a')
    expect(store.result).toEqual({ run_id: 'a', steps: [] })

    vi.mocked(getRun).mockRejectedValue(new Error('运行记录不存在'))
    await expect(store.selectRun(makeRun({ run_id: 'a' }))).rejects.toThrow('运行记录不存在')
    expect(store.error).toBe('运行记录不存在')
  })
})

describe('auth store', () => {
  it('restore 在有令牌且服务端认账时恢复用户', async () => {
    localStorage.setItem('incident_agent_token', 'token-1')
    vi.mocked(currentUser).mockResolvedValue({ username: 'devatlas-demo' } as never)

    const store = useAuthStore()
    await store.restore()

    expect(store.user).toEqual({ username: 'devatlas-demo' })
    expect(store.token).toBe('token-1')
  })

  it('restore 遇到 401（后端契约 error_code=UNAUTHORIZED）时清掉令牌，界面不会卡在"已登录但全部 401"', async () => {
    localStorage.setItem('incident_agent_token', 'expired')
    vi.mocked(currentUser).mockRejectedValue(
      Object.assign(new Error('登录状态无效或已过期'), {
        response: { status: 401, data: { error_code: 'UNAUTHORIZED' } },
      }),
    )

    const store = useAuthStore()
    await store.restore()

    expect(store.user).toBeNull()
    expect(store.token).toBe('')
    expect(localStorage.getItem('incident_agent_token')).toBeNull()
  })

  it('restore 遇到 403 同样清掉令牌', async () => {
    localStorage.setItem('incident_agent_token', 'token-1')
    vi.mocked(currentUser).mockRejectedValue(
      Object.assign(new Error('用户已被禁用'), {
        response: { status: 403, data: { error_code: 'FORBIDDEN' } },
      }),
    )

    const store = useAuthStore()
    await store.restore()

    expect(store.token).toBe('')
    expect(localStorage.getItem('incident_agent_token')).toBeNull()
  })

  it('restore 遇到连接失败时只提示、保留 Token（网络抖动不能把人踢下线）', async () => {
    localStorage.setItem('incident_agent_token', 'good-token')
    vi.mocked(currentUser).mockRejectedValue(new Error('无法连接 Incident Agent API。'))

    const store = useAuthStore()
    await store.restore()

    expect(store.user).toBeNull()
    expect(store.token).toBe('good-token')
    expect(localStorage.getItem('incident_agent_token')).toBe('good-token')
    expect(store.error).toBe('无法连接 Incident Agent API。')
  })

  it('restore 遇到上游 503（DevAtlas 没起来）也保留 Token', async () => {
    localStorage.setItem('incident_agent_token', 'good-token')
    vi.mocked(currentUser).mockRejectedValue(httpError(503, '依赖服务暂不可用，请稍后重试'))

    const store = useAuthStore()
    await store.restore()

    expect(store.token).toBe('good-token')
    expect(localStorage.getItem('incident_agent_token')).toBe('good-token')
    expect(store.error).toBe('依赖服务暂不可用，请稍后重试')
  })

  it('没有令牌时不请求服务端', async () => {
    const store = useAuthStore()
    await store.restore()
    expect(currentUser).not.toHaveBeenCalled()
  })
})
