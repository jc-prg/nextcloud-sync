<script setup>
/**
 * Lazy-loading folder tree backed by GET /api/browse.
 *
 * Uses a flat ordered list of visible nodes so no recursive component is needed.
 * Each node tracks its depth, expanded state, and whether children were fetched.
 *
 * Props:
 *   accountId  – Account to browse
 *   modelValue – currently selected path (v-model)
 *
 * Emits:
 *   update:modelValue – when a folder is clicked/selected
 */
import { ref, watch, onMounted } from 'vue'
import { browseApi } from '@/api/browse'

const props = defineProps({
  accountId: { type: Number, required: true },
  modelValue: { type: String, default: null },
})
const emit = defineEmits(['update:modelValue'])

// Flat list of visible nodes
// { name, path, depth, expanded, loaded, loading, error }
const nodes = ref([])
const rootLoading = ref(false)
const rootError = ref(null)

onMounted(loadRoot)
watch(() => props.accountId, loadRoot)

async function loadRoot() {
  nodes.value = []
  rootError.value = null
  rootLoading.value = true
  try {
    const data = await browseApi.list(props.accountId, '/')
    nodes.value = data.entries
      .filter((e) => e.is_dir)
      .map((e) => makeNode(e, 0))
  } catch (err) {
    rootError.value = errMsg(err)
  } finally {
    rootLoading.value = false
  }
}

async function toggle(node) {
  if (node.expanded) {
    collapse(node)
  } else {
    await expand(node)
  }
}

function collapse(node) {
  node.expanded = false
  // Remove all descendants (depth > node.depth immediately following)
  const idx = nodes.value.indexOf(node)
  let end = idx + 1
  while (end < nodes.value.length && nodes.value[end].depth > node.depth) end++
  nodes.value.splice(idx + 1, end - idx - 1)
}

async function expand(node) {
  if (node.loading) return
  node.loading = true
  node.error = null
  try {
    const data = await browseApi.list(props.accountId, node.path)
    const children = data.entries
      .filter((e) => e.is_dir)
      .map((e) => makeNode(e, node.depth + 1))
    const idx = nodes.value.indexOf(node)
    nodes.value.splice(idx + 1, 0, ...children)
    node.expanded = true
    node.loaded = true
  } catch (err) {
    node.error = errMsg(err)
  } finally {
    node.loading = false
  }
}

async function refresh(node) {
  if (node.expanded) {
    collapse(node)
    node.loaded = false
  }
  await expand(node)
}

function select(node) {
  emit('update:modelValue', node.path)
}

function makeNode(entry, depth) {
  return {
    name: entry.name,
    path: entry.path,
    depth,
    expanded: false,
    loaded: false,
    loading: false,
    error: null,
  }
}

function errMsg(err) {
  return err?.response?.data?.detail || err?.message || 'Unknown error'
}
</script>

<template>
  <div class="folder-tree">
    <div v-if="rootLoading" class="tree-loading">
      <span class="spinner spinner-dark" />
      <span>Loading…</span>
    </div>

    <div v-else-if="rootError" class="tree-error">
      <span>⚠ {{ rootError }}</span>
      <button class="btn btn-ghost btn-sm" @click="loadRoot">Retry</button>
    </div>

    <div v-else-if="nodes.length === 0" class="tree-empty">
      No folders found
    </div>

    <div
      v-for="node in nodes"
      :key="node.path"
      class="tree-node"
      :class="{ selected: modelValue === node.path }"
      :style="{ paddingLeft: `${node.depth * 16 + 8}px` }"
    >
      <button
        class="expand-btn"
        :class="{ expanded: node.expanded, loading: node.loading }"
        @click.stop="toggle(node)"
        :aria-label="node.expanded ? 'Collapse' : 'Expand'"
      >
        <span v-if="node.loading" class="spinner spinner-dark" style="width:12px;height:12px;" />
        <svg v-else viewBox="0 0 10 10" width="10" height="10" fill="currentColor">
          <path d="M3 2l4 3-4 3z" :transform="node.expanded ? 'rotate(90,5,5)' : ''" />
        </svg>
      </button>

      <button class="folder-btn" @click="select(node)">
        <span class="folder-icon">{{ node.expanded ? '📂' : '📁' }}</span>
        <span class="folder-name">{{ node.name }}</span>
      </button>

      <button v-if="node.expanded" class="refresh-btn btn-ghost btn btn-icon btn-sm" title="Refresh" @click.stop="refresh(node)">
        ↺
      </button>

      <div v-if="node.error" class="node-error">⚠ {{ node.error }}</div>
    </div>
  </div>
</template>

<style scoped>
.folder-tree {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--card-bg);
  overflow-y: auto;
  max-height: 300px;
  min-height: 120px;
}

.tree-loading,
.tree-empty,
.tree-error {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  color: var(--text-muted);
  font-size: 13px;
}
.tree-error { color: var(--error); }

.tree-node {
  display: flex;
  align-items: center;
  gap: 4px;
  min-height: 32px;
  border-radius: 4px;
  margin: 1px 4px;
  padding-top: 0;
  padding-bottom: 0;
  position: relative;
}
.tree-node.selected { background: var(--primary-light); }
.tree-node.selected .folder-name { color: var(--primary); font-weight: 600; }

.expand-btn {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  cursor: pointer;
  border-radius: 4px;
  color: var(--text-muted);
  flex-shrink: 0;
  padding: 0;
}
.expand-btn:hover { background: var(--border); color: var(--text); }

.folder-btn {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: transparent;
  cursor: pointer;
  text-align: left;
  padding: 4px 4px 4px 0;
  border-radius: 4px;
  color: var(--text);
  min-width: 0;
}
.folder-btn:hover { color: var(--primary); }
.folder-icon { font-size: 14px; flex-shrink: 0; }
.folder-name { font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.refresh-btn { opacity: 0; font-size: 14px; flex-shrink: 0; }
.tree-node:hover .refresh-btn { opacity: 1; }

.node-error {
  position: absolute;
  left: 100%;
  white-space: nowrap;
  font-size: 11.5px;
  color: var(--error);
  background: var(--error-bg);
  padding: 2px 6px;
  border-radius: 4px;
}
</style>
