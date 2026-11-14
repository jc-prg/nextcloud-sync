<script setup>
/**
 * Devices synced by the Nextcloud desktop client (e.g. a laptop).
 *
 * next-sync does not sync them; each device holds a simulated folder tree whose
 * folders can be linked to a folder of an account, so the dashboard overview can
 * show the device as the first stage of the sync chain.
 */
import { ref, computed, onMounted, watch } from 'vue'
import { devicesApi } from '@/api/devices'
import { accountsApi } from '@/api/accounts'
import ConfirmModal from '@/components/ConfirmModal.vue'
import FolderTree from '@/components/FolderTree.vue'
import { addFolder, removeFolder, renameFolder, depth, baseName, isWithin } from '@/utils/deviceTree'

const props = defineProps({
  openId: { type: Number, default: null }, // device to open for editing (deep link from the overview)
  accountsVersion: { type: Number, default: 0 }, // bumped when accounts change
})

const devices = ref([])
const accounts = ref([])
const loading = ref(true)
const saving = ref(false)
const deleteTarget = ref(null)
const editTarget = ref(undefined) // undefined = closed, null = new, {id,...} = edit
const form = ref({ label: '', folders: [] })

// Inline editing inside the tree: { mode: 'add' | 'rename' | 'link', path, name?, account_id?, account_path? }
const pending = ref(null)
const formError = ref('')

const accountById = computed(() => new Map(accounts.value.map((a) => [a.id, a])))

onMounted(async () => {
  await load()
  const dev = devices.value.find((d) => d.id === props.openId)
  if (dev) openEdit(dev)
})

watch(() => props.accountsVersion, async () => {
  accounts.value = await accountsApi.list()
})

async function load() {
  loading.value = true
  try {
    ;[devices.value, accounts.value] = await Promise.all([devicesApi.list(), accountsApi.list()])
  } finally {
    loading.value = false
  }
}

function openNew() {
  editTarget.value = null
  form.value = { label: 'Laptop', folders: [] }
  pending.value = null
}

function openEdit(device) {
  editTarget.value = device
  form.value = { label: device.label, folders: device.folders.map((f) => ({ ...f })) }
  pending.value = null
}

function closeForm() {
  editTarget.value = undefined
  pending.value = null
}

const formOpen = () => editTarget.value !== undefined

async function save() {
  saving.value = true
  try {
    if (editTarget.value) await devicesApi.update(editTarget.value.id, form.value)
    else await devicesApi.create(form.value)
    await load()
    closeForm()
  } catch (e) {
    alert(e?.response?.data?.detail || 'Save failed')
  } finally {
    saving.value = false
  }
}

async function confirmDelete() {
  await devicesApi.delete(deleteTarget.value.id)
  deleteTarget.value = null
  await load()
}

// ── Tree editing ───────────────────────────────────────────────────────────

function startAdd(parent) {
  pending.value = { mode: 'add', path: parent, name: '' }
  formError.value = ''
}

function startRename(folder) {
  pending.value = { mode: 'rename', path: folder.path, name: baseName(folder.path) }
  formError.value = ''
}

function startLink(folder) {
  pending.value = {
    mode: 'link',
    path: folder.path,
    account_id: folder.account_id ?? accounts.value[0]?.id ?? null,
    account_path: folder.account_path,
  }
}

function applyName() {
  const p = pending.value
  const result = p.mode === 'add'
    ? addFolder(form.value.folders, p.path, p.name)
    : renameFolder(form.value.folders, p.path, p.name)
  if (!result) {
    formError.value = 'Invalid name, or a folder with that name already exists here.'
    return
  }
  form.value.folders = result
  pending.value = null
}

function applyLink() {
  const p = pending.value
  const folder = form.value.folders.find((f) => f.path === p.path)
  folder.account_id = p.account_id
  folder.account_path = p.account_path || '/'
  pending.value = null
}

function unlink(folder) {
  folder.account_id = null
  folder.account_path = null
  if (pending.value?.path === folder.path) pending.value = null
}

function remove(folder) {
  form.value.folders = removeFolder(form.value.folders, folder.path)
  if (pending.value && isWithin(pending.value.path, folder.path)) pending.value = null
}

function linkLabel(f) {
  const acc = accountById.value.get(f.account_id)
  return `${acc ? acc.label : `#${f.account_id} (deleted)`}:${f.account_path}`
}

const isPending = (mode, path) => pending.value?.mode === mode && pending.value.path === path
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h2>Devices</h2>
        <p>Computers synced by the Nextcloud desktop client, shown as first column in the overview.</p>
      </div>
      <button class="btn btn-primary" @click="openNew">+ Add Device</button>
    </div>

    <!-- Form panel -->
    <div v-if="formOpen()" class="card" style="margin-bottom:20px;">
      <div class="card-header">
        <h2>{{ editTarget ? 'Edit Device' : 'New Device' }}</h2>
        <button class="btn btn-ghost btn-sm" @click="closeForm">✕</button>
      </div>
      <div class="card-body">
        <div class="form-group" style="max-width:360px;margin-bottom:20px;">
          <label>Label</label>
          <input v-model="form.label" class="input" placeholder="e.g. Laptop" />
        </div>

        <div class="form-group">
          <label>Folders</label>
          <small>
            Simulate the device's folder tree. Link a folder to the account folder the Nextcloud client syncs it with.
          </small>
        </div>

        <div class="tree">
          <template v-for="f in form.folders" :key="f.path">
            <div class="tree-row" :style="{ paddingLeft: 8 + depth(f.path) * 20 + 'px' }">
              <span class="folder-icon">📁</span>
              <template v-if="isPending('rename', f.path)">
                <input
                  v-model="pending.name" class="input input-sm" autofocus
                  @keyup.enter="applyName" @keyup.esc="pending = null"
                />
                <button class="btn btn-primary btn-sm" @click="applyName">OK</button>
                <button class="btn btn-ghost btn-sm" @click="pending = null">Cancel</button>
              </template>
              <template v-else>
                <span class="folder-name">{{ baseName(f.path) }}</span>
                <span v-if="f.account_id" class="link mono" :title="'Synced with ' + linkLabel(f)">⇄ {{ linkLabel(f) }}</span>
                <span class="row-actions">
                  <button class="btn btn-ghost btn-sm" title="Add subfolder" @click="startAdd(f.path)">+ Sub</button>
                  <button class="btn btn-ghost btn-sm" @click="startLink(f)">{{ f.account_id ? 'Relink' : 'Link' }}</button>
                  <button v-if="f.account_id" class="btn btn-ghost btn-sm" @click="unlink(f)">Unlink</button>
                  <button class="btn btn-ghost btn-sm" @click="startRename(f)">Rename</button>
                  <button class="btn btn-ghost btn-sm danger" title="Remove with subfolders" @click="remove(f)">✕</button>
                </span>
              </template>
            </div>

            <div v-if="isPending('add', f.path)" class="tree-row" :style="{ paddingLeft: 8 + (depth(f.path) + 1) * 20 + 'px' }">
              <span class="folder-icon">📁</span>
              <input
                v-model="pending.name" class="input input-sm" placeholder="Folder name" autofocus
                @keyup.enter="applyName" @keyup.esc="pending = null"
              />
              <button class="btn btn-primary btn-sm" @click="applyName">Add</button>
              <button class="btn btn-ghost btn-sm" @click="pending = null">Cancel</button>
            </div>

            <div v-if="isPending('link', f.path)" class="link-panel" :style="{ marginLeft: 8 + (depth(f.path) + 1) * 20 + 'px' }">
              <p v-if="accounts.length === 0" class="muted">No accounts configured yet.</p>
              <template v-else>
                <div class="form-group">
                  <label>Account</label>
                  <select v-model="pending.account_id" class="input" @change="pending.account_path = null">
                    <option v-for="a in accounts" :key="a.id" :value="a.id">{{ a.label }}</option>
                  </select>
                </div>
                <div class="form-group">
                  <label>
                    Folder
                    <span class="mono muted">{{ pending.account_path || '/ (whole account)' }}</span>
                    <button
                      v-if="pending.account_path && pending.account_path !== '/'"
                      class="btn btn-ghost btn-sm" @click="pending.account_path = null"
                    >Use whole account</button>
                  </label>
                  <FolderTree v-model="pending.account_path" :account-id="pending.account_id" />
                </div>
              </template>
              <div class="actions">
                <button class="btn btn-primary btn-sm" :disabled="!pending.account_id" @click="applyLink">Link</button>
                <button class="btn btn-secondary btn-sm" @click="pending = null">Cancel</button>
              </div>
            </div>
          </template>

          <div v-if="isPending('add', '/')" class="tree-row" style="padding-left:8px;">
            <span class="folder-icon">📁</span>
            <input
              v-model="pending.name" class="input input-sm" placeholder="Folder name" autofocus
              @keyup.enter="applyName" @keyup.esc="pending = null"
            />
            <button class="btn btn-primary btn-sm" @click="applyName">Add</button>
            <button class="btn btn-ghost btn-sm" @click="pending = null">Cancel</button>
          </div>
          <div v-else class="tree-row" style="padding-left:8px;">
            <button class="btn btn-ghost btn-sm" @click="startAdd('/')">+ Folder</button>
          </div>
        </div>
        <p v-if="formError && pending && pending.mode !== 'link'" class="form-error">{{ formError }}</p>

        <div style="margin-top:16px;display:flex;gap:8px;">
          <button class="btn btn-primary" :disabled="saving || !form.label.trim()" @click="save">
            <span v-if="saving" class="spinner" />
            Save
          </button>
          <button class="btn btn-secondary" @click="closeForm">Cancel</button>
        </div>
      </div>
    </div>

    <!-- Devices table -->
    <div class="card">
      <div v-if="loading" class="empty-state"><span class="spinner spinner-dark" style="width:24px;height:24px;" /></div>
      <div v-else-if="devices.length === 0" class="empty-state">
        <div class="icon">▭</div>
        <h3>No devices yet</h3>
        <p>Add your laptop to show it as the first stage in the overview.</p>
      </div>
      <table v-else class="table">
        <thead>
          <tr>
            <th>Label</th>
            <th>Folders</th>
            <th>Linked</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="dev in devices" :key="dev.id">
            <td><strong>{{ dev.label }}</strong></td>
            <td>{{ dev.folders.length }}</td>
            <td>{{ dev.folders.filter((f) => f.account_id).length }}</td>
            <td>
              <div class="actions">
                <button class="btn btn-secondary btn-sm" @click="openEdit(dev)">Edit</button>
                <button class="btn btn-danger btn-sm" @click="deleteTarget = dev">Delete</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <ConfirmModal
      v-if="deleteTarget"
      title="Delete device?"
      :message="`This will permanently delete &quot;${deleteTarget.label}&quot; and its folder tree. Nothing on the device itself is touched.`"
      @confirm="confirmDelete"
      @cancel="deleteTarget = null"
    />
  </div>
</template>

<style scoped>
.tree {
  margin-top: 10px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 4px 0;
}
.tree-row {
  display: flex;
  align-items: center;
  gap: 6px;
  min-height: 34px;
  padding-right: 8px;
}
.tree-row:hover { background: var(--border-light); }
.folder-icon { font-size: 14px; }
.folder-name { font-size: 13.5px; white-space: nowrap; }
.link {
  color: var(--primary);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0;
}
.row-actions { margin-left: auto; display: flex; gap: 2px; opacity: .35; flex-shrink: 0; }
.tree-row:hover .row-actions { opacity: 1; }
.danger:hover { color: var(--error); }
.input-sm { max-width: 220px; padding: 4px 8px; font-size: 13px; }
.link-panel {
  display: flex; flex-direction: column; gap: 12px;
  margin: 4px 8px 10px; padding: 12px;
  border: 1px solid var(--border); border-radius: var(--radius); background: var(--bg);
  max-width: 480px;
}
.muted { color: var(--text-muted); font-weight: 400; }
.form-error { color: var(--error); font-size: 13px; margin: 8px 0 0; }

@media (max-width: 640px) {
  .row-actions { opacity: 1; flex-wrap: wrap; }
  .tree-row { flex-wrap: wrap; }
}
</style>
