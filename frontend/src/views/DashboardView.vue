<script setup>
import { ref, onMounted } from 'vue'
import { rulesApi } from '@/api/rules'
import { jobsApi } from '@/api/jobs'
import { accountsApi } from '@/api/accounts'
import StatusBadge from '@/components/StatusBadge.vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const rules = ref([])
const latestJobs = ref({}) // rule_id → SyncJob
const accounts = ref([])
const quotas = ref({}) // account_id → { used, available }
const loading = ref(true)
const triggering = ref(null)

onMounted(async () => {
  await refresh()
})

async function refresh() {
  loading.value = true
  try {
    const [rulesData, accountsData] = await Promise.all([rulesApi.list(), accountsApi.list()])
    rules.value = rulesData
    accounts.value = accountsData
    await Promise.all([
      ...rulesData.map(async (rule) => {
        const data = await jobsApi.list({ rule_id: rule.id, limit: 1 })
        latestJobs.value[rule.id] = data.items[0] ?? null
      }),
      ...accountsData.map(async (account) => {
        quotas.value[account.id] = await accountsApi.quota(account.id)
      }),
    ])
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
  const d = new Date(/[Z+]/.test(dt.slice(-6)) ? dt : dt + 'Z')
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  const sameDay = (a, b) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  const timeStr = d.toLocaleTimeString()
  if (sameDay(d, today)) return `today<br>${timeStr}`
  if (sameDay(d, yesterday)) return `yesterday<br>${timeStr}`
  return `${d.toLocaleDateString()}<br>${timeStr}`
}

function transferred(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let v = bytes, i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(1)} ${units[i]}`
}

function fmtBytes(bytes) {
  if (bytes == null) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = bytes, i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(1)} ${units[i]}`
}

function effectiveQuota(account) {
  const q = quotas.value[account.id]
  if (!q || q.used == null) return null
  const serverTotal = q.available != null ? q.used + q.available : null
  const limit = account.storage_limit_bytes ?? null
  const effectiveTotal = (serverTotal != null && limit != null)
    ? Math.min(serverTotal, limit)
    : (limit ?? serverTotal)
  const effectiveFree = effectiveTotal != null ? Math.max(0, effectiveTotal - q.used) : q.available
  return { used: q.used, free: effectiveFree, total: effectiveTotal, capped: limit != null }
}

function usedPercent(account) {
  const eq = effectiveQuota(account)
  if (!eq || eq.total == null || eq.total === 0) return null
  return Math.min(100, Math.round((eq.used / eq.total) * 100))
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h1>Dashboard</h1>
        <p>Overview of accounts and sync rules.</p>
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

    <template v-else>
      <!-- Accounts -->
      <div class="section-header">
        <h2>Accounts</h2>
        <RouterLink to="/accounts" class="btn btn-ghost btn-sm">Manage</RouterLink>
      </div>

      <div v-if="accounts.length === 0" class="empty-state" style="margin-bottom:32px;">
        <p>No accounts configured yet.</p>
        <RouterLink to="/accounts" class="btn btn-primary" style="margin-top:12px;">+ Add Account</RouterLink>
      </div>

      <div v-else class="accounts-grid" style="margin-bottom:40px;">
        <div v-for="account in accounts" :key="account.id" class="account-card card">
          <div class="account-card-top">
            <div class="account-name">{{ account.label }}</div>
            <div class="account-url mono">{{ account.username }}@{{ account.webdav_url.replace(/https?:\/\//, '') }}</div>
          </div>
          <div class="account-quota">
            <template v-if="quotas[account.id]?.error">
              <span class="quota-error">Could not fetch quota</span>
            </template>
            <template v-else-if="quotas[account.id]?.used == null && quotas[account.id]?.available == null">
              <span class="quota-unknown">Quota not available</span>
            </template>
            <template v-else>
              <div class="quota-bar-wrap">
                <div class="quota-bar" :style="`width:${usedPercent(account) ?? 0}%`" :class="(usedPercent(account) ?? 0) >= 90 ? 'quota-bar-warn' : ''"></div>
              </div>
              <div class="quota-labels">
                <span>Used: {{ fmtBytes(effectiveQuota(account)?.used) }}</span>
                <span>
                  Free: {{ fmtBytes(effectiveQuota(account)?.free) }}
                  <span v-if="effectiveQuota(account)?.capped" class="quota-cap-hint">(capped)</span>
                </span>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- Sync Rules -->
      <div class="section-header">
        <h2>Sync Rules</h2>
      </div>

      <div v-if="rules.length === 0" class="empty-state">
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
              <span v-html="fmt(latestJobs[rule.id]?.started_at)"></span>
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
    </template>
  </div>
</template>

<style scoped>
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.section-header h2 {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: .06em;
  margin: 0;
}

.accounts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
}
.account-card { padding: 0; overflow: hidden; }
.account-card-top { padding: 14px 16px 12px; }
.account-name { font-weight: 600; font-size: 14px; margin-bottom: 3px; }
.account-url { font-size: 11px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.account-quota { padding: 10px 16px 14px; border-top: 1px solid var(--border-light); }
.quota-bar-wrap {
  height: 6px;
  background: var(--border-light);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 6px;
}
.quota-bar {
  height: 100%;
  background: var(--accent, #3b82f6);
  border-radius: 3px;
  transition: width .3s;
}
.quota-bar-warn { background: #ef4444; }
.quota-labels { display: flex; justify-content: space-between; font-size: 12px; color: var(--text-muted); }
.quota-cap-hint { font-size: 11px; opacity: .7; }
.quota-error, .quota-unknown { font-size: 12px; color: var(--text-muted); }

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
