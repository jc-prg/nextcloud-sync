<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { accountsApi } from '@/api/accounts'
import ConfirmModal from '@/components/ConfirmModal.vue'

const route = useRoute()
const router = useRouter()

const accounts = ref([])
const loading = ref(true)
const saving = ref(false)
const testing = ref(null)
const cronRunning = ref(null)
const testResults = ref({})
const deleteTarget = ref(null)
const editTarget = ref(undefined) // undefined = closed, null = new, {id,...} = edit

const form = ref(emptyForm())

function emptyForm() {
  return {
    label: '', webdav_url: '', username: '', password: '', storage_limit_gb: '',
    cron_enabled: false, cron_interval_minutes: 5, cron_url: '',
  }
}

onMounted(async () => {
  await load()
  // Deep link from the overview graph: /accounts?edit=<id>
  const editId = Number(route.query.edit)
  if (editId) {
    const acc = accounts.value.find((a) => a.id === editId)
    if (acc) openEdit(acc)
    router.replace({ path: '/accounts' })
  }
})

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
  form.value = {
    label: account.label,
    webdav_url: account.webdav_url,
    username: account.username,
    password: '',
    storage_limit_gb: account.storage_limit_bytes != null ? (account.storage_limit_bytes / 1073741824).toFixed(2).replace(/\.?0+$/, '') : '',
    cron_enabled: account.cron_enabled,
    cron_interval_minutes: account.cron_interval_minutes,
    cron_url: account.cron_url || '',
  }
}

function closeForm() {
  editTarget.value = undefined
}

const formOpen = () => editTarget.value !== undefined

async function save() {
  saving.value = true
  try {
    const limitBytes = form.value.storage_limit_gb !== '' && form.value.storage_limit_gb !== null
      ? Math.round(parseFloat(form.value.storage_limit_gb) * 1073741824)
      : null
    if (editTarget.value) {
      const payload = { ...form.value, storage_limit_bytes: limitBytes }
      delete payload.storage_limit_gb
      if (!payload.password) delete payload.password
      await accountsApi.update(editTarget.value.id, payload)
    } else {
      const payload = { ...form.value, storage_limit_bytes: limitBytes }
      delete payload.storage_limit_gb
      await accountsApi.create(payload)
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

// cron.php URL shown as placeholder: <server root>/cron.php derived from the WebDAV URL
function derivedCronUrl(webdavUrl) {
  const idx = (webdavUrl || '').indexOf('/remote.php/')
  return idx >= 0 ? webdavUrl.slice(0, idx) + '/cron.php' : ''
}

async function runCron(account) {
  cronRunning.value = account.id
  try {
    const updated = await accountsApi.runCron(account.id)
    const i = accounts.value.findIndex((a) => a.id === account.id)
    if (i >= 0) accounts.value[i] = updated
  } catch (e) {
    alert(e?.response?.data?.detail || 'cron.php call failed')
  } finally {
    cronRunning.value = null
  }
}

function formatTime(iso) {
  // Backend stores naive UTC timestamps
  return iso ? new Date(iso.endsWith('Z') ? iso : iso + 'Z').toLocaleString() : ''
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
          <div class="form-group">
            <label>Max Storage (GB) <span style="font-weight:400;color:var(--text-muted);">— optional</span></label>
            <input v-model="form.storage_limit_gb" type="number" min="0" step="0.1" class="input" placeholder="leave blank to use server quota" />
            <small>Caps the usable storage shown in the dashboard; useful when sharing a server with others.</small>
          </div>
          <div class="form-group">
            <label style="display:flex;align-items:center;gap:8px;">
              <input v-model="form.cron_enabled" type="checkbox" />
              Call Nextcloud cron.php periodically
            </label>
            <small>Runs the server's background jobs (Nextcloud setting "Webcron"). Not needed if the server uses system cron.</small>
          </div>
          <template v-if="form.cron_enabled">
            <div class="form-group">
              <label>Interval (minutes)</label>
              <input v-model.number="form.cron_interval_minutes" type="number" min="1" max="1440" step="1" class="input" />
              <small>Nextcloud recommends every 5 minutes.</small>
            </div>
            <div class="form-group">
              <label>cron.php URL <span style="font-weight:400;color:var(--text-muted);">— optional</span></label>
              <input v-model="form.cron_url" class="input" :placeholder="derivedCronUrl(form.webdav_url) || 'https://cloud.example.com/cron.php'" />
              <small>Leave blank to derive it from the WebDAV URL.</small>
            </div>
          </template>
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
            <th>cron.php</th>
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
              <span v-if="cronRunning === acc.id" class="spinner spinner-dark" style="width:14px;height:14px;" />
              <span
                v-else-if="acc.cron_last_ok === true"
                class="badge badge-success"
                :title="`Last call: ${formatTime(acc.cron_last_run_at)}`"
              >✓ {{ acc.cron_enabled ? `every ${acc.cron_interval_minutes} min` : 'OK' }}</span>
              <span
                v-else-if="acc.cron_last_ok === false"
                class="badge badge-error"
                :title="`${formatTime(acc.cron_last_run_at)}: ${acc.cron_last_error}`"
              >✕ Failed</span>
              <span v-else-if="acc.cron_enabled" class="badge badge-neutral">every {{ acc.cron_interval_minutes }} min</span>
              <span v-else class="badge badge-neutral">off</span>
            </td>
            <td>
              <div class="actions">
                <button class="btn btn-secondary btn-sm" :disabled="testing === acc.id" @click="testConn(acc)">Test</button>
                <button
                  v-if="acc.cron_effective_url"
                  class="btn btn-secondary btn-sm"
                  :disabled="cronRunning === acc.id"
                  :title="`Call ${acc.cron_effective_url} now`"
                  @click="runCron(acc)"
                >Cron</button>
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
