import { createRouter, createWebHistory } from 'vue-router'
import type { RouteLocationNormalized } from 'vue-router'

import { TOKEN_STORAGE_KEY } from '../api/client'
import LoginView from '../views/LoginView.vue'
import IncidentWorkspaceView from '../views/IncidentWorkspaceView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/workspace' },
    { path: '/login', name: 'login', component: LoginView, meta: { guestOnly: true } },
    { path: '/workspace', name: 'workspace', component: IncidentWorkspaceView, meta: { requiresAuth: true } },
  ],
})

/**
 * 守卫只判断"本地有没有令牌"，不判断令牌是否还有效（P1-5-4 保持这个分工）。
 *
 * 为什么有意不去校验有效性：守卫里没有可用的同步校验手段，异步校验会让每次导航都
 * 多打一次接口。令牌真正失效时，**任意一个接口**都会返回 401，响应拦截器统一清掉
 * 令牌并跳到这里带 `redirect` 的登录页（`src/main.ts`）。这也正是"401 之后仍要跳
 * 登录页"能成立的原因：拦截器清的是 `localStorage`，守卫读的也是 `localStorage`。
 */
export function requiresSession(to: RouteLocationNormalized) {
  const hasToken = Boolean(localStorage.getItem(TOKEN_STORAGE_KEY))
  if (to.meta.requiresAuth && !hasToken) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.guestOnly && hasToken) return { name: 'workspace' }
  return undefined
}

router.beforeEach(requiresSession)

export default router
