/**
 * `HistoryDrawer.vue` 的组件测试（P1-5-3）。
 *
 * 设计文档章节：§13.4 Web UI（运行历史展示）；`role=dialog`/键盘/焦点管理是
 * 2026-09-15 的 P1-5-3（设计文档未涉及可访问性，属工程质量补充）。
 *
 * 这个抽屉在 P1-5-3 之前只是"一个绝对定位的 div"：没有 `role="dialog"`，没有 ESC，
 * 打开后焦点仍在背后的表单上，关闭后焦点掉回 `<body>`。下面每一条都对应一个
 * 具体缺陷，而不是"存在某个属性"的形式检查：
 *
 * 1. 打开时焦点进入抽屉（否则键盘用户看不见自己在哪里）；
 * 2. ESC 关闭（模态对话框的通用约定）；
 * 3. Tab / Shift+Tab 在抽屉内循环（否则 Tab 会跑到被遮住的表单上）；
 * 4. 关闭时焦点还给触发按钮——并且**触发按钮已经不在 DOM 里时不能强设焦点**；
 * 5. 对话框语义（`role`/`aria-modal`/标题关联）与列表内容渲染。
 */
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import HistoryDrawer from '../src/components/HistoryDrawer.vue'
import { makeRun } from './helpers'

function pressKey(key: string, shiftKey = false): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key, shiftKey, bubbles: true, cancelable: true })
  window.dispatchEvent(event)
  return event
}

function mountDrawer(runs = [makeRun({ run_id: 'a' }), makeRun({ run_id: 'b' })]) {
  return mount(HistoryDrawer, {
    // hasMore 默认给 true：否则「加载更多」按钮不存在，焦点陷阱的"最后一个元素"
    // 就落不到它身上，用例会变成在测别的东西。
    props: { runs, hasMore: true },
    attachTo: document.body,
  })
}

beforeEach(() => {
  document.body.innerHTML = ''
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('HistoryDrawer accessibility', () => {
  it('暴露模态对话框语义，并把标题关联给读屏', () => {
    const wrapper = mountDrawer()
    const dialog = wrapper.get('[role="dialog"]')

    expect(dialog.attributes('aria-modal')).toBe('true')
    expect(dialog.attributes('aria-labelledby')).toBe('history-drawer-title')
    // aria-labelledby 指向的元素必须真实存在，否则读屏拿不到对话框名字。
    expect(wrapper.get('#history-drawer-title').text()).toBe('运行历史')

    wrapper.unmount()
  })

  it('打开后焦点进入抽屉的第一条记录（不是留在背后的表单上）', async () => {
    const trigger = document.createElement('button')
    trigger.textContent = '运行历史'
    document.body.appendChild(trigger)
    trigger.focus()

    const wrapper = mountDrawer()
    await wrapper.vm.$nextTick()

    expect(document.activeElement).toBe(wrapper.findAll('.history-row')[0].element)

    wrapper.unmount()
  })

  it('按下 ESC 关闭抽屉', () => {
    const wrapper = mountDrawer()
    const event = pressKey('Escape')

    expect(wrapper.emitted('close')).toHaveLength(1)
    // 事件不该继续冒泡给页面上的其他 ESC 处理者。
    expect(event.defaultPrevented).toBe(false)

    wrapper.unmount()
  })

  it('挂载后立刻按 ESC 也能关闭（监听器不能在 await 之后才装）', () => {
    // 这条用例是回归测试：最初把 `addEventListener` 写在 `await nextTick()` 之后，
    // 于是"抽屉刚打开就按 ESC"完全没反应——组件测试里表现为 emitted('close') 为
    // undefined，真实环境里是键盘用户关不掉对话框。
    const wrapper = mountDrawer()
    const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })
    window.dispatchEvent(event)

    expect(wrapper.emitted('close')).toHaveLength(1)

    wrapper.unmount()
  })

  it('Tab 到最后一个可聚焦元素后循环回第一个（Shift+Tab 反向同理）', async () => {
    const wrapper = mountDrawer()
    await wrapper.vm.$nextTick()

    const last = wrapper.get('.history-more').element as HTMLElement
    last.focus()
    expect(document.activeElement).toBe(last)

    pressKey('Tab')
    expect(document.activeElement).toBe(wrapper.get('.icon-button').element)

    pressKey('Tab', true)
    expect(document.activeElement).toBe(last)

    wrapper.unmount()
  })

  it('关闭后把焦点还给触发按钮；触发按钮已消失时不强设焦点', async () => {
    const trigger = document.createElement('button')
    document.body.appendChild(trigger)
    trigger.focus()

    const wrapper = mountDrawer()
    wrapper.unmount()
    expect(document.activeElement).toBe(trigger)

    // 第二次：焦点归还的目标在抽屉关闭前就被移出 DOM（例如路由切换）。
    const gone = document.createElement('button')
    document.body.appendChild(gone)
    gone.focus()
    const second = mountDrawer()
    gone.remove()
    expect(() => second.unmount()).not.toThrow()
    expect(document.activeElement).not.toBe(gone)
  })

  it('渲染每条记录的状态与计数；没有记录时给出空态', () => {
    const wrapper = mountDrawer([makeRun({ status: 'degraded', interrupted: true })])
    expect(wrapper.get('.history-row strong').text()).toBe('订单服务返回 502')
    // 被中断的运行必须显示 INTERRUPTED，而不是服务端的 degraded。
    expect(wrapper.get('.history-row').text()).toContain('INTERRUPTED')
    expect(wrapper.get('.history-row').text()).toContain('5 steps · 2 observations')

    const empty = mountDrawer([])
    expect(empty.get('.drawer-empty').text()).toBe('暂时没有运行记录。')
    expect(empty.find('.history-more').exists()).toBe(false)

    wrapper.unmount()
    empty.unmount()
  })

  it('还有下一页时渲染「加载更多」，加载中时禁用', async () => {
    const wrapper = mount(HistoryDrawer, {
      props: { runs: [makeRun()], hasMore: true, loadingMore: true },
      attachTo: document.body,
    })
    const more = wrapper.get('.history-more')
    expect(more.text()).toBe('加载中…')
    expect(more.attributes('disabled')).toBeDefined()

    await wrapper.setProps({ loadingMore: false })
    expect(wrapper.get('.history-more').text()).toBe('加载更多')
    await wrapper.get('.history-more').trigger('click')
    expect(wrapper.emitted('loadMore')).toHaveLength(1)

    wrapper.unmount()
  })
})
