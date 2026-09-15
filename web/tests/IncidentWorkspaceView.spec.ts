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
 * 行为，不是后端契约。
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import IncidentWorkspaceView from '../src/views/IncidentWorkspaceView.vue'
import { useIncidentStore } from '../src/stores/incident'
import { makeRun } from './helpers'

vi.mock('../src/api/system', () => ({ checkHealth: vi.fn() }))
vi.mock('../src/api/knowledgeBases', () => ({ listKnowledgeBases: vi.fn() }))
vi.mock('../src/api/incidents', () => ({ analyzeIncident: vi.fn() }))
vi.mock('../src/api/runs', () => ({ getRun: vi.fn(), listRuns: vi.fn() }))
vi.mock('../src/api/auth', () => ({ currentUser: vi.fn(), login: vi.fn() }))
vi.mock('../src/api/client', () => ({
  apiErrorMessage: (error: unknown) =>
    error instanceof Error ? error.message : '发生未知错误，请稍后重试。',
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
    vi.mocked(currentUser).mockRejectedValue(new Error('token 已过期'))

    const wrapper = await mountWorkspace()

    expect(listKnowledgeBases).not.toHaveBeenCalled()
    expect(wrapper.find('.intake-panel').exists()).toBe(true)

    wrapper.unmount()
  })
})
