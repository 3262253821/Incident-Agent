import { createRouter, createWebHistory } from 'vue-router'

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

router.beforeEach((to) => {
  const hasToken = Boolean(localStorage.getItem('incident_agent_token'))
  if (to.meta.requiresAuth && !hasToken) return { name: 'login' }
  if (to.meta.guestOnly && hasToken) return { name: 'workspace' }
})

export default router
