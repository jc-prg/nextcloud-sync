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
})
const emit = defineEmits(['update:modelValue'])

const allEntries = ref([])
const loading = ref(false)
const error = ref(null)

onMounted(load)
watch(() => [props.accountId, props.path], load)

async function load() {
  allEntries.value = []
  error.value = null
  loading.value = true
  try {
    const data = await browseApi.list(props.accountId, props.path, 2)
    allEntries.value = data.entries.filter((e) => e.is_dir)
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
      <template v-for="item in tree" :key="item.path">
        <label class="sf-item" :class="{ excluded: isExcluded(item.path) }">
          <input type="checkbox" :checked="!isExcluded(item.path)" @change="toggle(item.path)" />
          <span class="sf-icon">📁</span>
          <span class="sf-name">{{ name(item.path) }}</span>
        </label>
        <label
          v-for="child in item.children"
          :key="child"
          class="sf-item sf-item-child"
          :class="{ excluded: isExcluded(child) || isExcluded(item.path) }"
        >
          <input
            type="checkbox"
            :checked="!isExcluded(child) && !isExcluded(item.path)"
            :disabled="isExcluded(item.path)"
            @change="toggle(child)"
          />
          <span class="sf-icon">📁</span>
          <span class="sf-name">{{ name(child) }}</span>
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
</style>
