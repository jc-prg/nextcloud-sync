import api from './client'

export const rulesApi = {
  list: () => api.get('/rules').then((r) => r.data),
  get: (id) => api.get(`/rules/${id}`).then((r) => r.data),
  create: (data) => api.post('/rules', data).then((r) => r.data),
  update: (id, data) => api.patch(`/rules/${id}`, data).then((r) => r.data),
  delete: (id) => api.delete(`/rules/${id}`),
  run: (id) => api.post(`/rules/${id}/run`).then((r) => r.data),
}
