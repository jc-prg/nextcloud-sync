import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { makeToken } from '@/test-utils'

vi.mock('@/api/auth', () => ({
  authApi: { status: vi.fn(), setup: vi.fn(), login: vi.fn() },
}))

const { authApi } = await import('@/api/auth')
const { isTokenExpired, useAuthStore } = await import('@/stores/auth')

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
})

describe('isTokenExpired', () => {
  it('accepts a token that has not expired yet', () => {
    expect(isTokenExpired(makeToken(60))).toBe(false)
  })

  it.each([
    ['missing', ''],
    ['expired', makeToken(-1)],
    ['malformed', 'not-a-jwt'],
    ['bad payload', 'a.!!!.c'],
    ['no exp claim', makeToken(60, { exp: undefined })],
  ])('rejects a %s token', (_, token) => {
    expect(isTokenExpired(token)).toBe(true)
  })

  it('decodes base64url payloads', () => {
    // '?' and '>' in the payload produce '-' and '_' in base64url
    expect(isTokenExpired(makeToken(60, { pad: '???>>>' }))).toBe(false)
  })
})

describe('auth store', () => {
  it('restores a valid token from localStorage', () => {
    const token = makeToken()
    localStorage.setItem('token', token)
    const auth = useAuthStore()
    expect(auth.token).toBe(token)
    expect(auth.isAuthenticated()).toBe(true)
  })

  it('drops an expired stored token on load', () => {
    localStorage.setItem('token', makeToken(-10))
    expect(useAuthStore().token).toBe('')
    expect(localStorage.getItem('token')).toBeNull()
  })

  it('login stores the token', async () => {
    const token = makeToken()
    authApi.login.mockResolvedValue({ access_token: token })
    const auth = useAuthStore()
    await auth.login('pw')
    expect(authApi.login).toHaveBeenCalledWith('pw')
    expect(auth.token).toBe(token)
    expect(localStorage.getItem('token')).toBe(token)
  })

  it('setup stores the token and marks the app configured', async () => {
    authApi.setup.mockResolvedValue({ access_token: makeToken() })
    const auth = useAuthStore()
    await auth.setup('password1')
    expect(auth.isConfigured).toBe(true)
    expect(auth.isAuthenticated()).toBe(true)
  })

  it('logout clears the token', () => {
    localStorage.setItem('token', makeToken())
    const auth = useAuthStore()
    auth.logout()
    expect(auth.token).toBe('')
    expect(localStorage.getItem('token')).toBeNull()
  })

  it('isAuthenticated logs out once the token has expired', () => {
    const auth = useAuthStore()
    auth.token = makeToken(-1)
    localStorage.setItem('token', auth.token)
    expect(auth.isAuthenticated()).toBe(false)
    expect(localStorage.getItem('token')).toBeNull()
  })

  it('checkSetup reads the configured flag', async () => {
    authApi.status.mockResolvedValue({ is_configured: true })
    const auth = useAuthStore()
    expect(await auth.checkSetup()).toBe(true)
    expect(auth.isConfigured).toBe(true)
  })
})
