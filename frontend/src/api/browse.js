import api from './client'

export const browseApi = {
  list: (accountId, path = '/', depth = 1) =>
    api.get('/browse', { params: { account_id: accountId, path, depth } }).then((r) => r.data),
}
