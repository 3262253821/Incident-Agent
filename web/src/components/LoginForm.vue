<script setup lang="ts">
import { ref } from 'vue'
import { ArrowRight, AlertTriangle, LoaderCircle, ShieldCheck } from 'lucide-vue-next'

defineProps<{
  loading: boolean
  error: string
}>()
const emit = defineEmits<{ submit: [username: string, password: string] }>()
const username = ref('')
const password = ref('')
</script>

<template>
  <div class="auth-panel">
    <div class="auth-kicker"><ShieldCheck :size="15" /> DEVATLAS IDENTITY</div>
    <h2>进入故障分析台</h2>
    <p>使用 DevAtlas 账号登录，Agent 会沿用你的知识库权限。</p>
    <form @submit.prevent="emit('submit', username, password)">
      <label>用户名<input
        v-model="username"
        autocomplete="username"
        required
        placeholder="输入 DevAtlas 用户名"
      /></label>
      <label>密码<input
        v-model="password"
        type="password"
        autocomplete="current-password"
        required
        placeholder="输入密码"
      /></label>
      <p v-if="error" class="form-error" role="alert"><AlertTriangle :size="15" /> {{ error }}</p>
      <button
        class="primary-button full"
        type="submit"
        :disabled="loading"
        :aria-busy="loading"
      ><LoaderCircle v-if="loading" class="spin" :size="17" /><ArrowRight v-else :size="17" />{{ loading ? '验证中' : '登录并进入' }}</button>
    </form>
    <div class="auth-note"><ShieldCheck :size="14" /> Token 只在当前浏览器会话中使用，不写入 Agent 数据库。</div>
  </div>
</template>
