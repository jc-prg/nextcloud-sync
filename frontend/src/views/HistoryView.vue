<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { jobsApi } from '@/api/jobs'
import { rulesApi } from '@/api/rules'
import StatusBadge from '@/components/StatusBadge.vue'

const route = useRoute()

const rules = ref([])
const jobs = ref([])
const total = ref(0)
const loading = ref(true)
const expandedJob = ref(null)
const jobLogs = ref({})
const logsLoading = ref(null)
const aborting = ref(null)

const filterRuleId = ref(route.query.rule_id ? Number(route.query.rule_id) : null)
const page = ref(0)
const PAGE_SIZE = 30

let pollTimer = null
let logPollTimer = null
let durationTimer = null

const now = ref(Date.now())

onMounted(async () => {
  rules.value = await rulesApi.list()
  await loadJobs()
  startPolling()
})

onUnmounted(() => { stopPolling(); stopLogPolling(); stopDurationTimer() })

function hasRunningJobs() {
  return jobs.value.some((j) => j.status === 'running')
}

function startDurationTimer() {
  if (!durationTimer) {
    durationTimer = setInterval(() => { now.value = Date.now() }, 15000)
  }
}

function stopDurationTimer() {
  if (durationTimer) { clearInterval(durationTimer); durationTimer = null }
}

function startPolling() {
  stopPolling()
  if (hasRunningJobs()) {
    startDurationTimer()
    pollTimer = setInterval(async () => {
      await loadJobs(true)
      // If the expanded job just finished, do a final log refresh then stop log polling
      if (expandedJob.value) {
        const job = jobs.value.find((j) => j.id === expandedJob.value)
        if (job && job.status !== 'running') {
          stopLogPolling()
          const data = await jobsApi.logs(expandedJob.value)
          jobLogs.value[expandedJob.value] = data.items
        }
      }
      if (!hasRunningJobs()) { stopPolling(); stopDurationTimer() }
    }, 3000)
  }
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

function startLogPolling(jobId) {
  stopLogPolling()
  logPollTimer = setInterval(async () => {
    const data = await jobsApi.logs(jobId)
    jobLogs.value[jobId] = data.items
  }, 15000)
}

function stopLogPolling() {
  if (logPollTimer) { clearInterval(logPollTimer); logPollTimer = null }
}

async function loadJobs(silent = false) {
  if (!silent) loading.value = true
  try {
    const params = { limit: PAGE_SIZE, offset: page.value * PAGE_SIZE }
    if (filterRuleId.value) params.rule_id = filterRuleId.value
    const data = await jobsApi.list(params)
    jobs.value = data.items
    total.value = data.total
  } finally {
    if (!silent) loading.value = false
  }
}

async function abortJob(job) {
  if (aborting.value === job.id) return
  aborting.value = job.id
  try {
    await jobsApi.abort(job.id)
    await loadJobs(true)
    startPolling()
  } finally {
    aborting.value = null
  }
}

async function toggleLogs(job) {
  if (expandedJob.value === job.id) {
    expandedJob.value = null
    stopLogPolling()
    return
  }
  expandedJob.value = job.id
  logsLoading.value = job.id
  try {
    const data = await jobsApi.logs(job.id)
    jobLogs.value[job.id] = data.items
  } finally {
    logsLoading.value = null
  }
  if (job.status === 'running') {
    startLogPolling(job.id)
  }
}

function ruleLabel(id) {
  return rules.value.find((r) => r.id === id)?.label ?? `Rule #${id}`
}

// SQLite returns naive ISO strings (no Z); append Z so JS treats them as UTC
function parseUTC(dt) {
  if (!dt) return null
  return new Date(/[Z+]/.test(dt.slice(-6)) ? dt : dt + 'Z')
}

function fmt(dt) {
  if (!dt) return '—'
  const d = parseUTC(dt)
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  const sameDay = (a, b) =>
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  const timeStr = d.toLocaleTimeString()
  if (sameDay(d, today)) return `today ${timeStr}`
  if (sameDay(d, yesterday)) return `yesterday ${timeStr}`
  return d.toLocaleString()
}

function duration(job) {
  const end = job.finished_at ? parseUTC(job.finished_at) : now.value
  const ms = end - parseUTC(job.started_at)
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`
}

function transferred(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let v = bytes, i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${v.toFixed(1)} ${units[i]}`
}

const totalPages = computed(() => Math.ceil(total.value / PAGE_SIZE))

async function changePage(n) {
  page.value = n
  await loadJobs()
  startPolling()
}

async function changeFilter() {
  page.value = 0
  await loadJobs()
  startPolling()
}

const LOG_LEVEL_CLASS = { info: '', warning: 'log-warn', error: 'log-error' }
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h1>History</h1>
        <p>Sync job runs and per-file logs.</p>
      </div>
      <div class="actions">
        <select class="input" style="width:200px;" v-model="filterRuleId" @change="changeFilter">
          <option :value="null">All rules</option>
          <option v-for="r in rules" :key="r.id" :value="r.id">{{ r.label }}</option>
        </select>
        <button class="btn btn-secondary" @click="loadJobs">↺</button>
      </div>
    </div>

    <div class="card">
      <div v-if="loading" class="empty-state">
        <span class="spinner spinner-dark" style="width:24px;height:24px;" />
      </div>
      <div v-else-if="jobs.length === 0" class="empty-state">
        <div class="icon">◷</div>
        <h3>No jobs yet</h3>
        <p>Sync runs will appear here after the first job executes.</p>
      </div>
      <template v-else>
        <table class="table">
          <thead>
            <tr>
              <th></th>
              <th>Rule</th>
              <th>Started</th>
              <th>Duration</th>
              <th>Status</th>
              <th>Added</th>
              <th>Updated</th>
              <th>Deleted</th>
              <th>Transferred</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <template v-for="job in jobs" :key="job.id">
              <tr class="job-row" @click="toggleLogs(job)">
                <td class="expand-col">
                  <span class="expand-arrow" :class="{ open: expandedJob === job.id }">▶</span>
                </td>
                <td>{{ ruleLabel(job.sync_rule_id) }}</td>
                <td>{{ fmt(job.started_at) }}</td>
                <td :style="job.status === 'running' ? 'color:#60a5fa;font-variant-numeric:tabular-nums' : ''">{{ duration(job) }}</td>
                <td><StatusBadge :status="job.status" /></td>
                <td>{{ job.files_added }}</td>
                <td>{{ job.files_updated }}</td>
                <td>{{ job.files_deleted }}</td>
                <td>{{ transferred(job.bytes_transferred) }}</td>
                <td class="action-col" @click.stop>
                  <button
                    v-if="job.status === 'running'"
                    class="btn btn-danger btn-sm"
                    :disabled="aborting === job.id"
                    @click="abortJob(job)"
                  >
                    <span v-if="aborting === job.id" class="spinner spinner-dark" style="width:12px;height:12px;" />
                    Abort
                  </button>
                </td>
              </tr>
              <tr v-if="expandedJob === job.id" class="logs-row">
                <td colspan="10" class="logs-cell">
                  <div v-if="logsLoading === job.id" class="log-loading">
                    <span class="spinner spinner-dark" style="width:14px;height:14px;" /> Loading logs…
                  </div>
                  <div v-else-if="!jobLogs[job.id]?.length" class="log-empty">No log entries.</div>
                  <div v-else class="log-list">
                    <div
                      v-for="log in jobLogs[job.id]"
                      :key="log.id"
                      class="log-entry"
                      :class="LOG_LEVEL_CLASS[log.level]"
                    >
                      <span class="log-time mono">{{ parseUTC(log.timestamp).toLocaleTimeString() }}</span>
                      <span class="log-level">{{ log.level }}</span>
                      <span class="log-msg">{{ log.message }}</span>
                    </div>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>

        <!-- Pagination -->
        <div v-if="totalPages > 1" class="pagination">
          <button class="btn btn-secondary btn-sm" :disabled="page === 0" @click="changePage(page - 1)">← Prev</button>
          <span class="page-info">Page {{ page + 1 }} of {{ totalPages }}</span>
          <button class="btn btn-secondary btn-sm" :disabled="page >= totalPages - 1" @click="changePage(page + 1)">Next →</button>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.job-row { cursor: pointer; }
.job-row:hover td { background: var(--border-light); }

.expand-col { width: 32px; }
.action-col { width: 80px; text-align: right; }
.expand-arrow {
  display: inline-block;
  font-size: 10px;
  color: var(--text-muted);
  transition: transform .15s;
}
.expand-arrow.open { transform: rotate(90deg); }

.logs-row td { padding: 0; }
.logs-cell {
  background: #0f1117;
  padding: 12px 16px;
  border-bottom: 2px solid var(--primary);
  /* Prevent the cell from expanding the table beyond the job-row width */
  max-width: 0;
  overflow: hidden;
}

.log-loading, .log-empty {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #6b7280;
  font-size: 12.5px;
}

.log-list { display: flex; flex-direction: column; gap: 2px; max-height: 280px; overflow-y: auto; overflow-x: auto; }
.log-entry {
  display: flex;
  gap: 10px;
  font-size: 12px;
  font-family: 'SF Mono', 'Fira Code', monospace;
  color: #d1d5db;
  line-height: 1.6;
  min-width: max-content;
}
.log-entry.log-error { color: #f87171; }
.log-entry.log-warn { color: #fbbf24; }

.log-time { color: #6b7280; flex-shrink: 0; }
.log-level {
  flex-shrink: 0;
  width: 50px;
  text-transform: uppercase;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .05em;
  padding-top: 3px;
  color: #9ca3af;
}
.log-entry.log-error .log-level { color: #f87171; }
.log-entry.log-warn .log-level { color: #fbbf24; }
.log-msg { flex: 1; white-space: nowrap; }

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 14px;
  border-top: 1px solid var(--border);
}
.page-info { font-size: 13px; color: var(--text-muted); }
</style>
