import api from './client'

export const appsApi = {
  list: () => api.get('/apps').then((r) => r.data),
  get: (id) => api.get(`/apps/${id}`).then((r) => r.data),
  create: (data) => api.post('/apps', data).then((r) => r.data),
  update: (id, data) => api.patch(`/apps/${id}`, data).then((r) => r.data),
  delete: (id) => api.delete(`/apps/${id}`),
}
