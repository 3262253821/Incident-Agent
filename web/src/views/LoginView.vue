<script setup lang="ts">
import { useRouter } from 'vue-router'
import AppLayout from '../layouts/AppLayout.vue'
import LoginForm from '../components/LoginForm.vue'
import { useAuthStore } from '../stores/auth'
const auth = useAuthStore(); const router = useRouter()
async function submit(username: string, password: string) { await auth.signIn(username, password); router.push({ name: 'workspace' }) }
</script>
<template><AppLayout :api-online="false"><div class="auth-stage"><LoginForm :loading="auth.loading" :error="auth.error" @submit="submit" /></div></AppLayout></template>
