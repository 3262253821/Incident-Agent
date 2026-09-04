<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppLayout from '../layouts/AppLayout.vue'
import LoginForm from '../components/LoginForm.vue'
import { useAuthStore } from '../stores/auth'
import { checkHealth } from '../api/system'

const auth = useAuthStore(); const router = useRouter(); const apiOnline = ref(false)
async function submit(username: string, password: string) { await auth.signIn(username, password); router.push({ name: 'workspace' }) }
onMounted(async () => { try { await checkHealth(); apiOnline.value = true } catch { apiOnline.value = false } })
</script>
<template><AppLayout :api-online="apiOnline"><div class="auth-stage"><LoginForm :loading="auth.loading" :error="auth.error" @submit="submit" /></div></AppLayout></template>
