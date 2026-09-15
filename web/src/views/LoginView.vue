<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import AppLayout from '../layouts/AppLayout.vue'
import LoginForm from '../components/LoginForm.vue'
import { useAuthStore } from '../stores/auth'
import { checkHealth } from '../api/system'
import { safeRedirect } from '../utils/redirect'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const apiOnline = ref(false)

/**
 * 登录成功后回到 `redirect` 指向的页面（P1-5-4）。
 *
 * 被 401 踢下来的用户是被守卫带到登录页的，地址栏里带着他原本要打开的页面
 * （`/login?redirect=/workspace?status=degraded`）；以前这里一律 `push({name:'workspace'})`，
 * 于是"重新登录后回到首页"——用户得自己再点回去。
 *
 * `redirect` 是用户可控输入，一律经 `safeRedirect()` 过滤（只接受站内路径）。
 */
async function submit(username: string, password: string) {
  await auth.signIn(username, password)
  router.push(safeRedirect(route.query.redirect))
}

onMounted(async () => {
  try {
    await checkHealth()
    apiOnline.value = true
  } catch {
    apiOnline.value = false
  }
})
</script>

<template>
  <AppLayout :api-online="apiOnline">
    <div class="auth-stage">
      <!--
        `auth.error` 在登录页有两种来源：登录失败（由表单自身展示），以及 P1-5-4 之后
        `restore()` 遇到"后端不可达"时写入的提示——用户被守卫带到登录页，必须看得到
        "为什么没自动登录进去"，而不是一个安静的空表单。
      -->
      <LoginForm
        :loading="auth.loading"
        :error="auth.error"
        @submit="submit"
      />
    </div>
  </AppLayout>
</template>
