/**
 * 失败状态的细分展示（P1-5-5）。
 *
 * 历史列表只有摘要，`RunSummary` 里**没有**失败工具与错误码——那些只在
 * `GET /runs/{run_id}` 的完整载荷里（`degraded_summary.failed_tools`、
 * `steps[].error_code`）。所以这里的职责是：**把摘要里已有的信息说清楚**，
 * 并明确告诉用户"还缺什么、去哪看"，而不是假装列表里有明细。
 */
import { RUN_STATUS } from '../constants/status'
import type { RunResponse, RunSummary } from '../types/api'

/**
 * 摘要这一行能给出的失败细分。
 *
 * - 被中断的运行：服务端状态是 `degraded`，但用户看到的必须是"已中断"（与
 *   `runStatusLabel` 同一条规则）；
 * - 报告失败：模型返回了内容但没通过校验 → 提示"报告未通过校验"，与"工具失败"
 *   是两回事；
 * - 循环上限：分析被预算截断，不是工具挂了；
 * - 证据不足：工具跑完了但没拿到可用证据；
 * - 未结束：进程重启回收前的中间态。
 */
export function failureKind(run: Pick<RunSummary, 'status' | 'interrupted'>): string {
  if (run.interrupted) return '已中断'
  switch (run.status) {
    case RUN_STATUS.DEGRADED:
      return '工具执行失败'
    case RUN_STATUS.REPORT_VALIDATION_FAILED:
      return '报告未通过校验'
    case RUN_STATUS.MAX_ITERATIONS:
      return '达到循环上限'
    case RUN_STATUS.INSUFFICIENT_EVIDENCE:
      return '证据不足'
    case RUN_STATUS.RUNNING:
      return '未结束（可能已被回收）'
    case RUN_STATUS.COMPLETED:
      return '成功'
    default:
      return '其他失败'
  }
}

/** `status` 值 → 抽屉里那一行的筛选归属（"失败"档要跟后端过滤值一致）。 */
export function isFailureStatus(run: Pick<RunSummary, 'status' | 'interrupted'>): boolean {
  if (run.interrupted) return true
  return run.status !== RUN_STATUS.COMPLETED && run.status !== RUN_STATUS.RUNNING
}

/**
 * 摘要行能拼出的"失败明细"。
 *
 * 被中断时**不给任何工具级猜测**：中断意味着进程在 Graph 结束前消失，摘要里的
 * 计数不足以说明是哪一步失败，硬编一句"检索失败"会是编造。
 */
export function failureDetail(run: RunSummary): string {
  const parts: string[] = []
  if (run.interrupted) {
    return '进程在分析结束前退出，轨迹可能不完整；打开可查看已落库的步骤。'
  }
  if (run.error) parts.push(run.error)
  if (run.status === RUN_STATUS.DEGRADED) {
    parts.push('至少一个工具失败，已生成确定性降级摘要（打开可见失败工具与建议）。')
  }
  if (run.status === RUN_STATUS.REPORT_VALIDATION_FAILED) {
    parts.push('模型返回的报告未通过校验，已回退为证据快照。')
  }
  if (run.status === RUN_STATUS.MAX_ITERATIONS) {
    parts.push(`达到循环上限（${run.iteration}/${run.max_iterations}），可能证据不完整。`)
  }
  if (run.status === RUN_STATUS.INSUFFICIENT_EVIDENCE) {
    parts.push('没有取得工具证据，报告未经验证。')
  }
  if (run.status === RUN_STATUS.RUNNING) {
    parts.push('这条运行没有结束标记，通常意味着进程在运行中被重启回收。')
  }
  return parts.join(' ')
}

/**
 * 详情接口里的失败工具清单（`degraded_summary.failed_tools`）。
 *
 * 只有打开一条记录之后才有这个信息——这正是"点开拉详情"存在的意义。
 */
export function failedTools(detail: RunResponse | null | undefined): string[] {
  return detail?.degraded_summary?.failed_tools ?? []
}

/** 步骤里带 `error_code` 的那些（详情页用它解释"哪一步失败了"）。 */
export function failedSteps(detail: RunResponse | null | undefined): { step_index: number; error_code: string }[] {
  const steps = detail?.steps ?? []
  return steps
    .filter((step) => Boolean(step.error_code))
    .map((step) => ({ step_index: step.step_index, error_code: step.error_code as string }))
}
