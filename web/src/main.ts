import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { TOKEN_STORAGE_KEY, onSessionExpired } from './api/client'
import { useAuthStore } from './stores/auth'
import { safeRedirect } from './utils/redirect'
import './styles.css'

/**
 * 统一的会话失效处理（P1-5-4）：**只在入口装配**，`api/client.ts` 本身不 import
 * router/store（那会把模块依赖拧成环：router → views → stores → api → client）。
 */
onSessionExpired(() => {
  try {
    // 先清本地会话：路由守卫只看 localStorage，清掉之后下一次导航才拦得住。
    useAuthStore().signOut()
  } catch (failure) {
    // 极端情况下（Pinia 还没装好）也不能让"清状态失败"挡住跳转，所以兜底直接清键。
    console.error('[app] 清会话失败，改为直接清除本地令牌', failure)
    localStorage.removeItem(TOKEN_STORAGE_KEY)
  }
  // 带上 redirect，用户重新登录后回到刚才那一页，而不是被丢回工作台首页。
  // `safeRedirect()` 只接受站内路径（防开放重定向）。
  const redirect = safeRedirect(`${window.location.pathname}${window.location.search}`)
  void router.replace({ name: 'login', query: { redirect } }).catch(() => {
    // 已经在登录页（或重复触发）：导航被守卫拦下不是错误，忽略即可。
  })
})

createApp(App).use(createPinia()).use(router).mount('#app')
