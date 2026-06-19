<script setup>
import { ref, onMounted } from 'vue'
import { rulesApi } from '@/api/rules'
import { accountsApi } from '@/api/accounts'
import ConfirmModal from '@/components/ConfirmModal.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const rules = ref([])
const accounts = ref([])
const loading = ref(true)
const deleteTarget = ref(null)
const triggering = ref(null)

onMounted(async () => {
  loading.value = true
  try {
    ;[rules.value, accounts.value] = await Promise.all([rulesApi.list(), accountsApi.list()])
  } finally {
    loading.value = false
  }
})

function accountLabel(id) {
  return accounts.value.find((a) => a.id === id)?.label ?? `#${id}`
}

async function toggleEnabled(rule) {
  await rulesApi.update(rule.id, { enabled: !rule.enabled })
  rule.enabled = !rule.enabled
}

async function runNow(rule) {
  triggering.value = rule.id
  try {
    await rulesApi.run(rule.id)
  } finally {
    triggering.value = null
  }
}

async function confirmDelete() {
  await rulesApi.delete(deleteTarget.value.id)
  rules.value = rules.value.filter((r) => r.id !== deleteTarget.value.id)
  deleteTarget.value = null
}

function fmt(dt) {
  if (!dt) return '—'
  return new Date(/[Z+]/.test(dt.slice(-6)) ? dt : dt + 'Z').toLocaleString()
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h1>Sync Rules</h1>
        <p>Define which folders to sync and on what schedule.</p>
      </div>
      <RouterLink to="/rules/new" class="btn btn-primary">+ New Rule</RouterLink>
    </div>

    <div class="card">
      <div v-if="loading" class="empty-state">
        <span class="spinner spinner-dark" style="width:24px;height:24px;" />
      </div>
      <div v-else-if="rules.length === 0" class="empty-state">
        <div class="icon">⇄</div>
        <h3>No rules yet</h3>
        <p>Create a rule to define what gets synced and when.</p>
        <RouterLink to="/rules/new" class="btn btn-primary" style="margin-top:16px;">+ New Rule</RouterLink>
      </div>
      <table v-else class="table">
        <thead>
          <tr>
            <th>Enabled</th>
            <th>Label</th>
            <th>Source</th>
            <th>Destination</th>
            <th>Schedule</th>
            <th>Last run</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="rule in rules" :key="rule.id">
            <td>
              <label class="toggle">
                <input type="checkbox" :checked="rule.enabled" @change="toggleEnabled(rule)" />
                <span class="toggle-track" />
              </label>
            </td>
            <td><strong>{{ rule.label }}</strong></td>
            <td>
              <div class="account-path">
                <span class="badge badge-neutral">{{ accountLabel(rule.source_account_id) }}</span>
                <span class="mono path-text">{{ rule.source_path }}</span>
              </div>
            </td>
            <td>
              <div class="account-path">
                <span class="badge badge-neutral">{{ accountLabel(rule.dest_account_id) }}</span>
                <span class="mono path-text">{{ rule.dest_path }}</span>
              </div>
            </td>
            <td class="mono">{{ rule.schedule_cron }}</td>
            <td>{{ fmt(rule.last_run_at) }}</td>
            <td>
              <div class="actions">
                <button
                  class="btn btn-primary btn-sm"
                  :disabled="triggering === rule.id || !rule.enabled"
                  @click="runNow(rule)"
                >
                  <span v-if="triggering === rule.id" class="spinner" style="width:12px;height:12px;" />
                  Run
                </button>
                <RouterLink :to="`/rules/${rule.id}/edit`" class="btn btn-secondary btn-sm">Edit</RouterLink>
                <button class="btn btn-danger btn-sm" @click="deleteTarget = rule">Delete</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <ConfirmModal
      v-if="deleteTarget"
      title="Delete rule?"
      :message="`Delete &quot;${deleteTarget.label}&quot;? This cannot be undone.`"
      @confirm="confirmDelete"
      @cancel="deleteTarget = null"
    />
  </div>
</template>

<style scoped>
.account-path { display: flex; flex-direction: column; gap: 3px; }
.path-text { color: var(--text-muted); font-size: 11.5px; }
</style>
