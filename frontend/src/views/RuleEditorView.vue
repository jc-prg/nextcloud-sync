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
import SubfolderPicker from '@/components/SubfolderPicker.vue'

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
  exclude_subfolders: [],
  exclude_hidden: true,
  dest_account_id: null,
  dest_path: null,
  direction: 'one_way',
  schedule_cron: '0 3 * * *',
  delete_orphans: false,
  exclude_patterns: [],
  min_file_size: null,
  max_file_size: null,
})

// Size filter UI state (display value + unit, converted to bytes for the API)
const minSize = ref({ value: '', unit: 'MB' })
const maxSize = ref({ value: '', unit: 'MB' })
const UNITS = { KB: 1024, MB: 1024 ** 2, GB: 1024 ** 3 }

function toBytes(val, unit) {
  const n = parseFloat(val)
  return isNaN(n) || n <= 0 ? null : Math.floor(n * UNITS[unit])
}

function fromBytes(bytes, unit = 'MB') {
  if (!bytes) return { value: '', unit }
  if (bytes >= UNITS.GB) return { value: (bytes / UNITS.GB).toFixed(1), unit: 'GB' }
  if (bytes >= UNITS.MB) return { value: (bytes / UNITS.MB).toFixed(1), unit: 'MB' }
  return { value: (bytes / UNITS.KB).toFixed(1), unit: 'KB' }
}

function syncSizes() {
  form.value.min_file_size = toBytes(minSize.value.value, minSize.value.unit)
  form.value.max_file_size = toBytes(maxSize.value.value, maxSize.value.unit)
}

// Pattern list management
const newPattern = ref('')
function addPattern() {
  const p = newPattern.value.trim()
  if (p && !form.value.exclude_patterns.includes(p)) {
    form.value.exclude_patterns.push(p)
  }
  newPattern.value = ''
}
function removePattern(i) {
  form.value.exclude_patterns.splice(i, 1)
}

onMounted(async () => {
  accounts.value = await accountsApi.list()
  if (isEdit.value) {
    const rule = await rulesApi.get(ruleId.value)
    Object.assign(form.value, rule)
    minSize.value = fromBytes(rule.min_file_size)
    maxSize.value = fromBytes(rule.max_file_size)
    const match = CRON_PRESETS.find((p) => p.value !== '__custom__' && p.value === rule.schedule_cron)
    selectedPreset.value = match ? match.value : '__custom__'
    if (!match) cronMode.value = 'custom'
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
const selectedPreset = ref('0 3 * * *')

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
  syncSizes()
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
                <button type="button" class="btn btn-ghost btn-sm" @click="form.source_path = null; form.exclude_subfolders = []">Change</button>
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

          <div v-if="form.source_path && form.source_account_id" class="form-group">
            <label>Subfolders to sync</label>
            <small>Uncheck subfolders you want to exclude from the sync.</small>
            <SubfolderPicker
              :account-id="form.source_account_id"
              :path="form.source_path"
              v-model="form.exclude_subfolders"
            />
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
              <select class="input" v-model="selectedPreset" @change="applyCronPreset(selectedPreset)">
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

      <!-- Exclusion filters -->
      <div class="card" style="margin-bottom:16px;">
        <div class="card-header"><h2>Exclusion Filters</h2></div>
        <div class="card-body">

          <!-- Hidden files -->
          <div class="form-group" style="flex-direction:row;align-items:center;gap:10px;margin-bottom:20px;">
            <label class="toggle">
              <input type="checkbox" v-model="form.exclude_hidden" />
              <span class="toggle-track" />
            </label>
            <span style="font-size:13px;">
              <strong>Exclude hidden files and folders</strong> — skip files and directories whose name starts with <span class="mono">.</span>
            </span>
          </div>

          <!-- Size limits -->
          <div class="form-grid" style="margin-bottom:20px;">
            <div class="form-group">
              <label>Skip files smaller than</label>
              <div class="size-input">
                <input
                  v-model="minSize.value"
                  type="number" min="0" step="any"
                  class="input"
                  placeholder="No minimum"
                  @change="syncSizes"
                />
                <select v-model="minSize.unit" class="input unit-select" @change="syncSizes">
                  <option>KB</option><option>MB</option><option>GB</option>
                </select>
              </div>
            </div>
            <div class="form-group">
              <label>Skip files larger than</label>
              <div class="size-input">
                <input
                  v-model="maxSize.value"
                  type="number" min="0" step="any"
                  class="input"
                  placeholder="No maximum"
                  @change="syncSizes"
                />
                <select v-model="maxSize.unit" class="input unit-select" @change="syncSizes">
                  <option>KB</option><option>MB</option><option>GB</option>
                </select>
              </div>
            </div>
          </div>

          <!-- Regex patterns -->
          <div class="form-group">
            <label>Exclude by filename pattern (regex)</label>
            <small>Matched against the filename only, case-insensitive. Examples: <span class="mono">\.tmp$</span> &nbsp; <span class="mono">^~</span> &nbsp; <span class="mono">\.(log|bak)$</span></small>

            <div class="pattern-list" v-if="form.exclude_patterns.length">
              <div v-for="(p, i) in form.exclude_patterns" :key="i" class="pattern-tag">
                <span class="mono">{{ p }}</span>
                <button type="button" class="remove-btn" @click="removePattern(i)" title="Remove">✕</button>
              </div>
            </div>

            <div class="pattern-add">
              <input
                v-model="newPattern"
                class="input mono"
                placeholder="e.g. \.tmp$"
                @keydown.enter.prevent="addPattern"
              />
              <button type="button" class="btn btn-secondary btn-sm" @click="addPattern">Add</button>
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

.size-input { display: flex; gap: 8px; }
.unit-select { width: 80px; flex-shrink: 0; }

.pattern-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 10px 0 8px;
}
.pattern-tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px 3px 10px;
  background: var(--border-light);
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 12.5px;
}
.remove-btn {
  border: none;
  background: none;
  cursor: pointer;
  color: var(--text-muted);
  padding: 0 2px;
  font-size: 11px;
  line-height: 1;
}
.remove-btn:hover { color: var(--error); }

.pattern-add { display: flex; gap: 8px; margin-top: 8px; }
.pattern-add .input { flex: 1; }
</style>
