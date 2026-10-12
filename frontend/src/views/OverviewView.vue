<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { rulesApi } from '@/api/rules'
import { accountsApi } from '@/api/accounts'

const router = useRouter()
const rules = ref([])
const accounts = ref([])
const loading = ref(true)
const wrap = ref(null)
const edges = ref([])
const size = ref({ w: 0, h: 0 })
const hovered = ref(null)

let ro = null

onMounted(async () => {
  try {
    ;[rules.value, accounts.value] = await Promise.all([rulesApi.list(), accountsApi.list()])
  } finally {
    loading.value = false
  }
  await nextTick()
  if (wrap.value) {
    ro = new ResizeObserver(layoutEdges)
    ro.observe(wrap.value)
  }
  layoutEdges()
})

onBeforeUnmount(() => ro?.disconnect())

const segments = (p) => (p || '').split('/').filter(Boolean)
const normPath = (p) => '/' + segments(p).join('/')
const nodeKey = (accId, p) => `${accId}:${normPath(p)}`

const accountIds = computed(() => new Set(accounts.value.map((a) => a.id)))

// Only rules whose accounts still exist can be drawn
const drawable = computed(() =>
  rules.value.filter(
    (r) => accountIds.value.has(r.source_account_id) && accountIds.value.has(r.dest_account_id),
  ),
)

// Per account: flat, depth-first list of folders used by rules (plus their ancestors)
const cards = computed(() => {
  const trees = new Map(accounts.value.map((a) => [a.id, { endpoint: false, children: new Map() }]))

  function add(accId, path) {
    let node = trees.get(accId)
    for (const seg of segments(path)) {
      if (!node.children.has(seg)) node.children.set(seg, { endpoint: false, children: new Map() })
      node = node.children.get(seg)
    }
    node.endpoint = true
  }
  for (const r of drawable.value) {
    add(r.source_account_id, r.source_path)
    add(r.dest_account_id, r.dest_path)
  }

  return accounts.value.map((acc) => {
    const root = trees.get(acc.id)
    const rows = []
    if (root.endpoint) rows.push({ key: nodeKey(acc.id, '/'), name: '/ (whole account)', depth: 0, endpoint: true })
    const walk = (node, parts, depth) => {
      for (const [name, child] of [...node.children].sort((a, b) => a[0].localeCompare(b[0]))) {
        const p = [...parts, name]
        rows.push({ key: nodeKey(acc.id, p.join('/')), name, depth, endpoint: child.endpoint })
        walk(child, p, depth + 1)
      }
    }
    walk(root, [], root.endpoint ? 1 : 0)
    return { acc, rows }
  })
})

function layoutEdges() {
  const el = wrap.value
  if (!el) return
  const base = el.getBoundingClientRect()
  size.value = { w: el.scrollWidth, h: el.scrollHeight }

  const rects = new Map()
  el.querySelectorAll('[data-node]').forEach((n) => {
    const r = n.getBoundingClientRect()
    rects.set(n.dataset.node, {
      left: r.left - base.left,
      right: r.right - base.left,
      cy: r.top - base.top + r.height / 2,
    })
  })

  // Spread anchors when several edges attach to the same side of a row
  const used = new Map()
  const slot = (key, side) => {
    const k = `${key}|${side}`
    const n = used.get(k) ?? 0
    used.set(k, n + 1)
    return (n % 2 ? 1 : -1) * Math.ceil(n / 2) * 4
  }

  const out = []
  for (const rule of drawable.value) {
    const sKey = nodeKey(rule.source_account_id, rule.source_path)
    const dKey = nodeKey(rule.dest_account_id, rule.dest_path)
    const s = rects.get(sKey)
    const d = rects.get(dKey)
    if (!s || !d) continue

    let sx, dx, sSide, dSide
    if (s.right <= d.left) { sx = s.right; dx = d.left; sSide = 'r'; dSide = 'l' }
    else if (d.right <= s.left) { sx = s.left; dx = d.right; sSide = 'l'; dSide = 'r' }
    else { sx = s.right; dx = d.right; sSide = 'r'; dSide = 'r' }

    const sy = s.cy + slot(sKey, sSide)
    const dy = d.cy + slot(dKey, dSide)
    let path
    if (sSide === dSide) {
      // Same column: loop out to the right of the cards
      const off = 50 + (out.length % 4) * 14
      const x = Math.max(sx, dx) + off
      path = `M${sx},${sy} C${x},${sy} ${x},${dy} ${dx},${dy}`
    } else {
      const mid = Math.max(40, Math.abs(dx - sx) / 2)
      const dir = sSide === 'r' ? 1 : -1
      path = `M${sx},${sy} C${sx + dir * mid},${sy} ${dx - dir * mid},${dy} ${dx},${dy}`
    }
    out.push({ rule, path })
  }
  edges.value = out
}

watch(cards, async () => {
  await nextTick()
  layoutEdges()
})

function openRule(rule) {
  router.push(`/rules/${rule.id}/edit`)
}

function openAccount(acc) {
  router.push({ path: '/accounts', query: { edit: acc.id } })
}

function host(url) {
  try { return new URL(url).host } catch { return url }
}

function edgeTitle(rule) {
  const arrow = rule.direction === 'two_way' ? '⇄' : '→'
  return `${rule.label || `Rule #${rule.id}`} ${arrow}\n${rule.schedule_cron}${rule.enabled ? '' : ' (disabled)'}`
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h1>Overview</h1>
        <p>Accounts, the folders used by sync rules, and the direction of each rule.</p>
      </div>
    </div>

    <div v-if="loading" class="card"><div class="empty-state"><span class="spinner spinner-dark" style="width:24px;height:24px;" /></div></div>
    <div v-else-if="accounts.length === 0" class="card">
      <div class="empty-state">
        <div class="icon">◎</div>
        <h3>Nothing to show yet</h3>
        <p>Add accounts and sync rules to see how they connect.</p>
      </div>
    </div>

    <div v-else class="graph-scroll">
      <div ref="wrap" class="graph">
        <div v-for="c in cards" :key="c.acc.id" class="node card">
          <button class="node-head" title="Open account" @click="openAccount(c.acc)">
            <strong>{{ c.acc.label }}</strong>
            <span class="mono host">{{ host(c.acc.webdav_url) }}</span>
          </button>
          <ul v-if="c.rows.length" class="folders">
            <li
              v-for="row in c.rows"
              :key="row.key"
              :data-node="row.key"
              :class="{ endpoint: row.endpoint }"
              :style="{ paddingLeft: 12 + row.depth * 16 + 'px' }"
            >
              <span class="ico">▸</span>{{ row.name }}
            </li>
          </ul>
          <div v-else class="none">No rules use this account</div>
        </div>

        <svg class="edges" :width="size.w" :height="size.h">
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="context-stroke" />
            </marker>
          </defs>
          <g
            v-for="e in edges"
            :key="e.rule.id"
            class="edge"
            :class="{ off: !e.rule.enabled, hot: hovered === e.rule.id }"
            @click="openRule(e.rule)"
            @mouseenter="hovered = e.rule.id"
            @mouseleave="hovered = null"
          >
            <title>{{ edgeTitle(e.rule) }}</title>
            <path class="hit" :d="e.path" />
            <path
              class="line"
              :d="e.path"
              marker-end="url(#arrow)"
              :marker-start="e.rule.direction === 'two_way' ? 'url(#arrow)' : undefined"
            />
          </g>
        </svg>
      </div>
    </div>
  </div>
</template>

<style scoped>
.graph-scroll { overflow-x: auto; }
.graph {
  position: relative;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 40px 140px;
  padding: 8px 80px 8px 8px;
}
.node { width: 260px; flex: none; overflow: hidden; }
.node-head {
  display: flex; flex-direction: column; align-items: flex-start; gap: 2px;
  width: 100%; padding: 12px 14px;
  background: var(--primary-light); border: 0; border-bottom: 1px solid var(--border);
  color: var(--text); text-align: left; cursor: pointer; font: inherit;
}
.node-head:hover { background: var(--border-light); }
.host { font-size: 12px; color: var(--text-muted); }
.folders { list-style: none; margin: 0; padding: 6px 0; }
.folders li {
  padding: 5px 12px; font-size: 13px; color: var(--text-light);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.folders li.endpoint { color: var(--text); font-weight: 500; background: var(--bg); }
.ico { margin-right: 6px; font-size: 10px; }
.none { padding: 12px 14px; font-size: 13px; color: var(--text-muted); }

.edges { position: absolute; top: 0; left: 0; pointer-events: none; overflow: visible; }
.edge { cursor: pointer; color: var(--primary); }
.edge .hit { fill: none; stroke: transparent; stroke-width: 14; pointer-events: stroke; }
.edge .line { fill: none; stroke: currentColor; stroke-width: 2; }
.edge.off .line { stroke-dasharray: 5 4; opacity: .55; }
.edge.hot .line { stroke-width: 3.5; }
.edge.hot { color: var(--primary-hover); }

@media (max-width: 640px) {
  .graph { gap: 32px 60px; padding-right: 60px; }
  .node { width: 100%; }
}
</style>
