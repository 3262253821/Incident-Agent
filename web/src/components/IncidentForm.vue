<script setup lang="ts">
import { BookOpen, ChevronDown, LoaderCircle, Play, Search, TerminalSquare } from 'lucide-vue-next'

defineProps<{ running: boolean; error: string }>()
const emit = defineEmits<{ submit: [payload: { title: string; content: string; knowledge_base_id: number; top_k: number }] }>()
const title = defineModel<string>('title', { required: true })
const content = defineModel<string>('content', { required: true })
const knowledgeBaseId = defineModel<number>('knowledgeBaseId', { required: true })
const topK = defineModel<number>('topK', { required: true })
function submit() { emit('submit', { title: title.value.trim(), content: content.value.trim(), knowledge_base_id: knowledgeBaseId.value, top_k: topK.value }) }
</script>
<template>
  <section class="panel intake-panel"><div class="panel-heading"><div><span class="panel-index">01</span><h3>Incident brief</h3></div><span class="panel-caption">输入现场信息</span></div>
    <form class="incident-form" @submit.prevent="submit"><label>故障标题<input v-model="title" maxlength="200" required /></label><label>日志 / 现象<textarea v-model="content" maxlength="20000" rows="9" required></textarea></label>
      <div class="field-row"><label>知识库 ID<div class="number-input"><BookOpen :size="15" /><input v-model.number="knowledgeBaseId" type="number" min="1" required /></div></label><label>召回数量<div class="number-input"><Search :size="15" /><select v-model.number="topK"><option v-for="value in [3, 5, 8, 10]" :key="value" :value="value">Top {{ value }}</option></select><ChevronDown :size="14" /></div></label></div>
      <div class="form-footer"><span class="privacy-line"><TerminalSquare :size="14" /> 只读分析，不执行生产操作</span><button class="primary-button" type="submit" :disabled="running"><LoaderCircle v-if="running" class="spin" :size="17" /><Play v-else :size="17" />{{ running ? '分析中' : '开始分析' }}</button></div>
    </form><p v-if="error" class="form-error bottom-error">{{ error }}</p>
  </section>
</template>
