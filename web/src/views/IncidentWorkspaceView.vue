<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { AlertTriangle, Database, Network, Server } from 'lucide-vue-next'
import AppLayout from '../layouts/AppLayout.vue'
import UserMenu from '../components/UserMenu.vue'
import BrandMark from '../components/BrandMark.vue'
import IncidentForm from '../components/IncidentForm.vue'
import ExecutionTrace from '../components/ExecutionTrace.vue'
import ReportPanel from '../components/ReportPanel.vue'
import DegradedPanel from '../components/DegradedPanel.vue'
import HistoryDrawer from '../components/HistoryDrawer.vue'
import StatusAnnouncer from '../components/StatusAnnouncer.vue'
import { apiErrorMessage } from '../api/client'
import { listKnowledgeBases } from '../api/knowledgeBases'
import { checkHealth } from '../api/system'
import { historyQuery } from '../utils/apiErrors'
import type { StatusFilter, TimeRangeFilter } from '../utils/apiErrors'
import { failureDetail } from '../utils/failingRun'
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
/** 抽屉里的筛选条件（P1-5-5）；变化时重新拉第一页，翻页由 store 带上同一组条件。 */
const statusFilter = ref<StatusFilter>('all')
const timeRange = ref<TimeRangeFilter>('all')
/** 重跑后给表单的说明：哪些字段没被复用、为什么（P1-5-5）。 */
const prefillNotice = ref('')
/** 重跑后把焦点送回表单第一格，否则键盘/读屏用户还停在已关闭的抽屉上。 */
const formPanel = ref<{ $el?: HTMLElement } | null>(null)
/** 分析状态与失败原因的读屏播报文案（P1-5-3），由 `StatusAnnouncer` 渲染。 */
const announcement = ref('')
/** 结果区容器：分析结束后滚到这里，否则结果会停在输入卡片下方的屏外。 */
const results = ref<HTMLElement | null>(null)

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

/**
 * 示例芯片：点一下就把现场信息写进表单。
 *
 * 只预填「标题 + 日志」，**不动知识库与召回数量**——那两个是用户账号下的真实资源，
 * 替他选一个再提交，会让"我明明没选过"变成一次静默的越权检索。
 */
const SUGGESTIONS = [
  {
    label: '订单服务 502',
    title: '订单服务返回 502',
    content: '网关返回 502，order-service 日志显示 MySQL connection timeout。请分析可能原因并给出排查顺序。',
  },
  {
    label: '数据库连接池耗尽',
    title: '数据库连接池耗尽',
    content:
      'order-service 大量请求超时，日志出现 HikariPool-1 - Connection is not available, request timed out after 30000ms。请分析原因与排查顺序。',
  },
  {
    label: '上游依赖超时',
    title: '支付回调上游超时',
    content: '支付回调服务调用 pay-gateway 出现 read timeout，重试后仍失败。请判断是网络、依赖还是自身线程池问题。',
  },
]

function applySuggestion(suggestion: (typeof SUGGESTIONS)[number]) {
  title.value = suggestion.title
  content.value = suggestion.content
}

const error = computed(() => incident.error || auth.error)
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
/** 最近运行（侧栏列表）：只取前 5 条，完整列表与筛选在抽屉里。 */
const recentRuns = computed(() => incident.history.slice(0, 5))
/**
 * 报告分类对应的小图标，放在结果标题前——让"这次是数据库还是网络问题"一眼可辨，
 * 不必读完整段摘要。
 */
const categoryIcon = computed(() => {
  const category = incident.result?.report?.category
  return category === 'database'
    ? Database
    : category === 'network'
      ? Network
      : category === 'dependency'
        ? Server
        : AlertTriangle
})

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

/**
 * 结果出现后把它滚进视野。
 *
 * `scrollIntoView` 在 jsdom 里不存在（组件测试会直接 TypeError），所以先判存在性——
 * 这不是防御性写法，而是"这段代码必须在测试环境里可运行"的硬要求。
 */
watch(
  () => incident.result,
  async (result) => {
    if (!result) return
    await nextTick()
    results.value?.scrollIntoView?.({ behavior: 'smooth', block: 'start' })
  },
)

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

/**
 * 「新建分析」：回到空白欢迎态。
 *
 * 清掉结果与告警，但**保留表单里已经填好的内容**——用户点它多半是想再跑一次别的现场，
 * 而不是想让自己刚写的日志消失。
 */
function newIncident() {
  incident.result = null
  incident.error = ''
  prefillNotice.value = ''
  results.value = null
}

/**
 * 提交分析（P1-5-4 去掉了这里的登出判断）。
 *
 * 旧写法是 `if (apiErrorMessage(failure).includes('401')) auth.signOut()`——把错误
 * 文案当控制流：`apiErrorMessage()` 优先返回后端的中文 `detail`，这条判断在真实响应
 * 上根本不会命中。现在**只有响应拦截器**按 HTTP 状态码处理会话失效（清 Token +
 * 带 redirect 跳登录页），这里只负责让错误留在 store 里给界面用。
 */
async function submit(payload: {
  title: string
  content: string
  knowledge_base_id: number
  top_k: number
}) {
  try {
    await incident.analyze(payload)
    // 跑完顺手刷新侧栏的最近运行，否则刚跑完的那条要重开抽屉才出现。
    await refreshRecentRuns()
  } catch {
    // 错误文案已经写进 store（`incident.analyze` 的 catch），这里不做第二次处理。
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
    await loadHistory()
    showHistory.value = true
  } catch (failure) {
    incident.error = apiErrorMessage(failure)
  }
}

/** 重新拉第一页：打开抽屉、或筛选条件变化时调用。 */
async function loadHistory() {
  return incident.loadHistory(historyQuery(statusFilter.value, timeRange.value))
}

/** 侧栏的「最近运行」：不带筛选拉第一页即可。 */
async function refreshRecentRuns() {
  try {
    await incident.loadHistory(historyQuery('all', 'all'))
  } catch {
    // 侧栏列表是次要信息：拉不到就保持空态，不弹告警打断正在看的结果。
  }
}

/** 抽屉里换了筛选档位：重查第一页（游标失效，必须从第一页开始）。 */
async function onStatusFilterChange(value: StatusFilter) {
  statusFilter.value = value
  await reloadHistory()
}

async function onTimeRangeChange(value: TimeRangeFilter) {
  timeRange.value = value
  await reloadHistory()
}

async function reloadHistory() {
  try {
    await loadHistory()
  } catch (failure) {
    incident.error = apiErrorMessage(failure)
  }
}

/**
 * 用一条历史记录重跑（P1-5-5）。
 *
 * **只能复用摘要里真实存在的字段**：`RunSummary`/`RunResponse` 都没有原始日志
 * （`content`）与 `top_k`——设计文档 §12.1 只要求存摘要。所以这里回填标题与知识库，
 * 并明确告诉用户日志要重新粘贴，而不是假装"一键重跑"。
 */
async function rerun(run: RunSummary) {
  showHistory.value = false
  title.value = run.title
  knowledgeBaseId.value = run.knowledge_base_id
  const missing = ['日志正文', '召回数量']
  if (run.status !== RUN_STATUS.COMPLETED) missing.push('失败原因明细')
  prefillNotice.value = `已按「${run.title}」回填标题与知识库（#${run.knowledge_base_id}）；${missing.join('、')}不在历史记录里，请重新填写。失败细分：${failureDetail(run)}`
  await nextTick()
  const root = formPanel.value?.$el
  root?.querySelector<HTMLInputElement>('input, textarea, select')?.focus()
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

/**
 * 首屏：健康检查 → 恢复会话 → 拉知识库。
 *
 * 历史/最近运行只在**确认有令牌**之后才拉（`auth.user` 有值）：令牌无效时两个接口
 * 都会 401，响应拦截器会顺手把用户踢到登录页——而这一次自动跳转并不是用户的行为。
 * 与 `loadKnowledgeBases` 同一条件，见 `IncidentWorkspaceView.spec.ts`「令牌无效时不
 * 拉知识库」。
 */
onMounted(async () => {
  await refreshHealth()
  await auth.restore()
  if (!auth.user) return
  await loadKnowledgeBases()
  await refreshRecentRuns()
})
</script>

<template>
  <AppLayout
    :api-online="apiOnline"
    :recent-runs="recentRuns"
    @refresh="refreshHealth"
    @history="openHistory"
    @new-incident="newIncident"
    @select-run="selectRun"
  >
    <template #user>
      <UserMenu v-if="auth.user" :user="auth.user" @logout="auth.signOut" />
    </template>
    <template #status>
      <div class="run-status" :class="runTone" role="status" aria-atomic="true">
        <span class="status-dot"></span>
        <span>{{ runLabel }}</span>
        <span v-if="incident.result" class="status-id">
          {{ incident.result.run_id.slice(0, 8) }}
          <template v-if="runDuration"> · 耗时 {{ runDuration }}</template>
        </span>
      </div>
    </template>

    <div class="dashboard">
      <div class="column">
        <StatusAnnouncer :message="announcement" />

        <!--
          欢迎态只在"还没有任何结果"时出现：一旦跑过一次，中栏就变成结果流，
          标题不再重复（DSH 首屏与会话页也是这个差别）。
        -->
        <section v-if="!incident.result" class="welcome">
          <div class="welcome-brand">
            <BrandMark :size="30" />
            <h2>Incident Agent</h2>
          </div>
          <p class="welcome-subtitle">
            把现场日志交给 Agent：它只读地调用检索与状态工具收集证据，再按证据给出可执行的排查顺序。
          </p>
          <div class="suggestion-row">
            <button
              v-for="item in SUGGESTIONS"
              :key="item.label"
              class="suggestion-chip"
              type="button"
              @click="applySuggestion(item)"
            >
              {{ item.label }}
            </button>
          </div>
        </section>

        <IncidentForm
          ref="formPanel"
          v-model:title="title"
          v-model:content="content"
          v-model:knowledge-base-id="knowledgeBaseId"
          v-model:top-k="topK"
          :running="incident.running"
          :error="error"
          :knowledge-bases="knowledgeBases"
          :loading-knowledge-bases="loadingKnowledgeBases"
          :knowledge-base-error="knowledgeBaseError"
          :field-errors="incident.fieldErrors"
          :failure-hint="incident.failureHint"
          :notice="prefillNotice"
          @submit="submit"
          @reload-knowledge-bases="loadKnowledgeBases"
        />

        <!-- 结果流：轨迹 → 报告 / 证据快照，按时间顺序接在输入卡片下方。 -->
        <div ref="results" class="results">
          <div v-if="incident.result" class="result-bar">
            <span class="result-title">
              <component :is="categoryIcon" :size="13" />
              {{ incident.result.title }}
            </span>
            <button class="field-action" type="button" @click="newIncident">新建分析</button>
          </div>
          <ExecutionTrace
            :running="incident.running"
            :steps="incident.result?.steps || []"
            :error="incident.result?.error || null"
          />
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
        </div>

        <p v-if="error && !incident.result" class="form-error bottom-error" role="alert">
          <AlertTriangle :size="15" /> {{ error }}
        </p>
      </div>

      <HistoryDrawer
        v-if="showHistory"
        :runs="incident.history"
        :has-more="Boolean(incident.nextCursor)"
        :loading-more="loadingMore"
        :status-filter="statusFilter"
        :time-range="timeRange"
        @close="showHistory = false"
        @select="selectRun"
        @load-more="loadMoreRuns"
        @rerun="rerun"
        @update:status-filter="onStatusFilterChange"
        @update:time-range="onTimeRangeChange"
      />
    </div>
  </AppLayout>
</template>
