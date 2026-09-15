<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ArrowRight, RotateCcw, X } from 'lucide-vue-next'
import { runStatusLabel, runStatusTone } from '../constants/status'
import { formatDuration, formatRelativeTime } from '../utils/time'
import { failureDetail, failureKind } from '../utils/failingRun'
import type { StatusFilter, TimeRangeFilter } from '../utils/apiErrors'
import type { RunSummary } from '../types/api'

/**
 * 筛选与"重跑"回调（P1-5-5）。
 *
 * 抽屉**不自己发请求**：筛选值由父组件持有，变化时向上抛事件、由父组件重新拉第一页。
 * 这样"翻页要带上同一组条件"这件事只有一个地方需要负责（store 的 `historyQuery`）。
 */
const props = withDefaults(
  defineProps<{
    runs: RunSummary[]
    hasMore?: boolean
    loadingMore?: boolean
    statusFilter?: StatusFilter
    timeRange?: TimeRangeFilter
  }>(),
  { hasMore: false, loadingMore: false, statusFilter: 'all', timeRange: 'all' },
)
const emit = defineEmits<{
  close: []
  select: [run: RunSummary]
  loadMore: []
  /** 详情里的失败工具等明细要打开之后才有，所以"重跑"只复用摘要里有的字段。 */
  rerun: [run: RunSummary]
  'update:statusFilter': [value: StatusFilter]
  'update:timeRange': [value: TimeRangeFilter]
}>()

/** 焦点陷阱的作用范围（`role=dialog` 的那个元素）。 */
const panel = ref<HTMLElement | null>(null)

/**
 * 谁把抽屉打开的。关闭时焦点要还给它，否则读屏/键盘用户的焦点会掉回
 * `<body>`，下一次 Tab 从页面开头重新开始（P1-5-3）。
 */
const restoreFocusTo = ref<HTMLElement | null>(null)
/** 筛选控件是受控的：切换后立刻把新值抛给父组件，由父组件重新拉第一页。 */
const statusFilter = ref<StatusFilter>(props.statusFilter)
const timeRange = ref<TimeRangeFilter>(props.timeRange)

const STATUS_FILTER_LABEL = '按运行结果筛选'
const TIME_FILTER_LABEL = '按时间范围筛选'

function onStatusFilterChange() {
  emit('update:statusFilter', statusFilter.value)
}

function onTimeRangeChange() {
  emit('update:timeRange', timeRange.value)
}

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

/**
 * 失败细分（P1-5-5）：列表里就要能看出"哪种失败"。
 *
 * 这里只用摘要里真实存在的字段；失败工具清单要打开详情才有（见 `utils/failingRun.ts`）。
 */
function runFailure(run: RunSummary) {
  return failureDetail(run)
}

function runFailureKind(run: RunSummary) {
  return failureKind(run)
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
    <!--
      筛选（P1-5-5）。两个 select 而不是一排状态标签：后端只认精确状态值，
      而用户想说的是"只看失败的"，所以这里做成"结果档位 + 时间档位"两组。
    -->
    <div class="drawer-filters">
      <label>
        <span class="sr-only">{{ STATUS_FILTER_LABEL }}</span>
        <select v-model="statusFilter" :aria-label="STATUS_FILTER_LABEL" @change="onStatusFilterChange">
          <option value="all">全部</option>
          <option value="failed">仅失败</option>
          <option value="completed">仅成功</option>
        </select>
      </label>
      <label>
        <span class="sr-only">{{ TIME_FILTER_LABEL }}</span>
        <select v-model="timeRange" :aria-label="TIME_FILTER_LABEL" @change="onTimeRangeChange">
          <option value="all">不限时间</option>
          <option value="24h">最近 24 小时</option>
          <option value="7d">最近 7 天</option>
          <option value="30d">最近 30 天</option>
        </select>
      </label>
    </div>
    <div
      v-for="item in runs"
      :key="item.run_id"
      class="history-row-wrap"
    >
      <button
        class="history-row"
        @click="emit('select', item)"
      >
        <span class="history-status" :class="[runTone(item), item.status]"></span>
        <span>
          <strong>{{ item.title }}</strong>
          <small>{{ runLabel(item) }} · {{ runFailureKind(item) }} · {{ runTiming(item) }}</small>
          <small>{{ runCounts(item) }} · {{ item.run_id.slice(0, 8) }}</small>
          <!-- 失败原因单独一行：它是用户打开抽屉最想看的东西。 -->
          <small v-if="runFailure(item)" class="history-failure">{{ runFailure(item) }}</small>
        </span>
        <ArrowRight :size="16" />
      </button>
      <!--
        「重跑」只复用摘要里真实存在的字段（标题 + 知识库）。原始日志与 top_k
        不在摘要/详情契约里，所以父组件会提示用户补填，见 utils/failingRun.ts。
        它与整行是**兄弟**而不是嵌套（嵌套按钮在 HTML 里非法）；`.stop` 只是让
        点击不再往上冒给抽屉容器，不是"防止打开详情"——那条链路由兄弟结构保证
        （E2 反证实测：去掉 `.stop` 后相关用例仍然全绿）。
      -->
      <button
        class="history-rerun"
        :aria-label="`用「${item.title}」重跑`"
        title="按这条记录的知识库与标题重新分析"
        @click.stop="emit('rerun', item)"
      >
        <RotateCcw :size="14" /> 重跑
      </button>
    </div>
    <p v-if="!runs.length" class="drawer-empty">当前筛选下暂时没有运行记录。</p>
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
