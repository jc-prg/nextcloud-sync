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
  if (!auth.isAuthenticated()) {
    // Check if app is configured; if not, send to setup
    try {
      await auth.checkSetup()
    } catch {
      // ignore
    }
    return auth.isConfigured ? '/login' : '/setup'
  }
})

// A lazy route chunk can fail to load when the page was built from an older
// deploy (its hashed asset names no longer exist). Reload once to pick up the
// current index.html instead of leaving the user on a half-loaded page.
const RELOAD_KEY = 'chunk-reload'

function reloadOnce(path) {
  if (sessionStorage.getItem(RELOAD_KEY)) return
  sessionStorage.setItem(RELOAD_KEY, '1')
  window.location.assign(path)
}

window.addEventListener('vite:preloadError', (event) => {
  event.preventDefault()
  reloadOnce(window.location.pathname)
})

router.onError((err, to) => {
  if (/dynamically imported module|Importing a module script failed|Unable to preload CSS/i.test(err?.message)) {
    reloadOnce(to.fullPath)
  }
})

router.afterEach((to, from, failure) => {
  if (!failure) sessionStorage.removeItem(RELOAD_KEY)
})

export default router
