<script setup>
import { ref, onMounted } from 'vue'
import { rulesApi } from '@/api/rules'
import { jobsApi } from '@/api/jobs'
import StatusBadge from '@/components/StatusBadge.vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const rules = ref([])
const latestJobs = ref({}) // rule_id → SyncJob
const loading = ref(true)
const triggering = ref(null)

onMounted(async () => {
  await refresh()
})

async function refresh() {
  loading.value = true
  try {
    rules.value = await rulesApi.list()
    // Fetch last job for each rule
    await Promise.all(
      rules.value.map(async (rule) => {
        const data = await jobsApi.list({ rule_id: rule.id, limit: 1 })
        latestJobs.value[rule.id] = data.items[0] ?? null
      }),
    )
  } finally {
    loading.value = false
  }
}

async function runNow(rule) {
  triggering.value = rule.id
  try {
    await rulesApi.run(rule.id)
    setTimeout(refresh, 1500)
  } finally {
    triggering.value = null
  }
}

function fmt(dt) {
  if (!dt) return '—'
  return new Date(dt).toLocaleString()
}

function transferred(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let v = bytes, i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(1)} ${units[i]}`
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h1>Dashboard</h1>
        <p>Overview of all sync rules and their last run status.</p>
      </div>
      <div class="actions">
        <button class="btn btn-secondary" @click="refresh">↺ Refresh</button>
        <RouterLink to="/rules/new" class="btn btn-primary">+ New Rule</RouterLink>
      </div>
    </div>

    <div v-if="loading" class="empty-state">
      <div class="spinner spinner-dark" style="width:28px;height:28px;margin:0 auto 12px;" />
      <p>Loading…</p>
    </div>

    <div v-else-if="rules.length === 0" class="empty-state">
      <div class="icon">⇄</div>
      <h3>No sync rules yet</h3>
      <p>Create your first rule to start backing up folders.</p>
      <RouterLink to="/rules/new" class="btn btn-primary" style="margin-top:16px;">+ New Rule</RouterLink>
    </div>

    <div v-else class="rules-grid">
      <div v-for="rule in rules" :key="rule.id" class="rule-card card">
        <div class="rule-card-top">
          <div class="rule-info">
            <div class="rule-name">{{ rule.label }}</div>
            <div class="rule-schedule mono">{{ rule.schedule_cron }}</div>
          </div>
          <div class="rule-badges">
            <span v-if="!rule.enabled" class="badge badge-neutral">disabled</span>
            <StatusBadge v-else-if="latestJobs[rule.id]" :status="latestJobs[rule.id].status" />
            <span v-else class="badge badge-neutral">never run</span>
          </div>
        </div>

        <div class="rule-card-meta" v-if="latestJobs[rule.id]">
          <div class="meta-item">
            <span class="meta-label">Last run</span>
            <span>{{ fmt(latestJobs[rule.id]?.started_at) }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Added</span>
            <span>{{ latestJobs[rule.id]?.files_added }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Updated</span>
            <span>{{ latestJobs[rule.id]?.files_updated }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Transferred</span>
            <span>{{ transferred(latestJobs[rule.id]?.bytes_transferred) }}</span>
          </div>
        </div>
        <div class="rule-card-meta" v-else>
          <span style="color:var(--text-muted);font-size:13px;">No runs yet</span>
        </div>

        <div class="rule-card-footer">
          <RouterLink :to="`/rules/${rule.id}/edit`" class="btn btn-secondary btn-sm">Edit</RouterLink>
          <button
            class="btn btn-primary btn-sm"
            :disabled="triggering === rule.id || !rule.enabled"
            @click="runNow(rule)"
          >
            <span v-if="triggering === rule.id" class="spinner" style="width:12px;height:12px;" />
            Run now
          </button>
          <RouterLink :to="`/history?rule_id=${rule.id}`" class="btn btn-ghost btn-sm">Logs</RouterLink>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rules-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}
.rule-card { padding: 0; overflow: hidden; }
.rule-card-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px 12px;
}
.rule-name { font-weight: 600; font-size: 14.5px; margin-bottom: 4px; }
.rule-schedule { color: var(--text-muted); font-size: 12px; }
.rule-badges { flex-shrink: 0; }

.rule-card-meta {
  display: flex;
  gap: 20px;
  padding: 10px 18px;
  border-top: 1px solid var(--border-light);
  border-bottom: 1px solid var(--border-light);
  background: var(--bg);
}
.meta-item { display: flex; flex-direction: column; gap: 2px; }
.meta-label { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); font-weight: 600; }

.rule-card-footer {
  display: flex;
  gap: 8px;
  padding: 12px 18px;
}
</style>
