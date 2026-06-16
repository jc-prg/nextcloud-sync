import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi } from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
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

  return { token, isConfigured, checkSetup, setup, login, logout }
})
