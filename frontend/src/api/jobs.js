import api from './client'

export const jobsApi = {
  list: (params = {}) => api.get('/jobs', { params }).then((r) => r.data),
  get: (id) => api.get(`/jobs/${id}`).then((r) => r.data),
  logs: (id, params = {}) => api.get(`/jobs/${id}/logs`, { params }).then((r) => r.data),
}
