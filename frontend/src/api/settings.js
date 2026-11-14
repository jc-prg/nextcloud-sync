import api from './client'

// Small UI settings stored as JSON by key in the backend
export const settingsApi = {
  get: (key) => api.get(`/settings/${key}`).then((r) => r.data.value),
  put: (key, value) => api.put(`/settings/${key}`, { value }).then((r) => r.data.value),
}
