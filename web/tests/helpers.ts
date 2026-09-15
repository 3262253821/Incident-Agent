/**
 * 组件测试的共享夹具（P1-5-3）。
 *
 * 三件事各只做一次：① `localStorage` 在 jsdom 里是跨用例共享的，token 泄漏会让
 * "未登录"这类用例静默变成"已登录"；② 对话框的焦点管理依赖 `document.activeElement`，
 * 每个用例从一个干净的 `<body>` 开始；③ 测试数据一律用工厂函数，避免用例之间
 * 通过共享对象串味（改了一个字段就在下一个用例里看到）。
 */
import type { RunSummary } from '../src/types/api'

/** 每次返回一个新对象：`overrides` 只影响这一条记录。 */
export function makeRun(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: '3f4d2c1b-0000-4000-8000-000000000000',
    title: '订单服务返回 502',
    status: 'completed',
    knowledge_base_id: 4,
    iteration: 2,
    max_iterations: 6,
    steps_count: 5,
    observations_count: 2,
    interrupted: false,
    error: null,
    started_at: '2026-09-15T08:00:00+00:00',
    completed_at: '2026-09-15T08:00:04+00:00',
    duration_ms: 4321,
    ...overrides,
  }
}

/** 重置 jsdom 的全局状态。在需要干净起点的用例里显式调用。 */
export function resetDom(): void {
  localStorage.clear()
  document.body.innerHTML = ''
}
