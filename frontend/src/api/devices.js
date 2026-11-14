import api from './client'

export const devicesApi = {
  list: () => api.get('/devices').then((r) => r.data),
  get: (id) => api.get(`/devices/${id}`).then((r) => r.data),
  create: (data) => api.post('/devices', data).then((r) => r.data),
  update: (id, data) => api.patch(`/devices/${id}`, data).then((r) => r.data),
  delete: (id) => api.delete(`/devices/${id}`),
}
