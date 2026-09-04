<script setup lang="ts">
import { Activity, Database, FileSearch, Network, Server, ShieldCheck } from 'lucide-vue-next'
import type { IncidentReport } from '../types/api'
defineProps<{ report: IncidentReport }>()
function sourceLabel(source: string) { return ({ fault_log: '故障日志', knowledge_base: '知识库', service_status: '服务状态', tool_error: '工具错误' } as Record<string, string>)[source] || source }
function categoryIcon(category: string) { return category === 'database' ? Database : category === 'network' ? Network : category === 'dependency' ? Server : Activity }
</script>
<template>
  <section class="panel report-panel"><div class="panel-heading"><div><span class="panel-index">03</span><h3>Validated report</h3></div><span class="confidence-tag"><ShieldCheck :size="14" /> {{ report.confidence.toUpperCase() }} CONFIDENCE</span></div>
    <div class="report-summary"><div class="category-icon"><component :is="categoryIcon(report.category)" :size="24" /></div><div><span class="report-category">{{ report.category }}</span><h4>{{ report.summary }}</h4></div></div>
    <div class="report-columns"><div><h5>证据</h5><div class="evidence-list"><article v-for="(item, index) in report.evidence" :key="index" class="evidence-item"><span class="evidence-source">{{ sourceLabel(item.source) }}</span><p>{{ item.detail }}</p><small v-if="item.filename"><FileSearch :size="12" /> {{ item.filename }} · chunk {{ item.chunk_index ?? '-' }}</small></article></div></div><div><h5>可能原因</h5><ul class="plain-list"><li v-for="cause in report.possible_causes" :key="cause">{{ cause }}</li></ul><h5 class="next-heading">排查步骤</h5><ol class="plain-list numbered"><li v-for="step in report.troubleshooting_steps" :key="step">{{ step }}</li></ol></div></div>
  </section>
</template>
