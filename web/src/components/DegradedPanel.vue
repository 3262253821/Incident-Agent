<script setup lang="ts">
import { computed } from 'vue'
import { AlertTriangle, ClipboardList, FileSearch, TerminalSquare } from 'lucide-vue-next'
import type { DegradedSummary, Observation } from '../types/api'

const props = withDefaults(
  defineProps<{
    observations: Observation[]
    caption?: string
    summary?: DegradedSummary | null
  }>(),
  { caption: '报告未通过校验', summary: null },
)

// 只有摘要里确实存在结构化事实时才渲染对应区块，避免出现空标题。
const hasSignals = computed(() => Boolean(props.summary?.log_signals.length))
const hasSources = computed(() => Boolean(props.summary?.knowledge_base_sources.length))
const hasStatuses = computed(() => Boolean(props.summary?.service_statuses.length))

function toolLabel(name: string) {
  return (
    ({
      analyze_log: '日志信号分析',
      search_knowledge: '知识库检索',
      get_service_status: '服务状态查询',
    } as Record<string, string>)[name] || name
  )
}
</script>

<template>
  <section class="panel degraded-panel">
    <div class="panel-heading">
      <div>
        <span class="panel-index">03</span>
        <h3>Evidence snapshot</h3>
      </div>
      <span class="panel-caption">{{ caption }}</span>
    </div>

    <div v-if="summary" class="degraded-summary">
      <p class="degraded-text">{{ summary.text }}</p>

      <div v-if="hasSignals" class="degraded-block">
        <h5><TerminalSquare :size="13" /> 已命中的日志信号</h5>
        <ul class="plain-list">
          <li v-for="(signal, index) in summary.log_signals" :key="index">
            {{ signal.type }}
            <span v-if="signal.line_number">（第 {{ signal.line_number }} 行）</span>
            <small v-if="signal.matched_text"> · {{ signal.matched_text }}</small>
          </li>
        </ul>
      </div>

      <div v-if="hasSources" class="degraded-block">
        <h5><FileSearch :size="13" /> 已检索到的知识库来源</h5>
        <ul class="plain-list">
          <li
            v-for="(source, index) in summary.knowledge_base_sources"
            :key="index"
          >
            {{ source.filename || '未命名文档' }}
            <small v-if="source.chunk_index !== null && source.chunk_index !== undefined">
              · chunk {{ source.chunk_index }}
            </small>
          </li>
        </ul>
      </div>

      <div v-if="hasStatuses" class="degraded-block">
        <h5>已查询到的服务状态</h5>
        <ul class="plain-list">
          <li v-for="(item, index) in summary.service_statuses" :key="index">
            {{ item }}
          </li>
        </ul>
      </div>

      <div v-if="summary.suggestions.length" class="degraded-block">
        <h5><ClipboardList :size="13" /> 建议人工核对</h5>
        <ol class="plain-list numbered">
          <li v-for="(item, index) in summary.suggestions" :key="index">{{ item }}</li>
        </ol>
      </div>
    </div>

    <p v-else class="degraded-hint">
      <AlertTriangle :size="14" /> 本次运行没有可用的结构化摘要。
    </p>

    <div class="observation-grid">
      <article
        v-for="(item, index) in observations"
        :key="item.tool_call_id || index"
        class="observation-card"
      >
        <div>
          <span class="observation-index">0{{ index + 1 }}</span>
          <strong>{{ toolLabel(item.tool_name) }}</strong>
        </div>
        <span :class="item.result.ok ? 'ok-label' : 'fail-label'">
          {{ item.result.ok ? 'SUCCESS' : item.result.error_code }}
        </span>
      </article>
    </div>
  </section>
</template>
