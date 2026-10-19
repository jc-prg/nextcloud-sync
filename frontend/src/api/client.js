import axios from 'axios'
import { markOffline, markOnline } from '@/stores/connectivity'
import { useAuthStore } from '@/stores/auth'
import router from '@/router'

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => { markOnline(); return r },
  (err) => {
    if (!err.response) {
      // No response at all — server is unreachable
      markOffline()
    } else {
      markOnline()
      // Don't redirect on 401 from auth endpoints — those handle errors themselves
      if (err.response.status === 401 && !err.config?.url?.includes('/auth/')) {
        // Ignore 401s from requests sent with an older token: a fresh login
        // may already have replaced it, and must not be thrown away
        const sentToken = err.config?.headers?.Authorization?.replace('Bearer ', '') || ''
        const auth = useAuthStore()
        if (sentToken === auth.token) {
          auth.logout()
          if (router.currentRoute.value.path !== '/login') router.push('/login')
        }
      }
    }
    return Promise.reject(err)
  },
)

export default api
