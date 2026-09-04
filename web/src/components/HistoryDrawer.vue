<script setup lang="ts">
import { ArrowRight, X } from 'lucide-vue-next'
import type { RunResponse } from '../types/api'
defineProps<{ runs: RunResponse[] }>()
const emit = defineEmits<{ close: []; select: [run: RunResponse] }>()
</script>
<template><div class="history-drawer"><div class="drawer-heading"><div><span class="section-kicker">RECENT RUNS</span><h3>运行历史</h3></div><button class="icon-button" title="关闭历史" aria-label="关闭历史" @click="emit('close')"><X :size="18" /></button></div><button v-for="item in runs" :key="item.run_id" class="history-row" @click="emit('select', item)"><span class="history-status" :class="item.status"></span><span><strong>{{ item.run_id.slice(0, 12) }}</strong><small>{{ item.status }} · {{ item.observations.length }} observations</small></span><ArrowRight :size="16" /></button><p v-if="!runs.length" class="drawer-empty">暂时没有运行记录。</p></div></template>
