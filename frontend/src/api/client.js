import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (r) => r,
  (err) => {
    // Don't redirect on 401 from auth endpoints — those handle errors themselves
    if (err.response?.status === 401 && !err.config?.url?.includes('/auth/')) {
      localStorage.removeItem('token')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  },
)

export default api
