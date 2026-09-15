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
    expect(empty.get('.drawer-empty').text()).toBe('当前筛选下暂时没有运行记录。')
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

/**
 * P1-5-5 新增：筛选交互、"重跑"、失败细分。
 *
 * 这三件事此前在抽屉里都不存在：列表只能整体刷新，行只能点开（没有任何"重跑"
 * 入口），失败状态只有状态标签（看不出是哪一种失败、也不知道该补什么信息）。
 */
describe('HistoryDrawer 筛选与重跑', () => {
  it('状态筛选默认「全部」，切换后把新档位抛给父组件（由父组件重新拉第一页）', async () => {
    const wrapper = mountDrawer()
    const selects = wrapper.findAll('.drawer-filters select')
    expect(selects).toHaveLength(2)
    expect((selects[0].element as HTMLSelectElement).value).toBe('all')

    await selects[0].setValue('failed')

    expect(wrapper.emitted('update:statusFilter')?.[0]).toEqual(['failed'])
    wrapper.unmount()
  })

  it('时间筛选同样受控：切换后抛 update:timeRange', async () => {
    const wrapper = mountDrawer()
    const select = wrapper.findAll('.drawer-filters select')[1]

    await select.setValue('7d')

    expect(wrapper.emitted('update:timeRange')?.[0]).toEqual(['7d'])
    wrapper.unmount()
  })

  it('筛选控件带 aria-label（视觉上没有文字标签，读屏必须能识别）', () => {
    const wrapper = mountDrawer()
    const selects = wrapper.findAll('.drawer-filters select')
    expect(selects[0].attributes('aria-label')).toBe('按运行结果筛选')
    expect(selects[1].attributes('aria-label')).toBe('按时间范围筛选')
    wrapper.unmount()
  })

  it('点「重跑」发出 rerun 事件，且不会同时触发"打开这条记录"', async () => {
    const run = makeRun({ run_id: 'rerun-me', title: '订单服务返回 502', knowledge_base_id: 4 })
    const wrapper = mountDrawer([run])

    await wrapper.get('.history-rerun').trigger('click')

    expect(wrapper.emitted('rerun')?.[0]?.[0]).toEqual(run)
    expect(wrapper.emitted('select')).toBeUndefined()
    wrapper.unmount()
  })

  it('「重跑」与整行是兄弟节点，不是一个按钮套在另一个按钮里', async () => {
    // 这条是结构约束，也是 E2 反证留下的结论：最初我把 `.stop` 注释成"防止触发父级
    // 行的 click"，实测发现 row 与 rerun 是兄弟（都挂在 .history-row-wrap 下），
    // 所以 `.stop` 并非"防止打开详情"的关键——把它删掉这两个用例仍然全绿（E2 没抓到）。
    // 真正要守住的是这个结构：嵌套按钮在 HTML 里非法，键盘行为也会变得不可预期。
    const wrapper = mountDrawer([makeRun()])
    const rerun = wrapper.get('.history-rerun').element as HTMLElement
    const row = wrapper.get('.history-row').element as HTMLElement

    expect(rerun.parentElement?.className).toContain('history-row-wrap')
    expect(row.contains(rerun)).toBe(false)

    // 真的会冒泡的事件也只触发 rerun（select 不会被顺带触发）。
    rerun.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }))
    expect(wrapper.emitted('rerun')).toHaveLength(1)
    expect(wrapper.emitted('select')).toBeUndefined()
    wrapper.unmount()
  })

  it('每行的重跑按钮有可区分的无障碍名称（读屏听得出是哪一条）', () => {
    const wrapper = mountDrawer([
      makeRun({ run_id: 'a', title: '故障甲' }),
      makeRun({ run_id: 'b', title: '故障乙' }),
    ])
    const labels = wrapper.findAll('.history-rerun').map((button) => button.attributes('aria-label'))
    expect(labels).toEqual(['用「故障甲」重跑', '用「故障乙」重跑'])
    wrapper.unmount()
  })

  it('失败记录在列表里就写明"哪种失败"（细分展示，不只是状态标签）', () => {
    const wrapper = mountDrawer([
      makeRun({ run_id: 'a', status: 'degraded' }),
      makeRun({ run_id: 'b', status: 'report_validation_failed' }),
      makeRun({ run_id: 'c', status: 'max_iterations', iteration: 6, max_iterations: 6 }),
      makeRun({ run_id: 'd', status: 'completed' }),
    ])
    const rows = wrapper.findAll('.history-row')

    expect(rows[0].text()).toContain('工具执行失败')
    expect(rows[0].text()).toContain('至少一个工具失败')
    expect(rows[1].text()).toContain('报告未通过校验')
    expect(rows[2].text()).toContain('达到循环上限')
    expect(rows[2].text()).toContain('6/6')
    // 成功的一条不该出现失败说明。
    expect(rows[3].find('.history-failure').exists()).toBe(false)
    wrapper.unmount()
  })

  it('被中断的记录同时给出"已中断"与原因，不跟服务端的 degraded 混为一谈', () => {
    const wrapper = mountDrawer([makeRun({ run_id: 'a', status: 'degraded', interrupted: true })])
    const text = wrapper.get('.history-row').text()

    expect(text).toContain('INTERRUPTED')
    expect(text).toContain('已中断')
    expect(text).toContain('进程在分析结束前退出')
    wrapper.unmount()
  })
})
