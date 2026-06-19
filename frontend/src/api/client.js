import axios from 'axios'
import { markOffline, markOnline } from '@/stores/connectivity'

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
        localStorage.removeItem('token')
        window.location.href = '/login'
      }
    }
    return Promise.reject(err)
  },
)

export default api
