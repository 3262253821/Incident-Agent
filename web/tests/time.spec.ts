/**
 * `src/utils/time.ts` 的正式单测（P1-5-3）。
 *
 * 设计文档章节：§13.4 Web UI（"前端第一版只需要实现：登录态、故障输入、运行中状态、
 * 工具步骤列表、引用和报告展示"，相对时间与耗时属于列表与状态展示）；可访问性
 * 与前端测试框架是 2026-09-15 的 P1-5-3，设计文档未涉及。
 *
 * 这 14 条用例此前是 `tmp/check_time_helpers.ts`（`tmp/` 不提交），靠
 * `node --experimental-strip-types` 手跑——也就是说它们**不在 CI 里**，改了
 * `time.ts` 没有任何东西会失败。现在搬进 vitest，`npm run test` 会在 CI 的前端
 * job 里执行。
 */
import { describe, expect, it } from 'vitest'

import { formatDuration, formatRelativeTime } from '../src/utils/time'

/** 固定"现在"，避免用例依赖真实时钟。 */
const NOW = Date.parse('2026-09-15T12:00:00+00:00')

function secondsAgo(seconds: number): string {
  return new Date(NOW - seconds * 1000).toISOString()
}

describe('formatRelativeTime', () => {
  it('一分钟内显示「刚刚」', () => {
    expect(formatRelativeTime(secondsAgo(0), NOW)).toBe('刚刚')
    expect(formatRelativeTime(secondsAgo(59), NOW)).toBe('刚刚')
  })

  it('分钟/小时/天各用对应的单位', () => {
    expect(formatRelativeTime(secondsAgo(3 * 60), NOW)).toBe('3 分钟前')
    expect(formatRelativeTime(secondsAgo(2 * 3600), NOW)).toBe('2 小时前')
    expect(formatRelativeTime(secondsAgo(5 * 86400), NOW)).toBe('5 天前')
  })

  it('刚好跨过每个单位边界时进位（60 秒 = 1 分钟）', () => {
    expect(formatRelativeTime(secondsAgo(60), NOW)).toBe('1 分钟前')
    expect(formatRelativeTime(secondsAgo(3600), NOW)).toBe('1 小时前')
    expect(formatRelativeTime(secondsAgo(86400), NOW)).toBe('1 天前')
  })

  it('超过 7 天改用本地日期', () => {
    const iso = secondsAgo(8 * 86400)
    expect(formatRelativeTime(iso, NOW)).toBe(new Date(Date.parse(iso)).toLocaleDateString('zh-CN'))
  })

  it('空值与非法值返回空串（后端允许 started_at 为 null）', () => {
    expect(formatRelativeTime(null, NOW)).toBe('')
    expect(formatRelativeTime(undefined, NOW)).toBe('')
    expect(formatRelativeTime('', NOW)).toBe('')
    expect(formatRelativeTime('not-a-date', NOW)).toBe('')
  })

  it('客户端时钟慢于服务端时不显示负数（时钟偏差防御）', () => {
    expect(formatRelativeTime(secondsAgo(-90), NOW)).toBe('刚刚')
  })
})

describe('formatDuration', () => {
  it('毫秒、秒、分钟三种量级', () => {
    expect(formatDuration(820)).toBe('820ms')
    expect(formatDuration(8400)).toBe('8.4s')
    expect(formatDuration(65000)).toBe('1m 5s')
    expect(formatDuration(120000)).toBe('2m')
  })

  it('恰好 1000ms 进位成秒', () => {
    expect(formatDuration(1000)).toBe('1.0s')
  })

  it('未结束与被回收的中断运行（null/undefined）返回空串', () => {
    expect(formatDuration(null)).toBe('')
    expect(formatDuration(undefined)).toBe('')
  })

  it('负数当作未知而不是「-1ms」', () => {
    expect(formatDuration(-1)).toBe('')
  })
})
