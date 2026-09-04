<script setup lang="ts">
import { AlertTriangle, Check, FileSearch, LoaderCircle, X } from 'lucide-vue-next'
import type { AgentStep } from '../types/api'
defineProps<{ running: boolean; steps: AgentStep[]; error: string | null }>()
function toolLabel(name: string) { return ({ analyze_log: '日志信号分析', search_knowledge: '知识库检索', get_service_status: '服务状态查询' } as Record<string, string>)[name] || name }
function nodeLabel(node: string) { return ({ agent: '模型决策', observe: '整理观察', report: '生成报告', degrade: '降级结束', limit: '循环保护' } as Record<string, string>)[node] || node }
</script>
<template>
  <section class="panel trace-panel"><div class="panel-heading"><div><span class="panel-index">02</span><h3>Execution trace</h3></div><span class="panel-caption">实时轨迹</span></div>
    <div v-if="!steps.length && !running" class="trace-empty"><div class="empty-icon"><FileSearch :size="22" /></div><strong>等待一次分析</strong><span>模型请求、工具结果和状态变化会显示在这里。</span></div>
    <div v-else class="trace-list"><div v-if="running" class="trace-item active-trace"><span class="trace-marker"><LoaderCircle class="spin" :size="14" /></span><div><strong>模型正在收集证据</strong><small>请求 DevAtlas 与服务状态工具</small></div><span class="trace-time">LIVE</span></div>
      <div v-for="(step, index) in steps" :key="`${step.step_index}-${index}`" class="trace-item"><span class="trace-marker" :class="step.status === 'success' ? 'success' : 'failure'"><Check v-if="step.status === 'success'" :size="13" /><X v-else :size="13" /></span><div><strong>{{ nodeLabel(step.node) }}</strong><small>{{ step.tool_name ? toolLabel(step.tool_name) : step.action }}</small></div><span class="trace-time">R{{ step.iteration }}</span></div>
      <div v-if="error" class="trace-alert"><AlertTriangle :size="16" /><span>{{ error }}</span></div>
    </div>
  </section>
</template>
