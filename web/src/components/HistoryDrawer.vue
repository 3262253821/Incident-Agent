<script setup lang="ts">
import { ArrowRight, X } from 'lucide-vue-next'
import { runStatusLabel, runStatusTone } from '../constants/status'
import { formatDuration, formatRelativeTime } from '../utils/time'
import type { RunSummary } from '../types/api'

defineProps<{ runs: RunSummary[]; hasMore?: boolean; loadingMore?: boolean }>()
const emit = defineEmits<{
  close: []
  select: [run: RunSummary]
  loadMore: []
}>()

/** 被中断的运行与普通 degraded 区分开，避免历史和主状态展示不一致。 */
function runLabel(run: RunSummary) {
  return runStatusLabel(run.status, run.interrupted)
}

/** 状态细分：running / 证据不足 / 报告失败 / 循环上限 / 被中断 各有自己的色调。 */
function runTone(run: RunSummary) {
  return runStatusTone(run.status, run.interrupted)
}

/** 一行内回答「什么时候跑的、花了多久」。 */
function runTiming(run: RunSummary) {
  const parts = [formatRelativeTime(run.started_at)]
  const duration = formatDuration(run.duration_ms)
  if (duration) parts.push(`耗时 ${duration}`)
  return parts.filter(Boolean).join(' · ')
}

/** 列表只有计数；完整轨迹在点开时通过详情接口加载。 */
function runCounts(run: RunSummary) {
  return `${run.steps_count} steps · ${run.observations_count} observations`
}
</script>

<template>
  <div class="history-drawer">
    <div class="drawer-heading">
      <div>
        <span class="section-kicker">RECENT RUNS</span>
        <h3>运行历史</h3>
      </div>
      <button
        class="icon-button"
        title="关闭历史"
        aria-label="关闭历史"
        @click="emit('close')"
      >
        <X :size="18" />
      </button>
    </div>
    <button
      v-for="item in runs"
      :key="item.run_id"
      class="history-row"
      @click="emit('select', item)"
    >
      <span class="history-status" :class="[runTone(item), item.status]"></span>
      <span>
        <strong>{{ item.title }}</strong>
        <small>{{ runLabel(item) }} · {{ runTiming(item) }}</small>
        <small>{{ runCounts(item) }} · {{ item.run_id.slice(0, 8) }}</small>
      </span>
      <ArrowRight :size="16" />
    </button>
    <p v-if="!runs.length" class="drawer-empty">暂时没有运行记录。</p>
    <button
      v-if="runs.length && hasMore"
      class="history-more"
      :disabled="loadingMore"
      @click="emit('loadMore')"
    >
      {{ loadingMore ? '加载中…' : '加载更多' }}
    </button>
  </div>
</template>
