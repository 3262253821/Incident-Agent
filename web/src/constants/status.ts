/**
 * Run status values returned by the Agent API.
 *
 * Must stay in sync with `app/incident_agent/core/statuses.py`. A status the
 * frontend does not know about must never be silently displayed as a success.
 */
export const RUN_STATUS = {
  RUNNING: 'running',
  COMPLETED: 'completed',
  INSUFFICIENT_EVIDENCE: 'insufficient_evidence',
  DEGRADED: 'degraded',
  REPORT_VALIDATION_FAILED: 'report_validation_failed',
  MAX_ITERATIONS: 'max_iterations',
} as const

export const STATUS_LABEL: Record<string, string> = {
  [RUN_STATUS.RUNNING]: 'RUNNING',
  [RUN_STATUS.COMPLETED]: 'COMPLETED',
  [RUN_STATUS.INSUFFICIENT_EVIDENCE]: 'NO EVIDENCE',
  [RUN_STATUS.DEGRADED]: 'DEGRADED',
  [RUN_STATUS.REPORT_VALIDATION_FAILED]: 'REPORT FAILED',
  [RUN_STATUS.MAX_ITERATIONS]: 'LOOP LIMIT',
}

export const STATUS_TONE: Record<string, string> = {
  [RUN_STATUS.RUNNING]: 'busy',
  [RUN_STATUS.COMPLETED]: 'good',
  [RUN_STATUS.INSUFFICIENT_EVIDENCE]: 'warn',
  [RUN_STATUS.DEGRADED]: 'warn',
  [RUN_STATUS.REPORT_VALIDATION_FAILED]: 'warn',
  [RUN_STATUS.MAX_ITERATIONS]: 'warn',
}

/** Unknown statuses are shown verbatim and treated as a warning, not a success. */
export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status.toUpperCase()
}

export function statusTone(status: string): string {
  return STATUS_TONE[status] ?? 'warn'
}

/**
 * 被中断的运行：进程在 Graph 结束前消失，由下一次启动回收。
 * 它的服务端状态是 degraded，但必须显示成 INTERRUPTED，否则用户会把它
 * 当成一次正常的降级分析。
 */
export function runStatusLabel(status: string, interrupted?: boolean): string {
  return interrupted ? 'INTERRUPTED' : statusLabel(status)
}

export function runStatusTone(status: string, interrupted?: boolean): string {
  return interrupted ? 'warn' : statusTone(status)
}

/** 报告未通过校验时为 true；有报告就不算「证据快照」场景。 */
export function hasValidatedReport(status: string | undefined): boolean {
  return status === RUN_STATUS.COMPLETED || status === RUN_STATUS.INSUFFICIENT_EVIDENCE
}

/**
 * 屏幕阅读器播报文案（P1-5-3）。
 *
 * 状态标签本身是英文缩写（`DEGRADED`/`LOOP LIMIT`），读屏直接念缩写没有意义；
 * 这里给出中文整句。另外三条必须说清楚的状态语义：
 *
 * - **被中断的运行要念成"已中断"，不能跟着服务端的 `degraded` 念**，否则读屏用户
 *   听到的和界面显示的不一致（与 `runStatusLabel` 同一条规则）；
 * - **未知状态不能念成成功**，退回"状态未知"而不是把原值当正常状态播报；
 * - 没有运行时返回空串，`StatusAnnouncer` 因此保持静默，不会在挂载时乱播。
 */
export function runStatusAnnouncement(status: string | undefined, interrupted?: boolean): string {
  if (!status) return ''
  if (interrupted) return '分析已中断。'
  switch (status) {
    case RUN_STATUS.RUNNING:
      return '正在分析，模型正在收集证据。'
    case RUN_STATUS.COMPLETED:
      return '分析完成，已生成通过校验的报告。'
    case RUN_STATUS.INSUFFICIENT_EVIDENCE:
      return '分析结束，但没有取得工具证据，报告未经验证。'
    case RUN_STATUS.DEGRADED:
      return '分析降级结束，只生成了证据快照。'
    case RUN_STATUS.REPORT_VALIDATION_FAILED:
      return '分析结束，但报告未通过校验，只生成了证据快照。'
    case RUN_STATUS.MAX_ITERATIONS:
      return '分析达到循环上限后结束，只生成了证据快照。'
    default:
      return '分析结束，状态未知。'
  }
}
