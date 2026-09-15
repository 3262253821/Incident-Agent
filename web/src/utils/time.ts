/**
 * 时间展示工具（P1-3-2）。
 *
 * 后端返回的时间戳都是**带 +00:00 的 ISO 8601**（存储是 naive UTC，在 API 边界
 * 补上偏移），所以这里可以直接用 `Date.parse` 得到真实时刻，再换算成用户本地
 * 时间，不会出现"把 UTC 墙上时间当本地时间"的偏差。
 */

/** 相对时间，例如「刚刚」「3 分钟前」「2 小时前」「5 天前」，超过 7 天显示日期。 */
export function formatRelativeTime(
  iso: string | null | undefined,
  now: number = Date.now(),
): string {
  if (!iso) return ''
  const timestamp = Date.parse(iso)
  if (Number.isNaN(timestamp)) return ''

  const seconds = Math.round((now - timestamp) / 1000)
  // 客户端时钟慢于服务端时会出现负数：显示"刚刚"，不要显示"-3 分钟前"。
  if (seconds < 60) return '刚刚'

  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} 分钟前`

  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`

  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} 天前`

  return new Date(timestamp).toLocaleDateString('zh-CN')
}

/** 耗时，例如「820ms」「8.4s」「1m 5s」；未知（未结束 / 被中断）返回空串。 */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || ms < 0) return ''
  if (ms < 1000) return `${ms}ms`

  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(1)}s`

  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return rest ? `${minutes}m ${rest}s` : `${minutes}m`
}
