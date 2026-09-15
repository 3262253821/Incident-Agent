import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { currentUser, login } from '../api/auth'
import { TOKEN_STORAGE_KEY, apiErrorMessage, isAuthFailure } from '../api/client'
import type { User } from '../types/api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem(TOKEN_STORAGE_KEY) || '')
  const user = ref<User | null>(null)
  const loading = ref(false)
  const error = ref('')
  const isAuthenticated = computed(() => Boolean(token.value && user.value))

  async function signIn(username: string, password: string) {
    loading.value = true
    error.value = ''
    try {
      const response = await login(username.trim(), password)
      token.value = response.access_token
      user.value = response.user
      localStorage.setItem(TOKEN_STORAGE_KEY, response.access_token)
    } catch (failure) {
      error.value = apiErrorMessage(failure)
      throw failure
    } finally {
      loading.value = false
    }
  }

  /**
   * 用本地保存的令牌恢复登录态（P1-5-4 改了失败分支）。
   *
   * 以前是 `catch { signOut() }`：**任何**异常都清令牌，于是 Agent 没启动、网络抖动、
   * DevAtlas 暂时 503 都会把用户踢到登录页，而他手上的令牌其实还是好的。
   *
   * 现在按失败类型分流：
   *
   * - **认证失败（HTTP 401/403）**：令牌真的失效了 → 清令牌并交给统一的会话失效
   *   处理（响应拦截器已经这么做了，这里再调一次是为了"没有拦截器时的直接调用"
   *   也保持一致，`signOut()` 幂等）；
   * - **连接失败 / 超时 / 上游 5xx**：只在 `error` 里给出提示，**保留令牌**，
   *   用户可以原地重试。
   *
   * 注意：`restore()` 失败不代表"用户没登录"，只代表"这一次没问出来"。
   */
  async function restore() {
    if (!token.value) return
    error.value = ''
    try {
      user.value = await currentUser()
    } catch (failure) {
      if (isAuthFailure(failure)) {
        signOut()
        return
      }
      error.value = apiErrorMessage(failure)
    }
  }

  /** 清掉本地会话。幂等：401 时拦截器与 `restore()` 可能各调用一次。 */
  function signOut() {
    token.value = ''
    user.value = null
    localStorage.removeItem(TOKEN_STORAGE_KEY)
  }

  return { token, user, loading, error, isAuthenticated, signIn, restore, signOut }
})
