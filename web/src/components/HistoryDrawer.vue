<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
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

const panel = ref<HTMLElement | null>(null)
/**
 * 谁把抽屉打开的。关闭时焦点要还给它，否则读屏/键盘用户的焦点会掉回
 * `<body>`，下一次 Tab 从页面开头重新开始（P1-5-3）。
 */
const restoreFocusTo = ref<HTMLElement | null>(null)

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ')

/** 面板内当前可聚焦的元素（顺序即 DOM 顺序，等于 Tab 顺序）。 */
function focusableElements(): HTMLElement[] {
  const root = panel.value
  if (!root) return []
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    (element) => element.getAttribute('aria-hidden') !== 'true',
  )
}

/**
 * 焦点陷阱：不把焦点留在抽屉里的话，Tab 会跑到抽屉背后的表单上——
 * 视觉上"抽屉挡着"，键盘上却还在操作被遮住的界面。
 */
function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.stopPropagation()
    emit('close')
    return
  }
  if (event.key !== 'Tab') return

  const elements = focusableElements()
  const first = elements[0]
  const last = elements[elements.length - 1]
  if (!first || !last) {
    // 没有任何可聚焦元素时不能让 Tab 漏出去。
    event.preventDefault()
    return
  }
  const active = document.activeElement as HTMLElement | null
  if (event.shiftKey && (active === first || !panel.value?.contains(active))) {
    event.preventDefault()
    last.focus()
    return
  }
  if (!event.shiftKey && active === last) {
    event.preventDefault()
    first.focus()
  }
}

function focusInitialElement() {
  const preferred =
    panel.value?.querySelector<HTMLElement>('.history-row') ?? focusableElements()[0]
  ;(preferred ?? panel.value)?.focus()
}

onMounted(async () => {
  // 顺序很重要（写这条时踩到过）：先装监听器，再 await。反过来写的话，在
  // `await nextTick()` 解开之前到达的 ESC 会完全丢失——组件测试里表现为
  // "挂了监听却收不到事件"，真实环境里是"抽屉刚打开就按 ESC 关不掉"。
  window.addEventListener('keydown', onKeydown)
  restoreFocusTo.value = (document.activeElement as HTMLElement | null) ?? null
  // 等列表渲染完再落焦点，否则第一行还不存在。
  await nextTick()
  focusInitialElement()
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  const target = restoreFocusTo.value
  restoreFocusTo.value = null
  // 触发器可能已随界面消失（例如跳转了路由），此时不能强行 focus。
  if (target && document.contains(target)) target.focus()
})

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
  <div
    ref="panel"
    class="history-drawer"
    role="dialog"
    aria-modal="true"
    aria-labelledby="history-drawer-title"
    tabindex="-1"
  >
    <div class="drawer-heading">
      <div>
        <span class="section-kicker">RECENT RUNS</span>
        <h3 id="history-drawer-title">运行历史</h3>
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
