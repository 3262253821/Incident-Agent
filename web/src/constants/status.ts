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
