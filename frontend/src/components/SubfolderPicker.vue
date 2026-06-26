<script setup>
/**
 * Shows two levels of subfolders with checkboxes.
 * Checked = included in sync, unchecked = excluded.
 *
 * Props:
 *   accountId   – Account to browse
 *   path        – Parent path whose subfolders are listed
 *   modelValue  – list of excluded subfolder paths (v-model)
 *
 * Emits:
 *   update:modelValue – updated list of excluded paths
 */
import { ref, computed, watch, onMounted } from 'vue'
import { browseApi } from '@/api/browse'

const props = defineProps({
  accountId: { type: Number, required: true },
  path: { type: String, required: true },
  modelValue: { type: Array, default: () => [] },
  // All subfolder paths seen when the rule was last saved.
  // Used to detect new folders on first load of an edit form.
  knownSubfolders: { type: Array, default: null },
})
const emit = defineEmits(['update:modelValue', 'update:knownSubfolders'])

const allEntries = ref([])
const loading = ref(false)
const error = ref(null)
const removedPaths = ref([])  // stale excluded paths pruned after last load
const newPaths = ref([])      // paths in tree not seen at last save

onMounted(load)
watch(() => [props.accountId, props.path], load)

async function load() {
  const previousPaths = allEntries.value.map((e) => e.path)
  allEntries.value = []
  removedPaths.value = []
  newPaths.value = []
  error.value = null
  loading.value = true
  try {
    const data = await browseApi.list(props.accountId, props.path, 2)
    const dirs = data.entries.filter((e) => e.is_dir)
    allEntries.value = dirs

    const currentPaths = new Set(dirs.map((e) => e.path))

    // Prune excluded paths that no longer exist
    const stale = props.modelValue.filter((p) => !currentPaths.has(p))
    if (stale.length > 0) {
      removedPaths.value = stale
      emit('update:modelValue', props.modelValue.filter((p) => currentPaths.has(p)))
    }

    // Detect new folders:
    // On first load, compare against knownSubfolders (saved at last edit).
    // On reload within the same session, compare against previous in-memory tree.
    const referenceSet = previousPaths.length > 0
      ? new Set(previousPaths)
      : props.knownSubfolders !== null ? new Set(props.knownSubfolders) : null

    if (referenceSet !== null) {
      newPaths.value = [...currentPaths].filter((p) => !referenceSet.has(p))
    }

    // Update knownSubfolders to the current tree so it's saved with the rule
    emit('update:knownSubfolders', [...currentPaths])
  } catch (err) {
    error.value = err?.response?.data?.detail || err?.message || 'Failed to load subfolders'
  } finally {
    loading.value = false
  }
}

const tree = computed(() => {
  const srcDepth = props.path.replace(/\/$/, '').split('/').length
  const level1 = allEntries.value
    .filter((e) => e.path.replace(/\/$/, '').split('/').length === srcDepth + 1)
    .map((e) => e.path)
    .sort()
  return level1.map((p1) => {
    const prefix = p1.replace(/\/$/, '') + '/'
    const children = allEntries.value
      .filter((e) => e.path.replace(/\/$/, '').split('/').length === srcDepth + 2 && e.path.startsWith(prefix))
      .map((e) => e.path)
      .sort()
    return { path: p1, children }
  })
})

function isExcluded(path) {
  return props.modelValue.includes(path)
}

function toggle(path) {
  const excluded = [...props.modelValue]
  const idx = excluded.indexOf(path)
  if (idx === -1) {
    excluded.push(path)
  } else {
    excluded.splice(idx, 1)
  }
  emit('update:modelValue', excluded)
}

function name(path) {
  return path.replace(/\/$/, '').split('/').pop()
}
</script>

<template>
  <div class="subfolder-picker">
    <div v-if="loading" class="sf-state">
      <span class="spinner spinner-dark" style="width:12px;height:12px;" />
      <span>Loading subfolders…</span>
    </div>
    <div v-else-if="error" class="sf-state sf-error">
      <span>⚠ {{ error }}</span>
      <button class="btn btn-ghost btn-sm" @click="load">Retry</button>
    </div>
    <div v-else-if="tree.length === 0" class="sf-state sf-empty">
      No subfolders
    </div>
    <template v-else>
      <div v-if="removedPaths.length > 0" class="sf-notice sf-notice-removed">
        {{ removedPaths.length }} excluded subfolder{{ removedPaths.length > 1 ? 's' : '' }} no longer exist and {{ removedPaths.length > 1 ? 'were' : 'was' }} removed:
        <span v-for="p in removedPaths" :key="p" class="sf-notice-path">{{ name(p) }}</span>
      </div>
      <div v-if="newPaths.length > 0" class="sf-notice sf-notice-new">
        {{ newPaths.length }} new subfolder{{ newPaths.length > 1 ? 's' : '' }} found and included in sync:
        <span v-for="p in newPaths" :key="p" class="sf-notice-path">{{ name(p) }}</span>
      </div>
      <template v-for="item in tree" :key="item.path">
        <label class="sf-item" :class="{ excluded: isExcluded(item.path), 'sf-new': newPaths.includes(item.path) }">
          <input type="checkbox" :checked="!isExcluded(item.path)" @change="toggle(item.path)" />
          <span class="sf-icon">📁</span>
          <span class="sf-name">{{ name(item.path) }}</span>
          <span v-if="newPaths.includes(item.path)" class="sf-new-badge">new</span>
        </label>
        <label
          v-for="child in item.children"
          :key="child"
          class="sf-item sf-item-child"
          :class="{ excluded: isExcluded(child) || isExcluded(item.path), 'sf-new': newPaths.includes(child) }"
        >
          <input
            type="checkbox"
            :checked="!isExcluded(child) && !isExcluded(item.path)"
            :disabled="isExcluded(item.path)"
            @change="toggle(child)"
          />
          <span class="sf-icon">📁</span>
          <span class="sf-name">{{ name(child) }}</span>
          <span v-if="newPaths.includes(child)" class="sf-new-badge">new</span>
        </label>
      </template>
    </template>
  </div>
</template>

<style scoped>
.subfolder-picker {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--card-bg);
  max-height: 220px;
  overflow-y: auto;
  margin-top: 6px;
}

.sf-state {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  color: var(--text-muted);
  font-size: 13px;
}
.sf-error { color: var(--error); }
.sf-empty { font-style: italic; }

.sf-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  cursor: pointer;
  border-radius: 4px;
  margin: 2px 4px;
  font-size: 13px;
  color: var(--text);
  user-select: none;
}
.sf-item:hover { background: var(--border-light); }
.sf-item-child { padding-left: 30px; }
.sf-item.excluded { color: var(--text-muted); text-decoration: line-through; }
.sf-icon { font-size: 14px; flex-shrink: 0; }
.sf-name { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
input[type="checkbox"] { flex-shrink: 0; cursor: pointer; accent-color: var(--primary); }

.sf-notice {
  font-size: 12px;
  padding: 6px 10px;
  margin: 4px 4px 0;
  border-radius: 4px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}
.sf-notice-removed { background: #3a1a1a; color: #fca5a5; }
.sf-notice-new { background: #1a3a2a; color: #6ee7b7; }
.sf-notice-path {
  font-family: monospace;
  background: rgba(255,255,255,.1);
  padding: 1px 5px;
  border-radius: 3px;
}
.sf-new-badge {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .04em;
  padding: 1px 5px;
  border-radius: 3px;
  background: #1a3a2a;
  color: #6ee7b7;
  flex-shrink: 0;
}
</style>
