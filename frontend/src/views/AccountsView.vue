<script setup>
import { ref, onMounted } from 'vue'
import { accountsApi } from '@/api/accounts'
import ConfirmModal from '@/components/ConfirmModal.vue'

const accounts = ref([])
const loading = ref(true)
const saving = ref(false)
const testing = ref(null)
const testResults = ref({})
const deleteTarget = ref(null)
const editTarget = ref(null) // null = closed, {} = new, {id,...} = edit

const form = ref(emptyForm())

function emptyForm() {
  return { label: '', webdav_url: '', username: '', password: '' }
}

onMounted(load)

async function load() {
  loading.value = true
  try { accounts.value = await accountsApi.list() } finally { loading.value = false }
}

function openNew() {
  editTarget.value = null
  form.value = emptyForm()
}

function openEdit(account) {
  editTarget.value = account
  form.value = { label: account.label, webdav_url: account.webdav_url, username: account.username, password: '' }
}

function closeForm() {
  editTarget.value = undefined
}

const formOpen = () => editTarget.value !== undefined

async function save() {
  saving.value = true
  try {
    if (editTarget.value) {
      const payload = { ...form.value }
      if (!payload.password) delete payload.password
      await accountsApi.update(editTarget.value.id, payload)
    } else {
      await accountsApi.create(form.value)
    }
    await load()
    editTarget.value = undefined
  } catch (e) {
    alert(e?.response?.data?.detail || 'Save failed')
  } finally {
    saving.value = false
  }
}

async function testConn(account) {
  testing.value = account.id
  testResults.value[account.id] = null
  try {
    const result = await accountsApi.test(account.id)
    testResults.value[account.id] = result
  } catch {
    testResults.value[account.id] = { ok: false, error: 'Request failed' }
  } finally {
    testing.value = null
  }
}

async function confirmDelete() {
  await accountsApi.delete(deleteTarget.value.id)
  deleteTarget.value = null
  await load()
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h1>Accounts</h1>
        <p>WebDAV accounts for local and remote Nextcloud instances.</p>
      </div>
      <button class="btn btn-primary" @click="openNew">+ Add Account</button>
    </div>

    <!-- Form panel -->
    <div v-if="formOpen()" class="card form-panel" style="margin-bottom:20px;">
      <div class="card-header">
        <h2>{{ editTarget ? 'Edit Account' : 'New Account' }}</h2>
        <button class="btn btn-ghost btn-sm" @click="closeForm">✕</button>
      </div>
      <div class="card-body">
        <div class="form-grid" style="gap:16px;">
          <div class="form-group">
            <label>Label</label>
            <input v-model="form.label" class="input" placeholder="e.g. Local Pi, Remote Backup" />
          </div>
          <div class="form-group">
            <label>WebDAV URL</label>
            <input v-model="form.webdav_url" class="input" placeholder="https://cloud.example.com/remote.php/dav/files/user" />
            <small>Full DAV files root for this user account</small>
          </div>
          <div class="form-group">
            <label>Username</label>
            <input v-model="form.username" class="input" autocomplete="off" />
          </div>
          <div class="form-group">
            <label>Password{{ editTarget ? ' (leave blank to keep current)' : '' }}</label>
            <input v-model="form.password" type="password" class="input" autocomplete="new-password" />
          </div>
        </div>
        <div style="margin-top:16px;display:flex;gap:8px;">
          <button class="btn btn-primary" :disabled="saving" @click="save">
            <span v-if="saving" class="spinner" />
            Save
          </button>
          <button class="btn btn-secondary" @click="closeForm">Cancel</button>
        </div>
      </div>
    </div>

    <!-- Accounts table -->
    <div class="card">
      <div v-if="loading" class="empty-state"><span class="spinner spinner-dark" style="width:24px;height:24px;" /></div>
      <div v-else-if="accounts.length === 0" class="empty-state">
        <div class="icon">⬡</div>
        <h3>No accounts yet</h3>
        <p>Add a WebDAV account to get started.</p>
      </div>
      <table v-else class="table">
        <thead>
          <tr>
            <th>Label</th>
            <th>WebDAV URL</th>
            <th>Username</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="acc in accounts" :key="acc.id">
            <td><strong>{{ acc.label }}</strong></td>
            <td class="mono" style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">{{ acc.webdav_url }}</td>
            <td>{{ acc.username }}</td>
            <td>
              <span v-if="testing === acc.id" class="spinner spinner-dark" style="width:14px;height:14px;" />
              <span v-else-if="testResults[acc.id]?.ok === true" class="badge badge-success">✓ OK</span>
              <span v-else-if="testResults[acc.id]?.ok === false" class="badge badge-error" :title="testResults[acc.id]?.error">✕ Failed</span>
              <span v-else class="badge badge-neutral">—</span>
            </td>
            <td>
              <div class="actions">
                <button class="btn btn-secondary btn-sm" :disabled="testing === acc.id" @click="testConn(acc)">Test</button>
                <button class="btn btn-secondary btn-sm" @click="openEdit(acc)">Edit</button>
                <button class="btn btn-danger btn-sm" @click="deleteTarget = acc">Delete</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <ConfirmModal
      v-if="deleteTarget"
      title="Delete account?"
      :message="`This will permanently delete &quot;${deleteTarget.label}&quot;. Sync rules using this account will break.`"
      @confirm="confirmDelete"
      @cancel="deleteTarget = null"
    />
  </div>
</template>
