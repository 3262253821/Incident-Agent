/**
 * 工作台视图的集成测试（P1-5-3）。
 *
 * 设计文档章节：§13.4 Web UI（登录态、故障输入、运行中状态、工具步骤列表、报告展示）；
 * `aria-live` 播报与焦点返还是 2026-09-15 的 P1-5-3（设计文档未涉及）。
 *
 * 组件单测只能证明"抽屉自己会管理焦点"，证明不了**打开它的那条链路**：抽屉需要
 * 知道谁是触发者才能把焦点还回去，而触发按钮在 `AppLayout` 里、事件要经过视图。
 * 这条链路此前完全靠人工 review，也正是 P1-5-3 要补的部分。
 *
 * 依赖（鉴权、健康检查、历史列表、知识库列表）全部 mock：这里验证的是无障碍
 * 行为，不是后端契约。**例外是"网络故障不清 Token"**（P1-5-4）：它读取的正是
 * `auth.error`，而 `auth.error` 由 `restore()` 按"认证失败 / 连接失败"分流后写入，
 * 所以那几条用例断言的是真实 store，只把 API 层换成受控的失败。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import IncidentWorkspaceView from '../src/views/IncidentWorkspaceView.vue'
import { FAILED_STATUSES } from '../src/utils/apiErrors'
import { useAuthStore } from '../src/stores/auth'
import { useIncidentStore } from '../src/stores/incident'
import { makeRun } from './helpers'

vi.mock('../src/api/system', () => ({ checkHealth: vi.fn() }))
vi.mock('../src/api/knowledgeBases', () => ({ listKnowledgeBases: vi.fn() }))
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
  // store 通过这两个函数读 422 的 detail 数组与失败大类（P1-5-6）。
  apiErrorPayload: (error: unknown) => (error as { response?: { data?: unknown } })?.response?.data,
  validationErrors: (error: unknown) => {
    const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    return Array.isArray(detail) ? detail : []
  },
}))

const { checkHealth } = await import('../src/api/system')
const { listKnowledgeBases } = await import('../src/api/knowledgeBases')
const { listRuns } = await import('../src/api/runs')
const { currentUser } = await import('../src/api/auth')

/**
 * Pinia 必须是**同一个实例**：组件用注入的 pinia 调 `useIncidentStore()`，测试里
 * 也要能拿到同一个 store 来驱动状态，否则改的是另一个 store。
 */
let pinia = createPinia()

async function mountWorkspace() {
  const wrapper = mount(IncidentWorkspaceView, {
    global: { plugins: [pinia] },
    attachTo: document.body,
  })
  await flushPromises()
  return wrapper
}

/** 详情接口返回的完整运行载荷（列表摘要里没有报告/轨迹/观察）。 */
function runDetail(overrides: Parameters<typeof makeRun>[0] = {}) {
  return {
    ...makeRun(overrides),
    report: null,
    observations: [],
    steps: [],
    error: null,
    degraded_summary: null,
  }
}

beforeEach(() => {
  document.body.innerHTML = ''
  localStorage.clear()
  pinia = createPinia()
  vi.mocked(checkHealth).mockResolvedValue(undefined as never)
  vi.mocked(listKnowledgeBases).mockResolvedValue([] as never)
  vi.mocked(listRuns).mockResolvedValue({ items: [makeRun()], next_cursor: null } as never)
})

function incidentStore() {
  return useIncidentStore(pinia)
}

/** 模拟真实 axios 错误：`response.status` 是 HTTP 状态，`message` 是文案。 */
function httpError(status: number, message: string) {
  return Object.assign(new Error(message), { response: { status } })
}

afterEach(() => {
  vi.clearAllMocks()
  document.body.innerHTML = ''
})

describe('IncidentWorkspaceView accessibility', () => {
  it('始终渲染一个 aria-live 播报区（加载态不靠旋转图标传达）', async () => {
    const wrapper = await mountWorkspace()

    const announcer = wrapper.get('[role="status"][aria-live="polite"]')
    expect(announcer.attributes('aria-atomic')).toBe('true')
    // 初始没有运行时不该播报任何东西。
    expect(announcer.text()).toBe('')

    wrapper.unmount()
  })

  it('分析开始与结束都会更新播报文案', async () => {
    const wrapper = await mountWorkspace()
    const incident = incidentStore()

    incident.running = true
    await flushPromises()
    expect(wrapper.get('.sr-only[role="status"]').text()).toBe('正在分析，模型正在收集证据。')

    incident.running = false
    incident.result = runDetail() as never
    await flushPromises()
    expect(wrapper.get('.sr-only[role="status"]').text()).toBe('分析完成，已生成通过校验的报告。')

    wrapper.unmount()
  })

  it('被中断的运行播报成「已中断」，不跟着服务端的 degraded 念', async () => {
    const wrapper = await mountWorkspace()
    const incident = incidentStore()

    incident.result = runDetail({ status: 'degraded', interrupted: true }) as never
    await flushPromises()

    expect(wrapper.get('.sr-only[role="status"]').text()).toBe('分析已中断。')

    wrapper.unmount()
  })

  it('打开历史抽屉走的是 AppLayout 里的触发按钮，关闭后焦点回到它', async () => {
    const wrapper = await mountWorkspace()
    const trigger = wrapper.get('.rail-nav button[aria-label="运行历史"]')

    // jsdom 不会因为 click 自动设置 document.activeElement，真实浏览器会；这里显式
    // 模拟"用户用键盘 Tab 到按钮再按回车"，否则焦点归还的目标本身就是空的。
    ;(trigger.element as HTMLElement).focus()
    await trigger.trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(true)
    // 抽屉自己把焦点移进第一条记录。
    expect((document.activeElement as HTMLElement).className).toContain('history-row')

    await wrapper.get('[role="dialog"] .icon-button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    // 焦点必须回到那个触发按钮，而不是掉回 <body>。
    expect(document.activeElement).toBe(trigger.element)

    wrapper.unmount()
  })

  it('令牌无效（restore 失败）时不拉知识库，界面仍保持可用', async () => {
    localStorage.setItem('incident_agent_token', 'expired')
    vi.mocked(currentUser).mockRejectedValue(httpError(401, '登录状态无效或已过期'))

    const wrapper = await mountWorkspace()

    expect(listKnowledgeBases).not.toHaveBeenCalled()
    expect(wrapper.find('.intake-panel').exists()).toBe(true)

    wrapper.unmount()
  })

  it('后端不可达（不是 401）时保留 Token，并把连接失败提示显示在告警区（P1-5-4）', async () => {
    localStorage.setItem('incident_agent_token', 'good-token')
    vi.mocked(currentUser).mockRejectedValue(new Error('无法连接 Incident Agent API。'))

    const wrapper = await mountWorkspace()

    // 网络故障不清 Token——这是 P1-5-4 的核心区别。
    expect(localStorage.getItem('incident_agent_token')).toBe('good-token')
    expect(useAuthStore(pinia).token).toBe('good-token')
    expect(listKnowledgeBases).not.toHaveBeenCalled()
    // 不能安静失败：用户必须看得到"为什么没登录进去"。这里取的是底部那条
    // `.bottom-error`（表单自己的 `[role=alert]` 装的是知识库相关的提示）。
    expect(wrapper.get('.bottom-error').text()).toContain('无法连接 Incident Agent API。')

    wrapper.unmount()
  })

  it('令牌失效（401）时清 Token，让路由守卫把用户带回登录页（P1-5-4）', async () => {
    localStorage.setItem('incident_agent_token', 'expired')
    vi.mocked(currentUser).mockRejectedValue(httpError(401, '登录状态无效或已过期'))

    const wrapper = await mountWorkspace()

    expect(localStorage.getItem('incident_agent_token')).toBeNull()
    expect(useAuthStore(pinia).token).toBe('')

    wrapper.unmount()
  })
})

/**
 * P1-5-5 新增：抽屉筛选、重跑回填、失败细分提示。
 *
 * 这些行为的"接线"只能在视图层验证——抽屉只负责发出事件，真正改查询参数、
 * 回填表单、把说明传给表单的都是这里。
 */
describe('IncidentWorkspaceView 历史筛选与重跑（P1-5-5）', () => {
  async function openDrawer(wrapper: Awaited<ReturnType<typeof mountWorkspace>>) {
    const trigger = wrapper.get('.rail-nav button[aria-label="运行历史"]')
    ;(trigger.element as HTMLElement).focus()
    await trigger.trigger('click')
    await flushPromises()
    return wrapper.get('[role="dialog"]')
  }

  it('打开抽屉先按"不限筛选"拉第一页（不带 status / started_after）', async () => {
    const wrapper = await mountWorkspace()
    await openDrawer(wrapper)

    expect(listRuns).toHaveBeenCalledWith({})

    wrapper.unmount()
  })

  it('切换状态筛选会带着五个失败状态重查第一页（游标不能复用）', async () => {
    vi.mocked(listRuns).mockResolvedValue({ items: [makeRun()], next_cursor: 'cursor-1' } as never)
    const wrapper = await mountWorkspace()
    const dialog = await openDrawer(wrapper)

    await dialog.findAll('select')[0].setValue('failed')
    await flushPromises()

    expect(listRuns).toHaveBeenLastCalledWith({ status: FAILED_STATUSES })

    wrapper.unmount()
  })

  it('切换时间范围会带上 started_after（ISO 8601），并且不再带游标', async () => {
    vi.mocked(listRuns).mockResolvedValue({ items: [makeRun()], next_cursor: 'cursor-1' } as never)
    const wrapper = await mountWorkspace()
    const dialog = await openDrawer(wrapper)

    await dialog.findAll('select')[1].setValue('24h')
    await flushPromises()

    const params = vi.mocked(listRuns).mock.calls.at(-1)?.[0] as Record<string, unknown>
    expect(params.cursor).toBeUndefined()
    expect(String(params.started_after)).toMatch(/^\d{4}-\d{2}-\d{2}T/)

    wrapper.unmount()
  })

  it('点「重跑」回填标题与知识库、关掉抽屉，并说明哪些字段没能复用', async () => {
    const run = makeRun({ run_id: 'rerun-me', title: '网关 502 复盘', knowledge_base_id: 7, status: 'degraded' })
    vi.mocked(listRuns).mockResolvedValue({ items: [run], next_cursor: null } as never)
    const wrapper = await mountWorkspace()
    const dialog = await openDrawer(wrapper)

    await dialog.get('.history-rerun').trigger('click')
    await flushPromises()

    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect((wrapper.get('input[type="text"], .incident-form input').element as HTMLInputElement).value).toBe(
      '网关 502 复盘',
    )
    const notice = wrapper.get('.prefill-note').text()
    expect(notice).toContain('网关 502 复盘')
    expect(notice).toContain('#7')
    // 契约里没有原始日志与 top_k，必须如实说明而不是假装一键重跑。
    expect(notice).toContain('日志正文')
    expect(notice).toContain('不在历史记录里')
    // 焦点回到表单第一格，键盘用户不会停在已关闭的抽屉上。
    expect(document.activeElement?.tagName).toBe('INPUT')

    wrapper.unmount()
  })

  it('成功记录的重跑说明里不出现"失败原因明细"', async () => {
    vi.mocked(listRuns).mockResolvedValue({
      items: [makeRun({ run_id: 'ok', status: 'completed' })],
      next_cursor: null,
    } as never)
    const wrapper = await mountWorkspace()
    const dialog = await openDrawer(wrapper)

    await dialog.get('.history-rerun').trigger('click')
    await flushPromises()

    expect(wrapper.get('.prefill-note').text()).not.toContain('失败原因明细')

    wrapper.unmount()
  })

  it('失败大类建议显示在底部告警区（P1-5-6）', async () => {
    vi.mocked(currentUser).mockResolvedValue({ username: 'devatlas-demo' } as never)
    vi.mocked(listKnowledgeBases).mockResolvedValue([] as never)
    const wrapper = await mountWorkspace()
    const incident = incidentStore()
    incident.error = '依赖服务暂不可用，请稍后重试'
    incident.failureHint = { summary: '依赖服务暂时不可用', hint: '通常是 DevAtlas（鉴权 / 检索）没起来，稍后重试即可。' }
    await flushPromises()

    const bottom = wrapper.get('.bottom-error').text()
    expect(bottom).toContain('依赖服务暂不可用')
    expect(bottom).toContain('DevAtlas')

    wrapper.unmount()
  })
})
