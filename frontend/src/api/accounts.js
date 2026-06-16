import api from './client'

export const accountsApi = {
  list: () => api.get('/accounts').then((r) => r.data),
  get: (id) => api.get(`/accounts/${id}`).then((r) => r.data),
  create: (data) => api.post('/accounts', data).then((r) => r.data),
  update: (id, data) => api.patch(`/accounts/${id}`, data).then((r) => r.data),
  delete: (id) => api.delete(`/accounts/${id}`),
  test: (id) => api.post(`/accounts/${id}/test`).then((r) => r.data),
}
