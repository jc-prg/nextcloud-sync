<script setup>
/**
 * Shows direct subfolders of a given path with checkboxes.
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
import { ref, watch, onMounted } from 'vue'
import { browseApi } from '@/api/browse'

const props = defineProps({
  accountId: { type: Number, required: true },
  path: { type: String, required: true },
  modelValue: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue'])

const subfolders = ref([])
const loading = ref(false)
const error = ref(null)

onMounted(load)
watch(() => [props.accountId, props.path], load)

async function load() {
  subfolders.value = []
  error.value = null
  loading.value = true
  try {
    const data = await browseApi.list(props.accountId, props.path)
    subfolders.value = data.entries
      .filter((e) => e.is_dir)
      .map((e) => e.path)
      .sort()
  } catch (err) {
    error.value = err?.response?.data?.detail || err?.message || 'Failed to load subfolders'
  } finally {
    loading.value = false
  }
}

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

function subfoldername(path) {
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
    <div v-else-if="subfolders.length === 0" class="sf-state sf-empty">
      No subfolders
    </div>
    <template v-else>
      <label
        v-for="sf in subfolders"
        :key="sf"
        class="sf-item"
        :class="{ excluded: isExcluded(sf) }"
      >
        <input
          type="checkbox"
          :checked="!isExcluded(sf)"
          @change="toggle(sf)"
        />
        <span class="sf-icon">📁</span>
        <span class="sf-name">{{ subfoldername(sf) }}</span>
      </label>
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
.sf-item.excluded { color: var(--text-muted); text-decoration: line-through; }
.sf-icon { font-size: 14px; flex-shrink: 0; }
.sf-name { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
input[type="checkbox"] { flex-shrink: 0; cursor: pointer; accent-color: var(--primary); }
</style>
