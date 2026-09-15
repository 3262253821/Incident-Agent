/**
 * 表单可访问性测试（P1-5-3）。
 *
 * 设计文档章节：§13.4 Web UI（登录态、故障输入、运行中状态）；`role=alert`/`aria-busy`
 * 是 2026-09-15 的 P1-5-3（设计文档未涉及可访问性）。
 *
 * 两件事此前只能靠读模板确认：
 *
 * 1. **失败原因对读屏用户是否可感知**：`<p>` 上的错误文案在视觉上是红色的，但对
 *    屏幕阅读器只是普通段落，不会主动播报；`role="alert"` 才会。
 * 2. **提交按钮的忙碌状态**：按钮文字在"开始分析"/"分析中"之间切换，但没有
 *    `aria-busy` 时读屏不会把它当成"正在忙"，而且 `.spin` 图标本身没有语义。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import IncidentForm from '../src/components/IncidentForm.vue'
import LoginForm from '../src/components/LoginForm.vue'

function mountForm(overrides: Record<string, unknown> = {}) {
  return mount(IncidentForm, {
    props: {
      running: false,
      error: '',
      knowledgeBases: [{ id: 4, name: 'DevAtlas 开发演示知识库', description: null }],
      loadingKnowledgeBases: false,
      knowledgeBaseError: '',
      title: '订单服务返回 502',
      content: '网关返回 502',
      knowledgeBaseId: 4,
      topK: 5,
      ...overrides,
    },
  })
}

describe('IncidentForm 可访问性', () => {
  it('知识库为空时拦下提交，并把提示以 role=alert 播报', async () => {
    const wrapper = mountForm({ knowledgeBaseId: null })
    await wrapper.get('form').trigger('submit')

    const alert = wrapper.get('[role="alert"]')
    expect(alert.text()).toBe('请先选择要检索的知识库')
    expect(wrapper.emitted('submit')).toBeUndefined()
  })

  it('服务端错误与知识库加载错误都带 role=alert', () => {
    expect(mountForm({ error: '请求超时' }).get('.bottom-error').attributes('role')).toBe('alert')
    expect(mountForm({ knowledgeBaseError: '无法连接上游' }).get('.field-note').attributes('role')).toBe(
      'alert',
    )
    expect(mountForm({ knowledgeBases: [] }).get('.field-note').attributes('role')).toBe('alert')
  })

  it('提交按钮在运行时带 aria-busy 并禁用', async () => {
    const wrapper = mountForm({ running: true })
    const button = wrapper.get('button[type="submit"]')
    expect(button.attributes('aria-busy')).toBe('true')
    expect(button.attributes('disabled')).toBeDefined()
    expect(button.text()).toContain('分析中')

    await wrapper.setProps({ running: false })
    expect(wrapper.get('button[type="submit"]').attributes('aria-busy')).toBe('false')
  })

  it('选中知识库后提交的是修剪过的字段值与数字型 ID（空值不会变成 NaN）', async () => {
    const wrapper = mountForm({ title: '  订单服务返回 502  ', knowledgeBaseId: 4 })
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('submit')?.[0]?.[0]).toEqual({
      title: '订单服务返回 502',
      content: '网关返回 502',
      knowledge_base_id: 4,
      top_k: 5,
    })
  })
})

describe('LoginForm 可访问性', () => {
  it('登录错误是 role=alert，登录中按钮带 aria-busy', async () => {
    const wrapper = mount(LoginForm, { props: { loading: false, error: '用户名或密码错误' } })
    expect(wrapper.get('[role="alert"]').text()).toContain('用户名或密码错误')

    await wrapper.setProps({ loading: true })
    const button = wrapper.get('button[type="submit"]')
    expect(button.attributes('aria-busy')).toBe('true')
    expect(button.text()).toContain('验证中')
  })
})

describe('AppLayout 的触发按钮', () => {
  it('点「运行历史」时把按钮本身交给父组件（关闭后焦点要还给它）', async () => {
    const { default: AppLayout } = await import('../src/layouts/AppLayout.vue')
    const wrapper = mount(AppLayout, { props: { apiOnline: true } })

    const history = wrapper.get('button[aria-label="运行历史"]')
    await history.trigger('click')

    const payload = wrapper.emitted('history')
    expect(payload).toHaveLength(1)
    expect(payload?.[0]?.[0]).toBe(history.element)

    // 另外两个按钮不该触发历史事件（避免"点错按钮也开抽屉"）。
    await wrapper.get('button[aria-label="故障分析"]').trigger('click')
    expect(wrapper.emitted('history')).toHaveLength(1)
  })
})
