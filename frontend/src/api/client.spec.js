import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError } from 'axios'
import { createPinia, setActivePinia } from 'pinia'
import { makeToken } from '@/test-utils'

const route = { value: { path: '/rules' } }
vi.mock('@/router', () => ({ default: { currentRoute: route, push: vi.fn() } }))
vi.mock('@/stores/connectivity', () => ({ markOffline: vi.fn(), markOnline: vi.fn() }))

const { default: api } = await import('@/api/client')
const { default: router } = await import('@/router')
const { markOffline, markOnline } = await import('@/stores/connectivity')
const { useAuthStore } = await import('@/stores/auth')

// Replaces the HTTP layer: answers every request with `status`, or fails with no response at all
function respondWith(status) {
  api.defaults.adapter = async (config) => {
    if (status === null) throw new AxiosError('Network Error', 'ERR_NETWORK', config)
    const response = { status, statusText: '', data: {}, headers: {}, config }
    if (status >= 400) throw new AxiosError('fail', 'ERR_BAD_RESPONSE', config, null, response)
    return response
  }
}

let auth
beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  setActivePinia(createPinia())
  auth = useAuthStore()
  route.value.path = '/rules'
})

function login() {
  const token = makeToken()
  localStorage.setItem('token', token)
  auth.token = token
  return token
}

describe('api client', () => {
  it('sends the stored token as Bearer header', async () => {
    const token = login()
    respondWith(200)
    const res = await api.get('/rules')
    expect(res.config.headers.Authorization).toBe(`Bearer ${token}`)
    expect(markOnline).toHaveBeenCalled()
  })

  it('sends no Authorization header when logged out', async () => {
    respondWith(200)
    const res = await api.get('/rules')
    expect(res.config.headers.Authorization).toBeUndefined()
  })

  it('logs out and redirects to /login on 401', async () => {
    login()
    respondWith(401)
    await expect(api.get('/rules')).rejects.toThrow()
    expect(auth.token).toBe('')
    expect(router.push).toHaveBeenCalledWith('/login')
  })

  it('does not redirect when already on /login', async () => {
    login()
    route.value.path = '/login'
    respondWith(401)
    await expect(api.get('/rules')).rejects.toThrow()
    expect(auth.token).toBe('')
    expect(router.push).not.toHaveBeenCalled()
  })

  it('ignores 401 from auth endpoints', async () => {
    login()
    respondWith(401)
    await expect(api.post('/auth/login', {})).rejects.toThrow()
    expect(auth.token).not.toBe('')
    expect(router.push).not.toHaveBeenCalled()
  })

  it('ignores 401 for a request sent with an older token', async () => {
    login()
    api.defaults.adapter = async (config) => {
      // A fresh login replaces the token while this request is in flight
      auth.token = makeToken(7200)
      const response = { status: 401, data: {}, headers: {}, config }
      throw new AxiosError('fail', 'ERR_BAD_RESPONSE', config, null, response)
    }
    const fresh = await api.get('/rules').catch(() => auth.token)
    expect(auth.token).toBe(fresh)
    expect(router.push).not.toHaveBeenCalled()
  })

  it('marks the backend offline when there is no response', async () => {
    respondWith(null)
    await expect(api.get('/rules')).rejects.toThrow('Network Error')
    expect(markOffline).toHaveBeenCalled()
    expect(markOnline).not.toHaveBeenCalled()
  })

  it('marks the backend online on any HTTP error response', async () => {
    respondWith(500)
    await expect(api.get('/rules')).rejects.toThrow()
    expect(markOnline).toHaveBeenCalled()
    expect(markOffline).not.toHaveBeenCalled()
  })
})
