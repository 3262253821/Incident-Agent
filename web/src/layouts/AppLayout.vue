<script setup lang="ts">
import { ref } from 'vue'
import { Activity, BookOpen, History, RefreshCw } from 'lucide-vue-next'

defineProps<{ apiOnline: boolean }>()
const emit = defineEmits<{ refresh: []; history: [trigger: HTMLElement] }>()
/**
 * 把触发按钮本身交给父组件：历史抽屉是模态对话框，关闭后焦点必须回到打开它的
 * 那个按钮上，否则键盘用户的焦点会掉回 `<body>`（P1-5-3）。
 */
const historyButton = ref<HTMLButtonElement | null>(null)
</script>

<template>
  <main class="app-shell">
    <aside class="side-rail">
      <div class="brand-mark" aria-label="Signal Room">SR</div>
      <nav class="rail-nav" aria-label="主导航">
        <button class="rail-button active" title="故障分析" aria-label="故障分析"><Activity :size="19" /></button>
        <button class="rail-button" title="知识证据" aria-label="知识证据"><BookOpen :size="19" /></button>
        <button
          ref="historyButton"
          class="rail-button"
          title="运行历史"
          aria-label="运行历史"
          @click="emit('history', historyButton as HTMLElement)"
        >
          <History :size="19" />
        </button>
      </nav>
      <div class="rail-bottom">
        <button class="rail-button" title="重新检查 API" aria-label="重新检查 API" @click="emit('refresh')">
          <RefreshCw :size="18" />
        </button>
      </div>
    </aside>
    <section class="workspace">
      <header class="topbar">
        <div class="topbar-title">
          <span class="eyebrow">INCIDENT / ANALYSIS</span>
          <h1>Signal Room</h1>
        </div>
        <div class="topbar-actions">
          <div
            class="api-status"
            :class="{ online: apiOnline }"
          ><span class="status-dot"></span>{{ apiOnline ? 'API ONLINE' : 'API OFFLINE' }}</div>
          <slot name="user" />
        </div>
      </header>
      <slot />
    </section>
  </main>
</template>
