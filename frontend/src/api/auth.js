import api from './client'
import axios from 'axios'

export const authApi = {
  status: () => axios.get('/api/auth/status').then((r) => r.data),
  setup: (password) => api.post('/auth/setup', { password }).then((r) => r.data),
  login: (password) => api.post('/auth/login', { password }).then((r) => r.data),
}
