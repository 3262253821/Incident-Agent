<script setup lang="ts">
import { ArrowRight, X } from 'lucide-vue-next'
import { RUN_STATUS, statusLabel } from '../constants/status'
import type { RunSummary } from '../types/api'

defineProps<{ runs: RunSummary[] }>()
const emit = defineEmits<{ close: []; select: [run: RunSummary] }>()

/** 被中断的运行与普通 degraded 区分开，避免历史和主状态展示不一致。 */
function runLabel(run: RunSummary) {
  if (run.interrupted) return 'INTERRUPTED'
  return statusLabel(run.status)
}

function runTone(run: RunSummary) {
  if (run.interrupted) return 'warn'
  return run.status === RUN_STATUS.COMPLETED ? 'good' : 'warn'
}

/** 列表只有计数；完整轨迹在点开时通过详情接口加载。 */
function runMeta(run: RunSummary) {
  return [
    runLabel(run),
    `${run.steps_count} steps`,
    `${run.observations_count} observations`,
    run.run_id.slice(0, 8),
  ].join(' · ')
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
        <small>{{ runMeta(item) }}</small>
      </span>
      <ArrowRight :size="16" />
    </button>
    <p v-if="!runs.length" class="drawer-empty">暂时没有运行记录。</p>
  </div>
</template>
