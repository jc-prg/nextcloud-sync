<script setup>
/**
 * Create or edit a SyncRule.
 * Uses FolderTree to visually pick source and destination paths.
 */
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { rulesApi } from '@/api/rules'
import { accountsApi } from '@/api/accounts'
import FolderTree from '@/components/FolderTree.vue'

const route = useRoute()
const router = useRouter()

const ruleId = computed(() => route.params.id ? Number(route.params.id) : null)
const isEdit = computed(() => ruleId.value !== null)

const accounts = ref([])
const loading = ref(true)
const saving = ref(false)
const error = ref('')

const form = ref({
  label: '',
  enabled: true,
  source_account_id: null,
  source_path: null,
  dest_account_id: null,
  dest_path: null,
  direction: 'one_way',
  schedule_cron: '0 3 * * *',
  delete_orphans: false,
})

onMounted(async () => {
  accounts.value = await accountsApi.list()
  if (isEdit.value) {
    const rule = await rulesApi.get(ruleId.value)
    Object.assign(form.value, rule)
  }
  loading.value = false
})

const sourceAccount = computed(() =>
  accounts.value.find((a) => a.id === form.value.source_account_id) ?? null,
)
const destAccount = computed(() =>
  accounts.value.find((a) => a.id === form.value.dest_account_id) ?? null,
)

const CRON_PRESETS = [
  { label: 'Every hour', value: '0 * * * *' },
  { label: 'Every 6 hours', value: '0 */6 * * *' },
  { label: 'Daily at 03:00', value: '0 3 * * *' },
  { label: 'Daily at 01:00', value: '0 1 * * *' },
  { label: 'Weekly (Sun 03:00)', value: '0 3 * * 0' },
  { label: 'Custom', value: '__custom__' },
]

const cronMode = ref('preset')
function applyCronPreset(val) {
  if (val !== '__custom__') {
    form.value.schedule_cron = val
    cronMode.value = 'preset'
  } else {
    cronMode.value = 'custom'
  }
}

async function save() {
  error.value = ''
  if (!form.value.source_account_id || !form.value.source_path) {
    error.value = 'Please select a source folder.'
    return
  }
  if (!form.value.dest_account_id || !form.value.dest_path) {
    error.value = 'Please select a destination folder.'
    return
  }
  saving.value = true
  try {
    if (isEdit.value) {
      await rulesApi.update(ruleId.value, form.value)
    } else {
      await rulesApi.create(form.value)
    }
    router.push('/rules')
  } catch (e) {
    error.value = e?.response?.data?.detail || 'Save failed.'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h1>{{ isEdit ? 'Edit Rule' : 'New Sync Rule' }}</h1>
        <p>Define source, destination, schedule and sync options.</p>
      </div>
      <RouterLink to="/rules" class="btn btn-secondary">← Back</RouterLink>
    </div>

    <div v-if="loading" class="empty-state">
      <span class="spinner spinner-dark" style="width:28px;height:28px;" />
    </div>

    <form v-else @submit.prevent="save">
      <!-- Basic info -->
      <div class="card" style="margin-bottom:16px;">
        <div class="card-header"><h2>General</h2></div>
        <div class="card-body">
          <div class="form-grid">
            <div class="form-group">
              <label>Rule name</label>
              <input v-model="form.label" class="input" placeholder="e.g. Photos Backup" required />
            </div>
            <div class="form-group" style="justify-content:flex-end;flex-direction:row;align-items:center;gap:10px;">
              <span style="font-size:13px;font-weight:500;">Enabled</span>
              <label class="toggle">
                <input type="checkbox" v-model="form.enabled" />
                <span class="toggle-track" />
              </label>
            </div>
          </div>
        </div>
      </div>

      <!-- Source -->
      <div class="card" style="margin-bottom:16px;">
        <div class="card-header"><h2>Source</h2></div>
        <div class="card-body">
          <div class="form-group" style="margin-bottom:16px;">
            <label>Account</label>
            <select v-model="form.source_account_id" class="input" @change="form.source_path = null" required>
              <option :value="null" disabled>Select an account…</option>
              <option v-for="acc in accounts" :key="acc.id" :value="acc.id">{{ acc.label }}</option>
            </select>
          </div>

          <div class="form-group">
            <label>Folder</label>
            <template v-if="sourceAccount">
              <div v-if="form.source_path" class="selected-path">
                <span class="mono">{{ form.source_path }}</span>
                <button type="button" class="btn btn-ghost btn-sm" @click="form.source_path = null">Change</button>
              </div>
              <FolderTree
                v-else
                :account-id="form.source_account_id"
                v-model="form.source_path"
              />
              <small v-if="!form.source_path">Click a folder to select it as source.</small>
            </template>
            <p v-else class="placeholder-hint">Select an account first.</p>
          </div>
        </div>
      </div>

      <!-- Destination -->
      <div class="card" style="margin-bottom:16px;">
        <div class="card-header"><h2>Destination</h2></div>
        <div class="card-body">
          <div class="form-group" style="margin-bottom:16px;">
            <label>Account</label>
            <select v-model="form.dest_account_id" class="input" @change="form.dest_path = null" required>
              <option :value="null" disabled>Select an account…</option>
              <option v-for="acc in accounts" :key="acc.id" :value="acc.id">{{ acc.label }}</option>
            </select>
          </div>

          <div class="form-group">
            <label>Folder</label>
            <template v-if="destAccount">
              <div v-if="form.dest_path" class="selected-path">
                <span class="mono">{{ form.dest_path }}</span>
                <button type="button" class="btn btn-ghost btn-sm" @click="form.dest_path = null">Change</button>
              </div>
              <FolderTree
                v-else
                :account-id="form.dest_account_id"
                v-model="form.dest_path"
              />
              <small v-if="!form.dest_path">Click a folder to select it as destination.</small>
            </template>
            <p v-else class="placeholder-hint">Select an account first.</p>
          </div>
        </div>
      </div>

      <!-- Schedule & options -->
      <div class="card" style="margin-bottom:16px;">
        <div class="card-header"><h2>Schedule &amp; Options</h2></div>
        <div class="card-body">
          <div class="form-grid">
            <div class="form-group">
              <label>Schedule preset</label>
              <select class="input" @change="applyCronPreset($event.target.value)">
                <option v-for="p in CRON_PRESETS" :key="p.value" :value="p.value">{{ p.label }}</option>
              </select>
            </div>
            <div class="form-group">
              <label>Cron expression</label>
              <input v-model="form.schedule_cron" class="input mono" placeholder="0 3 * * *" required />
              <small>minute hour day month weekday (UTC)</small>
            </div>
            <div class="form-group">
              <label>Direction</label>
              <select v-model="form.direction" class="input">
                <option value="one_way">One-way (source → destination)</option>
                <option value="two_way">Two-way (bidirectional)</option>
              </select>
            </div>
            <div class="form-group" style="flex-direction:row;align-items:center;gap:10px;padding-top:22px;">
              <label class="toggle">
                <input type="checkbox" v-model="form.delete_orphans" />
                <span class="toggle-track" />
              </label>
              <span style="font-size:13px;">
                <strong>Delete orphans</strong> — remove files from destination that no longer exist on source
              </span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="error" class="alert alert-error" style="margin-bottom:16px;">{{ error }}</div>

      <div class="actions">
        <button type="submit" class="btn btn-primary" :disabled="saving">
          <span v-if="saving" class="spinner" />
          {{ isEdit ? 'Save changes' : 'Create rule' }}
        </button>
        <RouterLink to="/rules" class="btn btn-secondary">Cancel</RouterLink>
      </div>
    </form>
  </div>
</template>

<style scoped>
.selected-path {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: var(--primary-light);
  border: 1px solid #c7d7f8;
  border-radius: var(--radius);
  color: var(--primary);
}
.placeholder-hint { color: var(--text-muted); font-size: 13px; font-style: italic; }
</style>
