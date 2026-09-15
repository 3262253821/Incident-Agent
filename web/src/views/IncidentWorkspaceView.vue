<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { AlertTriangle } from 'lucide-vue-next'
import AppLayout from '../layouts/AppLayout.vue'
import UserMenu from '../components/UserMenu.vue'
import IncidentForm from '../components/IncidentForm.vue'
import ExecutionTrace from '../components/ExecutionTrace.vue'
import ReportPanel from '../components/ReportPanel.vue'
import DegradedPanel from '../components/DegradedPanel.vue'
import HistoryDrawer from '../components/HistoryDrawer.vue'
import StatusAnnouncer from '../components/StatusAnnouncer.vue'
import { apiErrorMessage } from '../api/client'
import { listKnowledgeBases } from '../api/knowledgeBases'
import { checkHealth } from '../api/system'
import {
  RUN_STATUS,
  runStatusAnnouncement,
  runStatusLabel,
  runStatusTone,
} from '../constants/status'
import { formatDuration } from '../utils/time'
import { useAuthStore } from '../stores/auth'
import { useIncidentStore } from '../stores/incident'
import type { KnowledgeBaseOption, RunSummary } from '../types/api'

const auth = useAuthStore()
const incident = useIncidentStore()
const apiOnline = ref(false)
const showHistory = ref(false)
const loadingMore = ref(false)
/** 分析状态与失败原因的读屏播报文案（P1-5-3），由 `StatusAnnouncer` 渲染。 */
const announcement = ref('')

const title = ref('订单服务返回 502')
const content = ref(
  '网关返回 502，order-service 日志显示 MySQL connection timeout。请分析可能原因并给出排查顺序。',
)
/**
 * 知识库不再硬编码：这里是"选中的知识库"，初始为空，登录后由
 * `GET /api/v1/knowledge-bases` 填进来（真实演示库 ID 不是固定值）。
 */
const knowledgeBaseId = ref<number | null>(null)
const knowledgeBases = ref<KnowledgeBaseOption[]>([])
const loadingKnowledgeBases = ref(false)
const knowledgeBaseError = ref('')
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

/**
 * 状态播报（P1-5-3）。
 *
 * 先看 `running`：分析进行中时还没有 run 记录，`runStatus` 是空的；两个 watch 在
 * 同一次刷新里先后触发，最后一次赋值决定屏幕阅读器读到的内容，所以终态优先于
 * "正在分析"。失败时用错误文案覆盖——它对读屏用户比状态词更有用。
 */
watch(
  () => incident.running,
  (running) => {
    if (running) announcement.value = '正在分析，模型正在收集证据。'
  },
)

watch(runStatus, (status) => {
  const message = runStatusAnnouncement(status, incident.result?.interrupted)
  if (message) announcement.value = message
})

watch(error, (message) => {
  if (message) announcement.value = `分析失败：${message}`
})

async function refreshHealth() {
  try {
    await checkHealth()
    apiOnline.value = true
  } catch {
    apiOnline.value = false
  }
}

/**
 * 拉取当前账号可选的知识库。
 *
 * 保留用户已经选中的项；它不在新列表里（例如换了账号）时退回第一项。列表为空时
 * 保持 `null`，由表单给出"请选择知识库"的提示，而不是把空值当数字发给服务端。
 */
async function loadKnowledgeBases() {
  loadingKnowledgeBases.value = true
  knowledgeBaseError.value = ''
  try {
    const options = await listKnowledgeBases()
    knowledgeBases.value = options
    const stillAvailable = options.some((option) => option.id === knowledgeBaseId.value)
    if (!stillAvailable) knowledgeBaseId.value = options.length ? options[0].id : null
  } catch (failure) {
    knowledgeBases.value = []
    knowledgeBaseId.value = null
    knowledgeBaseError.value = apiErrorMessage(failure)
  } finally {
    loadingKnowledgeBases.value = false
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

/**
 * 打开历史抽屉。
 *
 * 抽屉自己会在挂载时记住 `document.activeElement` 并在卸载时把焦点还回去——按
 * 按钮的那一刻按钮就是活动元素，所以这里不需要再传触发者。`AppLayout` 仍然把
 * 按钮作为事件载荷发出来（见 `forms.spec.ts`），那是留给"将来改成显式传递"的
 * 接口，目前没有第二个消费者。
 */
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
  // 令牌有效才有必要拉知识库；令牌无效时由登录页接管。
  if (auth.user) await loadKnowledgeBases()
})
</script>

<template>
  <AppLayout :api-online="apiOnline" @refresh="refreshHealth" @history="openHistory">
    <template #user>
      <UserMenu v-if="auth.user" :user="auth.user" @logout="auth.signOut" />
    </template>
    <div class="dashboard">
      <StatusAnnouncer :message="announcement" />
      <section class="hero-row">
        <div>
          <div class="section-kicker">CONTROL ROOM / 01</div>
          <h2>故障初筛</h2>
          <p>让模型收集可追溯证据，再给出可执行的排查顺序。</p>
        </div>
        <div class="run-status" :class="runTone" role="status" aria-atomic="true">
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
          :knowledge-bases="knowledgeBases"
          :loading-knowledge-bases="loadingKnowledgeBases"
          :knowledge-base-error="knowledgeBaseError"
          @submit="submit"
          @reload-knowledge-bases="loadKnowledgeBases"
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
      <p v-if="error && !incident.result" class="form-error bottom-error" role="alert">
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
