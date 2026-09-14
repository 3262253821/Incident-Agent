<script setup lang="ts">
import type { Observation } from '../types/api'

withDefaults(defineProps<{ observations: Observation[]; caption?: string }>(), {
  caption: '报告未通过校验',
})

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
