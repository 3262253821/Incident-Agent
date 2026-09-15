/**
 * 路由守卫的单测（P1-5-4）。
 *
 * 设计文档章节：§13.4 Web UI（登录态）。
 *
 * 为什么必须测：P1-5-4 的验收标准之一是"401 之后仍要跳登录页"——而守卫**只看
 * `localStorage` 里的 token**。响应拦截器清掉 token 之后，用户能回到登录页靠的
 * 就是这里。另外 `redirect` 参数是用户可控的（`/login?redirect=...`），必须挡住
 * `//evil.example` 这类协议相对地址，否则登录页会变成开放重定向。
 */
import { describe, expect, it } from 'vitest'
import type { RouteLocationNormalized } from 'vue-router'

import { requiresSession } from '../src/router'
import { safeRedirect } from '../src/utils/redirect'

function location(overrides: Partial<RouteLocationNormalized> = {}) {
  return {
    path: '/workspace',
    fullPath: '/workspace',
    name: 'workspace',
    meta: { requiresAuth: true },
    query: {},
    hash: '',
    params: {},
    matched: [],
    redirectedFrom: undefined,
    ...overrides,
  } as unknown as RouteLocationNormalized
}

describe('路由守卫：令牌在不在决定去留', () => {
  it('没有令牌时访问工作台 → 去登录页，并带上 redirect（登录后能回到原来要去的页面）', () => {
    localStorage.clear()

    expect(requiresSession(location())).toEqual({
      name: 'login',
      query: { redirect: '/workspace' },
    })
  })

  it('redirect 保留完整的 fullPath（含查询串与锚点）', () => {
    localStorage.clear()

    expect(
      requiresSession(
        location({ fullPath: '/workspace?status=degraded&cursor=abc#trace', path: '/workspace' }),
      ),
    ).toEqual({ name: 'login', query: { redirect: '/workspace?status=degraded&cursor=abc#trace' } })
  })

  it('有令牌时正常访问工作台（守卫不校验令牌有效性，那是接口与拦截器的事）', () => {
    localStorage.setItem('incident_agent_token', 'token-1')

    expect(requiresSession(location())).toBeUndefined()
  })

  it('已登录时访问登录页 → 回工作台（令牌被清掉之后这条不再成立，用户就停在登录页）', () => {
    localStorage.setItem('incident_agent_token', 'token-1')

    expect(
      requiresSession(location({ path: '/login', fullPath: '/login', name: 'login', meta: { guestOnly: true } })),
    ).toEqual({ name: 'workspace' })

    localStorage.clear()
    expect(
      requiresSession(location({ path: '/login', fullPath: '/login', name: 'login', meta: { guestOnly: true } })),
    ).toBeUndefined()
  })

  it('公开路由（既不需要登录也不是访客专用）原样放行', () => {
    localStorage.clear()

    expect(
      requiresSession(
        location({ path: '/', fullPath: '/', name: undefined, meta: {} }),
      ),
    ).toBeUndefined()
  })

  it('被清掉令牌之后（401 的真实后果）再访问工作台仍会去登录页并保留 redirect', () => {
    localStorage.setItem('incident_agent_token', 'token-1')
    expect(requiresSession(location())).toBeUndefined()

    // 响应拦截器的副作用就这一件事：把 localStorage 里的令牌删掉。
    localStorage.removeItem('incident_agent_token')

    expect(
      requiresSession(location({ fullPath: '/workspace?status=degraded' })),
    ).toEqual({ name: 'login', query: { redirect: '/workspace?status=degraded' } })
  })
})

describe('safeRedirect：只接受站内相对路径', () => {
  it('站内路径原样返回', () => {
    expect(safeRedirect('/workspace')).toBe('/workspace')
    expect(safeRedirect('/workspace?status=degraded')).toBe('/workspace?status=degraded')
  })

  it('缺省、空串与非字符串回落到工作台', () => {
    expect(safeRedirect(undefined)).toBe('/workspace')
    expect(safeRedirect('')).toBe('/workspace')
    expect(safeRedirect(['/workspace', '/login'])).toBe('/workspace')
  })

  it('挡住协议相对地址与绝对 URL（开放重定向）', () => {
    expect(safeRedirect('//evil.example/login')).toBe('/workspace')
    expect(safeRedirect('https://evil.example')).toBe('/workspace')
    expect(safeRedirect('/\\evil.example')).toBe('/workspace')
    expect(safeRedirect('workspace')).toBe('/workspace')
  })
})
