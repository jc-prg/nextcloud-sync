<script setup>
/**
 * Apps that use one or more account folders via WebDAV (e.g. a notes or password app).
 *
 * Display only: the overview shows them next to the destinations, linked to the
 * account folders they use.
 */
import { ref, computed, onMounted, watch } from 'vue'
import { appsApi } from '@/api/apps'
import { accountsApi } from '@/api/accounts'
import ConfirmModal from '@/components/ConfirmModal.vue'
import FolderTree from '@/components/FolderTree.vue'

const props = defineProps({
  openId: { type: Number, default: null }, // app to open for editing (deep link from the overview)
  accountsVersion: { type: Number, default: 0 }, // bumped when accounts change
})

const apps = ref([])
const accounts = ref([])
const loading = ref(true)
const saving = ref(false)
const deleteTarget = ref(null)
const editTarget = ref(undefined) // undefined = closed, null = new, {id,...} = edit
const form = ref({ label: '', note: '', folders: [] })
const picker = ref(null) // { account_id, account_path } while adding a folder

const accountById = computed(() => new Map(accounts.value.map((a) => [a.id, a])))

onMounted(async () => {
  await load()
  const app = apps.value.find((a) => a.id === props.openId)
  if (app) openEdit(app)
})

watch(() => props.accountsVersion, async () => {
  accounts.value = await accountsApi.list()
})

async function load() {
  loading.value = true
  try {
    ;[apps.value, accounts.value] = await Promise.all([appsApi.list(), accountsApi.list()])
  } finally {
    loading.value = false
  }
}

function openNew() {
  editTarget.value = null
  form.value = { label: '', note: '', folders: [] }
  picker.value = null
}

function openEdit(app) {
  editTarget.value = app
  form.value = { label: app.label, note: app.note || '', folders: app.folders.map((f) => ({ ...f })) }
  picker.value = null
}

function closeForm() {
  editTarget.value = undefined
  picker.value = null
}

const formOpen = () => editTarget.value !== undefined

async function save() {
  saving.value = true
  try {
    if (editTarget.value) await appsApi.update(editTarget.value.id, form.value)
    else await appsApi.create(form.value)
    await load()
    closeForm()
  } catch (e) {
    alert(e?.response?.data?.detail || 'Save failed')
  } finally {
    saving.value = false
  }
}

async function confirmDelete() {
  await appsApi.delete(deleteTarget.value.id)
  deleteTarget.value = null
  await load()
}

function startPick() {
  picker.value = { account_id: accounts.value[0]?.id ?? null, account_path: null }
}

function addFolder() {
  const f = { account_id: picker.value.account_id, account_path: picker.value.account_path || '/' }
  if (!form.value.folders.some((x) => x.account_id === f.account_id && x.account_path === f.account_path)) {
    form.value.folders.push(f)
  }
  picker.value = null
}

function folderLabel(f) {
  const acc = accountById.value.get(f.account_id)
  return `${acc ? acc.label : `#${f.account_id} (deleted)`}:${f.account_path}`
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>Apps</h2>
        <p>Apps that use account folders via WebDAV, shown next to the destinations in the overview.</p>
      </div>
      <button class="btn btn-primary" @click="openNew">+ Add App</button>
    </div>

    <!-- Form panel -->
    <div v-if="formOpen()" class="card" style="margin-bottom:20px;">
      <div class="card-header">
        <h2>{{ editTarget ? 'Edit App' : 'New App' }}</h2>
        <button class="btn btn-ghost btn-sm" @click="closeForm">✕</button>
      </div>
      <div class="card-body">
        <div class="form-grid" style="margin-bottom:20px;">
          <div class="form-group">
            <label>Label</label>
            <input v-model="form.label" class="input" placeholder="e.g. Obsidian, KeePassXC" />
          </div>
          <div class="form-group">
            <label>Note <span class="muted">— optional</span></label>
            <input v-model="form.note" class="input" placeholder="e.g. on phone and tablet" />
          </div>
        </div>

        <div class="form-group">
          <label>WebDAV folders</label>
          <small>The account folders this app reads and writes.</small>
        </div>
        <div class="folders">
          <div v-for="(f, i) in form.folders" :key="f.account_id + f.account_path" class="folder-row">
            <span class="folder-icon">📁</span>
            <span class="mono">{{ folderLabel(f) }}</span>
            <button class="btn btn-ghost btn-sm danger" title="Remove" @click="form.folders.splice(i, 1)">✕</button>
          </div>

          <div v-if="picker" class="link-panel">
            <p v-if="accounts.length === 0" class="muted">No accounts configured yet.</p>
            <template v-else>
              <div class="form-group">
                <label>Account</label>
                <select v-model="picker.account_id" class="input" @change="picker.account_path = null">
                  <option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.label }}</option>
                </select>
              </div>
              <div class="form-group">
                <label>
                  Folder
                  <span class="mono muted">{{ picker.account_path || '/ (whole account)' }}</span>
                  <button
                    v-if="picker.account_path && picker.account_path !== '/'"
                    class="btn btn-ghost btn-sm" @click="picker.account_path = null"
                  >Use whole account</button>
                </label>
                <FolderTree v-model="picker.account_path" :account-id="picker.account_id" />
              </div>
            </template>
            <div class="actions">
              <button class="btn btn-primary btn-sm" :disabled="!picker.account_id" @click="addFolder">Add</button>
              <button class="btn btn-secondary btn-sm" @click="picker = null">Cancel</button>
            </div>
          </div>
          <div v-else class="folder-row">
            <button class="btn btn-ghost btn-sm" @click="startPick">+ Folder</button>
          </div>
        </div>

        <div style="margin-top:16px;display:flex;gap:8px;">
          <button class="btn btn-primary" :disabled="saving || !form.label.trim()" @click="save">
            <span v-if="saving" class="spinner" />
            Save
          </button>
          <button class="btn btn-secondary" @click="closeForm">Cancel</button>
        </div>
      </div>
    </div>

    <!-- Apps table -->
    <div class="card">
      <div v-if="loading" class="empty-state"><span class="spinner spinner-dark" style="width:24px;height:24px;" /></div>
      <div v-else-if="apps.length === 0" class="empty-state">
        <div class="icon">◫</div>
        <h3>No apps yet</h3>
        <p>Add an app that syncs via WebDAV to show it in the overview.</p>
      </div>
      <table v-else class="table">
        <thead>
          <tr>
            <th>Label</th>
            <th>WebDAV folders</th>
            <th>Note</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="app in apps" :key="app.id">
            <td><strong>{{ app.label }}</strong></td>
            <td class="mono">
              <div v-for="f in app.folders" :key="f.account_id + f.account_path">{{ folderLabel(f) }}</div>
              <span v-if="app.folders.length === 0" class="muted">—</span>
            </td>
            <td>{{ app.note || '' }}</td>
            <td>
              <div class="actions">
                <button class="btn btn-secondary btn-sm" @click="openEdit(app)">Edit</button>
                <button class="btn btn-danger btn-sm" @click="deleteTarget = app">Delete</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <ConfirmModal
      v-if="deleteTarget"
      title="Delete app?"
      :message="`This will permanently delete &quot;${deleteTarget.label}&quot;. Nothing in the app or its folders is touched.`"
      @confirm="confirmDelete"
      @cancel="deleteTarget = null"
    />
  </div>
</template>

<style scoped>
.folders {
  margin-top: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 4px 0;
}
.folder-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding: 0 8px;
}
.folder-row:hover { background: var(--border-light); }
.folder-row .danger { margin-left: auto; }
.danger:hover { color: var(--error); }
.folder-icon { font-size: 14px; }
.link-panel {
  display: flex; flex-direction: column; gap: 12px;
  margin: 4px 8px 10px; padding: 12px;
  border: 1px solid var(--border); border-radius: var(--radius); background: var(--bg);
  max-width: 480px;
}
.muted { color: var(--text-muted); font-weight: 400; }

@media (max-width: 640px) {
  .form-grid { grid-template-columns: 1fr; }
}
</style>
