<script setup lang="ts">
import { CircleUserRound, LogOut } from 'lucide-vue-next'
import type { User } from '../types/api'
defineProps<{ user: User }>()
const emit = defineEmits<{ logout: [] }>()
</script>
<template><div class="user-menu"><CircleUserRound :size="17" /><span>{{ user.username }}</span><button class="icon-button" title="退出登录" aria-label="退出登录" @click="emit('logout')"><LogOut :size="15" /></button></div></template>
