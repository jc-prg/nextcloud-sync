import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes = [
  { path: '/setup', component: () => import('@/views/SetupView.vue'), meta: { public: true } },
  { path: '/login', component: () => import('@/views/LoginView.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('@/components/AppLayout.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', component: () => import('@/views/DashboardView.vue') },
      { path: 'accounts', component: () => import('@/views/AccountsView.vue') },
      { path: 'rules', component: () => import('@/views/RulesView.vue') },
      { path: 'rules/new', component: () => import('@/views/RuleEditorView.vue') },
      { path: 'rules/:id/edit', component: () => import('@/views/RuleEditorView.vue') },
      { path: 'history', component: () => import('@/views/HistoryView.vue') },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  if (to.meta.public) return true

  const auth = useAuthStore()
  if (!auth.token) {
    // Check if app is configured; if not, send to setup
    try {
      await auth.checkSetup()
    } catch {
      // ignore
    }
    return auth.isConfigured ? '/login' : '/setup'
  }
})

export default router
