import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { currentUser, login } from '../api/auth'
import { apiErrorMessage } from '../api/client'
import type { User } from '../types/api'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('incident_agent_token') || '')
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
      localStorage.setItem('incident_agent_token', response.access_token)
    } catch (failure) {
      error.value = apiErrorMessage(failure)
      throw failure
    } finally {
      loading.value = false
    }
  }

  async function restore() {
    if (!token.value) return
    try {
      user.value = await currentUser()
    } catch {
      signOut()
    }
  }

  function signOut() {
    token.value = ''
    user.value = null
    localStorage.removeItem('incident_agent_token')
  }

  return { token, user, loading, error, isAuthenticated, signIn, restore, signOut }
})
