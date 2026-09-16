<script setup lang="ts">
import { computed, ref } from 'vue'
import { BookOpen, ChevronDown, LoaderCircle, Play, Search, TerminalSquare } from 'lucide-vue-next'

import type { FailureExplanation, FieldErrorHints } from '../utils/apiErrors'
import type { KnowledgeBaseOption } from '../types/api'

const props = defineProps<{
  running: boolean
  error: string
  knowledgeBases: KnowledgeBaseOption[]
  loadingKnowledgeBases: boolean
  knowledgeBaseError: string
  /** 422 的字段级提示（P1-5-6），来自 store 对后端 `detail[].loc` 的映射。 */
  fieldErrors?: FieldErrorHints
  /** 失败大类与建议（P1-5-6）。 */
  failureHint?: FailureExplanation
  /** 重跑时带过来的说明（P1-5-5）：哪些字段没被复用。 */
  notice?: string
}>()
const emit = defineEmits<{
  submit: [payload: { title: string; content: string; knowledge_base_id: number; top_k: number }]
  reloadKnowledgeBases: []
}>()
const title = defineModel<string>('title', { required: true })
const content = defineModel<string>('content', { required: true })
const knowledgeBaseId = defineModel<number | null>('knowledgeBaseId', { required: true })
const topK = defineModel<number>('topK', { required: true })
/** 提交前的字段级提示：知识库是必选，空值绝不能变成 NaN 发给服务端。 */
const fieldError = ref('')

const EMPTY_HINTS: FieldErrorHints = { fields: {}, general: '' }

const knowledgeBasePlaceholder = computed(() => {
  if (props.loadingKnowledgeBases) return '加载中…'
  if (props.knowledgeBaseError) return '加载失败'
  if (!props.knowledgeBases.length) return '没有可用知识库'
  return '请选择知识库'
})

/** 服务端返回的字段错误（本地校验通过之后才轮到它们）。 */
const serverFieldErrors = computed(() => props.fieldErrors ?? EMPTY_HINTS)

/**
 * 知识库下拉下面那一行提示。
 *
 * 优先级：加载失败 > 账号下没有库 > 本地校验（没选库）> 服务端说这个字段有问题。
 * 一次只显示一条——同一时刻用户只需要知道"这一格现在该怎么办"。
 */
const knowledgeBaseMessage = computed(() => {
  if (props.knowledgeBaseError) return props.knowledgeBaseError
  if (!props.loadingKnowledgeBases && !props.knowledgeBases.length) {
    return '当前账号没有可用知识库，请先在 DevAtlas 创建。'
  }
  if (fieldError.value) return fieldError.value
  return serverFieldErrors.value.fields.knowledge_base_id ?? ''
})

/** 底部告警：整句文案 + 失败大类建议（两者可以同时存在）。 */
const bottomMessage = computed(() => {
  const parts = [props.error, props.failureHint?.hint].filter(Boolean)
  return parts.join(' ')
})

function submit() {
  const selected = knowledgeBaseId.value
  if (selected === null || !Number.isInteger(selected) || selected < 1) {
    fieldError.value = '请先选择要检索的知识库'
    return
  }
  fieldError.value = ''
  emit('submit', {
    title: title.value.trim(),
    content: content.value.trim(),
    knowledge_base_id: selected,
    top_k: topK.value,
  })
}
</script>

<template>
  <section class="panel intake-panel">
    <div class="panel-heading">
      <div>
        <span class="panel-index">01</span>
        <h3>Incident brief</h3>
      </div>
      <span class="panel-caption">输入现场信息</span>
    </div>
    <form class="incident-form" @submit.prevent="submit">
      <!--
        字段级提示（P1-5-6）：错误紧贴对应控件，而不是只在页面底部给一句整句。
        注意模板空白是有语义的（P1-5-1/§9-14）：`<input>` 与 `<p>` 相邻且分行时，
        `whitespace: 'condense'` 会把换行吃掉，所以 `p` 写在标签**内部**、与 input 换行。
      -->
      <label>故障标题<input
        id="incident-title"
        v-model="title"
        maxlength="200"
        required
      /><p
        v-if="serverFieldErrors.fields.title"
        class="form-error field-inline"
        role="alert"
      >{{ serverFieldErrors.fields.title }}</p></label>
      <label>日志 / 现象<textarea v-model="content" maxlength="20000" rows="9" required></textarea>
        <p
          v-if="serverFieldErrors.fields.content"
          class="form-error field-inline"
          role="alert"
        >{{ serverFieldErrors.fields.content }}</p></label>
      <div class="field-row">
        <label>知识库<div class="number-input">
          <BookOpen :size="15" />
          <select v-model.number="knowledgeBaseId" :disabled="loadingKnowledgeBases || !knowledgeBases.length" required>
            <option :value="null" disabled>{{ knowledgeBasePlaceholder }}</option>
            <option
              v-for="option in knowledgeBases"
              :key="option.id"
              :value="option.id"
            >{{ option.name }}（#{{ option.id }}）</option>
          </select>
          <ChevronDown :size="14" />
        </div></label>
        <label>召回数量<div class="number-input">
          <Search :size="15" />
          <select v-model.number="topK">
            <option v-for="value in [3, 5, 8, 10]" :key="value" :value="value">Top {{ value }}</option>
          </select>
          <ChevronDown :size="14" />
        </div></label>
      </div>
      <p
        v-if="serverFieldErrors.fields.top_k"
        class="form-error field-inline"
        role="alert"
      >{{ serverFieldErrors.fields.top_k }}</p>
      <p
        v-if="knowledgeBaseError"
        class="form-error field-note"
        role="alert"
      >{{ knowledgeBaseMessage }}<button
        type="button"
        class="field-action"
        @click="emit('reloadKnowledgeBases')"
      >重新加载</button></p>
      <p
        v-else-if="knowledgeBaseMessage"
        class="form-error field-note"
        role="alert"
      >{{ knowledgeBaseMessage }}</p>
      <!-- 重跑说明：标题与知识库已复用，日志正文与召回数量不在历史契约里（P1-5-5）。 -->
      <p v-if="notice" class="field-note prefill-note">{{ notice }}</p>
      <p v-if="serverFieldErrors.general" class="form-error field-note" role="alert">
        {{ serverFieldErrors.general }}
      </p>
      <div class="form-footer">
        <span class="privacy-line"><TerminalSquare :size="14" /> 只读分析，不执行生产操作</span>
        <button
          class="primary-button"
          type="submit"
          :disabled="running"
          :aria-busy="running"
        ><LoaderCircle v-if="running" class="spin" :size="17" /><Play v-else :size="17" />{{ running ? '分析中' : '开始分析' }}</button>
      </div>
    </form>
    <p v-if="bottomMessage" class="form-error bottom-error" role="alert">{{ bottomMessage }}</p>
  </section>
</template>
