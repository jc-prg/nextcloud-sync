import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi } from '@/api/auth'

// True if the JWT is missing, malformed or past its `exp` claim
export function isTokenExpired(token) {
  if (!token) return true
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
    return !payload.exp || payload.exp * 1000 <= Date.now()
  } catch {
    return true
  }
}

function loadToken() {
  const stored = localStorage.getItem('token') || ''
  if (stored && isTokenExpired(stored)) {
    localStorage.removeItem('token')
    return ''
  }
  return stored
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref(loadToken())
  const isConfigured = ref(false)

  async function checkSetup() {
    const data = await authApi.status()
    isConfigured.value = data.is_configured
    return data.is_configured
  }

  async function setup(password) {
    const data = await authApi.setup(password)
    token.value = data.access_token
    localStorage.setItem('token', data.access_token)
    isConfigured.value = true
  }

  async function login(password) {
    const data = await authApi.login(password)
    token.value = data.access_token
    localStorage.setItem('token', data.access_token)
  }

  function logout() {
    token.value = ''
    localStorage.removeItem('token')
  }

  function isAuthenticated() {
    if (isTokenExpired(token.value)) {
      if (token.value) logout()
      return false
    }
    return true
  }

  return { token, isConfigured, checkSetup, setup, login, logout, isAuthenticated }
})
