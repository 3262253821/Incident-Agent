<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { AlertTriangle } from 'lucide-vue-next'
import AppLayout from '../layouts/AppLayout.vue'
import UserMenu from '../components/UserMenu.vue'
import IncidentForm from '../components/IncidentForm.vue'
import ExecutionTrace from '../components/ExecutionTrace.vue'
import ReportPanel from '../components/ReportPanel.vue'
import DegradedPanel from '../components/DegradedPanel.vue'
import HistoryDrawer from '../components/HistoryDrawer.vue'
import { apiErrorMessage } from '../api/client'
import { checkHealth } from '../api/system'
import { RUN_STATUS, runStatusLabel, runStatusTone } from '../constants/status'
import { formatDuration } from '../utils/time'
import { useAuthStore } from '../stores/auth'
import { useIncidentStore } from '../stores/incident'
import type { RunSummary } from '../types/api'

const auth = useAuthStore()
const incident = useIncidentStore()
const apiOnline = ref(false)
const showHistory = ref(false)
const loadingMore = ref(false)

const title = ref('订单服务返回 502')
const content = ref(
  '网关返回 502，order-service 日志显示 MySQL connection timeout。请分析可能原因并给出排查顺序。',
)
const knowledgeBaseId = ref(3)
const topK = ref(5)

const error = computed(() => incident.error)
const runStatus = computed(() => incident.result?.status)
const runLabel = computed(() => {
  if (incident.running) return 'ANALYZING'
  if (!runStatus.value) return 'READY'
  return runStatusLabel(runStatus.value, incident.result?.interrupted)
})
const runTone = computed(() => {
  if (incident.running) return 'busy'
  if (!runStatus.value) return 'idle'
  return runStatusTone(runStatus.value, incident.result?.interrupted)
})
// 运行中还没有 completed_at，耗时由服务端在结束后给出。
const runDuration = computed(() => formatDuration(incident.result?.duration_ms))
// 报告通过校验（含证据不足）时展示报告；否则展示证据快照。
const showReport = computed(
  () =>
    Boolean(incident.result?.report) &&
    (runStatus.value === RUN_STATUS.COMPLETED ||
      runStatus.value === RUN_STATUS.INSUFFICIENT_EVIDENCE),
)
const evidenceCaption = computed(() =>
  runStatus.value === RUN_STATUS.INSUFFICIENT_EVIDENCE ? '未取得工具证据' : '报告未通过校验',
)

async function refreshHealth() {
  try {
    await checkHealth()
    apiOnline.value = true
  } catch {
    apiOnline.value = false
  }
}

async function submit(payload: {
  title: string
  content: string
  knowledge_base_id: number
  top_k: number
}) {
  try {
    await incident.analyze(payload)
  } catch (failure) {
    if (apiErrorMessage(failure).includes('401')) auth.signOut()
  }
}

async function openHistory() {
  try {
    await incident.loadHistory()
    showHistory.value = true
  } catch (failure) {
    incident.error = apiErrorMessage(failure)
  }
}

async function selectRun(run: RunSummary) {
  showHistory.value = false
  try {
    await incident.selectRun(run)
  } catch {
    // 错误已经写进 store，这里只负责不让抽屉挡住提示。
  }
}

async function loadMoreRuns() {
  loadingMore.value = true
  try {
    await incident.loadMoreHistory()
  } catch (failure) {
    incident.error = apiErrorMessage(failure)
  } finally {
    loadingMore.value = false
  }
}

onMounted(async () => {
  await refreshHealth()
  await auth.restore()
})
</script>

<template>
  <AppLayout :api-online="apiOnline" @refresh="refreshHealth" @history="openHistory">
    <template #user>
      <UserMenu v-if="auth.user" :user="auth.user" @logout="auth.signOut" />
    </template>
    <div class="dashboard">
      <section class="hero-row">
        <div>
          <div class="section-kicker">CONTROL ROOM / 01</div>
          <h2>故障初筛</h2>
          <p>让模型收集可追溯证据，再给出可执行的排查顺序。</p>
        </div>
        <div class="run-status" :class="runTone">
          <span class="status-dot"></span>
          <span>{{ runLabel }}</span>
          <span v-if="incident.result" class="status-id">
            {{ incident.result.run_id.slice(0, 8) }}
            <template v-if="runDuration"> · 耗时 {{ runDuration }}</template>
          </span>
        </div>
      </section>
      <div class="content-grid">
        <IncidentForm
          v-model:title="title"
          v-model:content="content"
          v-model:knowledge-base-id="knowledgeBaseId"
          v-model:top-k="topK"
          :running="incident.running"
          :error="error"
          @submit="submit"
        />
        <ExecutionTrace
          :running="incident.running"
          :steps="incident.result?.steps || []"
          :error="incident.result?.error || null"
        />
      </div>
      <ReportPanel
        v-if="showReport && incident.result?.report"
        :report="incident.result.report"
        :status="runStatus"
      />
      <DegradedPanel
        v-else-if="incident.result"
        :observations="incident.result.observations"
        :caption="evidenceCaption"
        :summary="incident.result.degraded_summary ?? null"
      />
      <p v-if="error && !incident.result" class="form-error bottom-error">
        <AlertTriangle :size="15" /> {{ error }}
      </p>
      <HistoryDrawer
        v-if="showHistory"
        :runs="incident.history"
        :has-more="Boolean(incident.nextCursor)"
        :loading-more="loadingMore"
        @close="showHistory = false"
        @select="selectRun"
        @load-more="loadMoreRuns"
      />
    </div>
  </AppLayout>
</template>
