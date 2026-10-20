import { beforeEach, describe, expect, it, vi } from 'vitest'
import { makeToken } from '@/test-utils'

// Views are lazy-loaded; stub them so navigation doesn't pull in real pages
vi.mock('@/views/LoginView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/views/SetupView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/views/RulesView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/views/DashboardView.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/AppLayout.vue', () => ({ default: { template: '<router-view />' } }))

const authApi = vi.hoisted(() => ({ status: vi.fn(), setup: vi.fn(), login: vi.fn() }))
vi.mock('@/api/auth', () => ({ authApi }))

// A fresh router (and store module) per test, starting from "/"
async function freshRouter() {
  vi.resetModules()
  window.history.replaceState({}, '', '/')
  const { createPinia, setActivePinia } = await import('pinia')
  setActivePinia(createPinia())
  return (await import('@/router')).default
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  sessionStorage.clear()
})

describe('navigation guard', () => {
  it('lets public routes through', async () => {
    const router = await freshRouter()
    await router.push('/login')
    expect(router.currentRoute.value.path).toBe('/login')
    expect(authApi.status).not.toHaveBeenCalled()
  })

  it('sends unauthenticated users to /login when the app is configured', async () => {
    authApi.status.mockResolvedValue({ is_configured: true })
    const router = await freshRouter()
    await router.push('/rules')
    expect(router.currentRoute.value.path).toBe('/login')
  })

  it('sends unauthenticated users to /setup on first run', async () => {
    authApi.status.mockResolvedValue({ is_configured: false })
    const router = await freshRouter()
    await router.push('/rules')
    expect(router.currentRoute.value.path).toBe('/setup')
  })

  it('falls back to /setup when the status check fails', async () => {
    authApi.status.mockRejectedValue(new Error('offline'))
    const router = await freshRouter()
    await router.push('/rules')
    expect(router.currentRoute.value.path).toBe('/setup')
  })

  it('treats an expired token as logged out', async () => {
    localStorage.setItem('token', makeToken(-5))
    authApi.status.mockResolvedValue({ is_configured: true })
    const router = await freshRouter()
    await router.push('/rules')
    expect(router.currentRoute.value.path).toBe('/login')
  })

  it('lets authenticated users through', async () => {
    localStorage.setItem('token', makeToken())
    const router = await freshRouter()
    await router.push('/rules')
    expect(router.currentRoute.value.path).toBe('/rules')
  })

  it('redirects / to /dashboard', async () => {
    localStorage.setItem('token', makeToken())
    const router = await freshRouter()
    await router.push('/')
    expect(router.currentRoute.value.path).toBe('/dashboard')
  })
})

describe('stale chunk reload', () => {
  // jsdom can't navigate, so the reload itself (location.assign) isn't observable;
  // the once-per-session marker is what guards against reload loops
  it('marks the reload for this session and re-arms after a successful navigation', async () => {
    const router = await freshRouter()

    const event = new Event('vite:preloadError', { cancelable: true })
    window.dispatchEvent(event)

    expect(event.defaultPrevented).toBe(true)
    expect(sessionStorage.getItem('chunk-reload')).toBe('1')

    await router.push('/login')
    expect(sessionStorage.getItem('chunk-reload')).toBeNull()
  })
})
