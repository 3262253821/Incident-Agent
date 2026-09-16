<script setup lang="ts">
/**
 * 应用外壳：**左侧栏 + 中栏**（DeepSeek Harness 的 Web GUI 布局）。
 *
 * 分工：
 *
 * - 左侧栏承载"导航与上下文"——品牌、主操作（新建分析）、导航、最近运行、页脚；
 * - 中栏（默认插槽）承载"内容与输入"——由 `IncidentWorkspaceView` 决定；
 * - 内容由插槽注入，外壳本身不碰任何业务状态，`apiOnline` 也由父组件传进来。
 *
 * 历史抽屉的触发按钮放在侧栏导航里（`.rail-nav`）：它是模态对话框，
 * 关闭后焦点必须回到打开它的那个按钮上（P1-5-3），所以把按钮元素本身抛给父组件。
 */
import { ref } from 'vue'
import { Activity, BookOpen, Clock3, History, Plus, RefreshCw } from 'lucide-vue-next'

import BrandMark from '../components/BrandMark.vue'
import { formatRelativeTime } from '../utils/time'
import { runStatusTone } from '../constants/status'
import type { RunSummary } from '../types/api'

defineProps<{ apiOnline: boolean; recentRuns?: RunSummary[] }>()
const emit = defineEmits<{
  refresh: []
  history: [trigger: HTMLElement]
  newIncident: []
  selectRun: [run: RunSummary]
}>()

/**
 * 把触发按钮本身交给父组件：历史抽屉是模态对话框，关闭后焦点必须回到打开它的
 * 那个按钮上，否则键盘用户的焦点会掉回 `<body>`（P1-5-3）。
 */
const historyButton = ref<HTMLButtonElement | null>(null)

/** 状态点的色调（P1-5-5 的失败细分在抽屉里，这里只要一个颜色差异）。 */
function tone(run: RunSummary) {
  return runStatusTone(run.status, run.interrupted)
}
</script>

<template>
  <main class="app-shell">
    <aside class="side-rail" aria-label="应用导航">
      <div class="side-brand">
        <span class="brand-mark"><BrandMark :size="24" /></span>
        <span class="brand-name">Incident Agent</span>
      </div>

      <!-- 主操作：清空当前结果、回到空白表单（DSH 的「新会话」）。 -->
      <button class="side-action" type="button" @click="emit('newIncident')">
        <Plus :size="16" /> 新建分析
      </button>

      <nav class="rail-nav" aria-label="主导航">
        <button class="rail-button active" title="故障分析" aria-label="故障分析">
          <span class="rail-button-icon"><Activity :size="17" /></span>
          <span class="rail-label">故障分析</span>
        </button>
        <button class="rail-button" title="知识证据" aria-label="知识证据">
          <span class="rail-button-icon"><BookOpen :size="17" /></span>
          <span class="rail-label">知识证据</span>
        </button>
        <button
          ref="historyButton"
          class="rail-button"
          title="运行历史"
          aria-label="运行历史"
          @click="emit('history', historyButton as HTMLElement)"
        >
          <span class="rail-button-icon"><History :size="17" /></span>
          <span class="rail-label">运行历史</span>
        </button>
      </nav>

      <div class="side-region">
        <h2 class="side-group-title"><Clock3 :size="12" /> 最近运行</h2>
        <p v-if="!recentRuns?.length" class="side-hint">还没有运行记录。</p>
        <button
          v-for="run in recentRuns"
          :key="run.run_id"
          class="side-run"
          type="button"
          :title="run.title"
          :aria-label="`打开「${run.title}」`"
          @click="emit('selectRun', run)"
        >
          <span class="status-dot" :class="tone(run)"></span>
          <span class="side-run-title">{{ run.title }}</span>
          <span class="side-run-time">{{ formatRelativeTime(run.started_at) }}</span>
        </button>
        <button
          v-if="recentRuns?.length"
          class="side-more"
          type="button"
          @click="emit('history', historyButton as HTMLElement)"
        >
          查看全部
        </button>
      </div>

      <div class="rail-bottom">
        <div class="api-status" :class="{ online: apiOnline }">
          <span class="status-dot"></span>{{ apiOnline ? 'API ONLINE' : 'API OFFLINE' }}
        </div>
        <button class="rail-button" title="重新检查 API" aria-label="重新检查 API" @click="emit('refresh')">
          <span class="rail-button-icon"><RefreshCw :size="16" /></span>
          <span class="rail-label">重新检查 API</span>
        </button>
        <slot name="user" />
      </div>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <div class="topbar-title">
          <span class="eyebrow">INCIDENT / ANALYSIS</span>
          <h1>Incident Agent</h1>
        </div>
        <div class="topbar-actions">
          <slot name="status" />
          <button class="icon-button" type="button" title="重新检查 API" aria-label="重新检查 API" @click="emit('refresh')">
            <RefreshCw :size="16" />
          </button>
        </div>
      </header>
      <slot />
    </section>
  </main>
</template>
