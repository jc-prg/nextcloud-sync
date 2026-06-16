import api from './client'

export const browseApi = {
  list: (accountId, path = '/') =>
    api.get('/browse', { params: { account_id: accountId, path } }).then((r) => r.data),
}
