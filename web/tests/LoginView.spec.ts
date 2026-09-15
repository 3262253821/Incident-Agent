/**
 * 登录页的单测（P1-5-4）。
 *
 * 设计文档章节：§13.4 Web UI（登录态）。
 *
 * 覆盖的是 P1-5-4 新增的那一段：登录成功之后去哪儿。此前一律 `router.push({name:'workspace'})`，
 * 于是"令牌过期被踢到登录页"的用户登录回来会回到工作台首页，丢掉他原本要打开的页面。
 * 现在 `redirect` 由路由守卫写进地址栏，登录成功后消费它——**但只接受站内路径**，
 * 否则 `/login?redirect=https://evil.example` 就成了开放重定向。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import LoginView from '../src/views/LoginView.vue'

const push = vi.fn()
const signIn = vi.fn()
let query: Record<string, string> = {}
/** 挂载后的组件实例（`submit()` 是 async 的，需要拿它的 promise 才能断言拒绝）。 */
let wrapper: ReturnType<typeof mount> | undefined

vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
  useRoute: () => ({ query }),
}))

vi.mock('../src/stores/auth', () => ({
  useAuthStore: () => ({ signIn, loading: false, error: '' }),
}))

vi.mock('../src/api/system', () => ({ checkHealth: vi.fn() }))

vi.mock('../src/api/client', () => ({
  TOKEN_STORAGE_KEY: 'incident_agent_token',
  apiErrorMessage: (error: unknown) =>
    error instanceof Error ? error.message : '发生未知错误，请稍后重试。',
  isAuthFailure: () => false,
  onSessionExpired: vi.fn(),
}))

async function mountLogin() {
  wrapper = mount(LoginView)
  await flushPromises()
  return wrapper
}

async function submitLogin() {
  const mounted = await mountLogin()
  await mounted.get('form').trigger('submit')
  await flushPromises()
  return mounted
}

/**
 * 直接调用组件暴露的 `submit()` 并等它 settle。
 *
 * 不能用 `trigger('submit')` 再断言拒绝：Vue 的事件处理器是即发即忘的，`trigger()`
 * 的 promise 与处理器的 promise 无关（这也是它会把拒绝变成 unhandled rejection 的原因）。
 */
async function submitAndSettle() {
  await mountLogin()
  const submit = (wrapper as unknown as { vm: { submit: (u: string, p: string) => Promise<void> } })
    .vm.submit
  return submit('devatlas-demo', 'wrong-password').then(
    () => 'resolved' as const,
    (error: unknown) => error,
  )
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  push.mockClear()
  signIn.mockReset()
})

describe('LoginView 登录后的去向', () => {
  it('没有 redirect 时进工作台', async () => {
    query = {}
    signIn.mockResolvedValue(undefined)

    await submitLogin()

    expect(push).toHaveBeenCalledWith('/workspace')
  })

  it('有站内 redirect 时回到原来要去的页面（保留查询串）', async () => {
    query = { redirect: '/workspace?status=degraded&cursor=abc' }
    signIn.mockResolvedValue(undefined)

    await submitLogin()

    expect(push).toHaveBeenCalledWith('/workspace?status=degraded&cursor=abc')
  })

  it('站外 redirect（协议相对地址）被忽略，回落到工作台', async () => {
    query = { redirect: '//evil.example/steal' }
    signIn.mockResolvedValue(undefined)

    await submitLogin()

    expect(push).toHaveBeenCalledWith('/workspace')
  })

  it('登录失败时不跳转（错误由表单以 role=alert 展示）', async () => {
    query = {}
    signIn.mockRejectedValue(new Error('用户名或密码错误'))

    const outcome = await submitAndSettle()

    expect(outcome).toBeInstanceOf(Error)
    expect((outcome as Error).message).toBe('用户名或密码错误')
    expect(push).not.toHaveBeenCalled()
  })
})
