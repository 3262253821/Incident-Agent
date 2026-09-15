<script setup lang="ts">
import { computed, ref } from 'vue'
import { BookOpen, ChevronDown, LoaderCircle, Play, Search, TerminalSquare } from 'lucide-vue-next'

import type { KnowledgeBaseOption } from '../types/api'

const props = defineProps<{
  running: boolean
  error: string
  knowledgeBases: KnowledgeBaseOption[]
  loadingKnowledgeBases: boolean
  knowledgeBaseError: string
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

const knowledgeBasePlaceholder = computed(() => {
  if (props.loadingKnowledgeBases) return '加载中…'
  if (props.knowledgeBaseError) return '加载失败'
  if (!props.knowledgeBases.length) return '没有可用知识库'
  return '请选择知识库'
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
      <label>故障标题<input v-model="title" maxlength="200" required /></label>
      <label>日志 / 现象<textarea v-model="content" maxlength="20000" rows="9" required></textarea></label>
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
      <p v-if="knowledgeBaseError" class="form-error field-note">{{ knowledgeBaseError }}<button
        type="button"
        class="field-action"
        @click="emit('reloadKnowledgeBases')"
      >重新加载</button></p>
      <p
        v-else-if="!loadingKnowledgeBases && !knowledgeBases.length"
        class="form-error field-note"
      >当前账号没有可用知识库，请先在 DevAtlas 创建。</p>
      <p v-else-if="fieldError" class="form-error field-note">{{ fieldError }}</p>
      <div class="form-footer">
        <span class="privacy-line"><TerminalSquare :size="14" /> 只读分析，不执行生产操作</span>
        <button
          class="primary-button"
          type="submit"
          :disabled="running"
        ><LoaderCircle v-if="running" class="spin" :size="17" /><Play v-else :size="17" />{{ running ? '分析中' : '开始分析' }}</button>
      </div>
    </form>
    <p v-if="error" class="form-error bottom-error">{{ error }}</p>
  </section>
</template>
