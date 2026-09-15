/**
 * 入口装配的单测（P1-5-4）。
 *
 * 设计文档章节：**不属于设计文档**——守的是"响应拦截器真的接到了应用上"这件事。
 *
 * 为什么单独测入口：拦截器可以写得很正确，却因为**没人注册处理函数**而完全没作用，
 * 而那种失效在浏览器里表现为"Token 过期后界面一直报 401、再也不跳登录页"——没有
 * 任何测试会红。这里直接 import `src/main.ts`（生产入口），把 Vue/Pinia/路由与
 * HTTP 层换掉，然后调用**真实注册进来的那个处理函数**，验证它会清会话并带
 * `redirect` 跳登录页。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const signOut = vi.fn()
const replace = vi.fn()

/** 被 `onSessionExpired()` 注册进来的处理函数（main.ts 导入时就会注册）。 */
let handler: ((error: unknown) => Promise<void>) | undefined

vi.mock('../src/api/client', () => ({
  apiErrorMessage: () => '',
  isAuthFailure: () => false,
  onSessionExpired: (next: typeof handler) => {
    handler = next
  },
}))

vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({ signOut }),
}))

vi.mock('../src/router', () => ({
  default: {
    beforeEach: vi.fn(),
    replace: (...args: unknown[]) => replace(...args),
  },
}))

vi.mock('vue', async (importOriginal) => {
  const actual = await importOriginal<typeof import('vue')>()
  return {
    ...actual,
    createApp: () => ({ use: () => ({ use: () => ({ mount: vi.fn() }) }) }),
  }
})

beforeEach(() => {
  signOut.mockClear()
  replace.mockClear()
  replace.mockResolvedValue(undefined)
})

describe('应用入口', () => {
  it('把会话失效处理函数接到 HTTP 客户端上（不接就等于没有统一 401 处理）', async () => {
    await import('../src/main')
    expect(typeof handler).toBe('function')
  })

  it('处理函数会清掉会话，并带着 redirect 跳登录页', async () => {
    await import('../src/main')
    // 真实浏览器里这时地址栏停在某个受保护页面；jsdom 里显式给出 location。
    window.history.replaceState({}, '', '/workspace?status=degraded')

    await handler?.(Object.assign(new Error('登录状态无效或已过期'), { response: { status: 401 } }))

    expect(signOut).toHaveBeenCalledTimes(1)
    expect(replace).toHaveBeenCalledWith({
      name: 'login',
      query: { redirect: '/workspace?status=degraded' },
    })
  })

  it('redirect 只接受站内路径（挡住 //evil.example 这类开放重定向）', async () => {
    await import('../src/main')
    window.history.replaceState({}, '', '/workspace')

    await handler?.(Object.assign(new Error('登录状态无效或已过期'), { response: { status: 401 } }))

    expect(replace).toHaveBeenCalledTimes(1)
    const target = replace.mock.calls[0][0] as { query: { redirect: string } }
    expect(target.query.redirect.startsWith('/')).toBe(true)
    expect(target.query.redirect.startsWith('//')).toBe(false)
  })
})
