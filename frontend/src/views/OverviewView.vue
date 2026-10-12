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
const sameLinks = ref([])
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
// side is 'src' (left column) or 'dst' (right column)
const nodeKey = (side, accId, p) => `${side}:${accId}:${normPath(p)}`

const accountIds = computed(() => new Set(accounts.value.map((a) => a.id)))

// Only rules whose accounts still exist can be drawn
const drawable = computed(() =>
  rules.value.filter(
    (r) => accountIds.value.has(r.source_account_id) && accountIds.value.has(r.dest_account_id),
  ),
)

// Build one card per account and side, listing the folders used on that side (plus ancestors)
function buildCards(side) {
  const idKey = side === 'src' ? 'source_account_id' : 'dest_account_id'
  const pathKey = side === 'src' ? 'source_path' : 'dest_path'
  const trees = new Map()

  for (const r of drawable.value) {
    if (!trees.has(r[idKey])) trees.set(r[idKey], { endpoint: false, children: new Map() })
    let node = trees.get(r[idKey])
    for (const seg of segments(r[pathKey])) {
      if (!node.children.has(seg)) node.children.set(seg, { endpoint: false, children: new Map() })
      node = node.children.get(seg)
    }
    node.endpoint = true
  }

  return accounts.value
    .filter((acc) => trees.has(acc.id))
    .map((acc) => {
      const root = trees.get(acc.id)
      const rows = []
      if (root.endpoint) rows.push({ key: nodeKey(side, acc.id, '/'), name: '/ (whole account)', depth: 0, endpoint: true })
      const walk = (node, parts, depth) => {
        for (const [name, child] of [...node.children].sort((a, b) => a[0].localeCompare(b[0]))) {
          const p = [...parts, name]
          rows.push({ key: nodeKey(side, acc.id, p.join('/')), name, depth, endpoint: child.endpoint })
          walk(child, p, depth + 1)
        }
      }
      walk(root, [], root.endpoint ? 1 : 0)
      return { acc, rows, headKey: `${side}:${acc.id}` }
    })
}

const sourceCards = computed(() => buildCards('src'))
const destCards = computed(() => buildCards('dst'))
const unusedAccounts = computed(() => {
  const used = new Set([...sourceCards.value, ...destCards.value].map((c) => c.acc.id))
  return accounts.value.filter((a) => !used.has(a.id))
})
// Accounts that appear in both columns get a red dotted link between their two cards
const bothSides = computed(() => {
  const dst = new Set(destCards.value.map((c) => c.acc.id))
  return sourceCards.value.filter((c) => dst.has(c.acc.id)).map((c) => c.acc.id)
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

  // Spread anchors when several edges attach to the same row
  const used = new Map()
  const slot = (key) => {
    const n = used.get(key) ?? 0
    used.set(key, n + 1)
    return (n % 2 ? 1 : -1) * Math.ceil(n / 2) * 4
  }

  const out = []
  for (const rule of drawable.value) {
    const s = rects.get(nodeKey('src', rule.source_account_id, rule.source_path))
    const d = rects.get(nodeKey('dst', rule.dest_account_id, rule.dest_path))
    if (!s || !d) continue
    const sy = s.cy + slot('s' + rule.source_account_id + rule.source_path)
    const dy = d.cy + slot('d' + rule.dest_account_id + rule.dest_path)
    const mid = Math.max(40, (d.left - s.right) / 2)
    out.push({
      rule,
      path: `M${s.right},${sy} C${s.right + mid},${sy} ${d.left - mid},${dy} ${d.left},${dy}`,
    })
  }
  edges.value = out

  const links = []
  for (const id of bothSides.value) {
    const s = rects.get(`src:${id}`)
    const d = rects.get(`dst:${id}`)
    if (!s || !d) continue
    const mid = Math.max(40, (d.left - s.right) / 2)
    links.push({ id, path: `M${s.right},${s.cy} C${s.right + mid},${s.cy} ${d.left - mid},${d.cy} ${d.left},${d.cy}` })
  }
  sameLinks.value = links
}

watch([sourceCards, destCards], async () => {
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
        <div v-for="(cards, side) in { src: sourceCards, dst: destCards }" :key="side" class="col">
          <h2 class="col-title">{{ side === 'src' ? 'Sources' : 'Destinations' }}</h2>
          <div v-for="c in cards" :key="c.headKey" class="node card">
            <button class="node-head" :data-node="c.headKey" title="Open account" @click="openAccount(c.acc)">
              <strong>{{ c.acc.label }}</strong>
              <span class="mono host">{{ host(c.acc.webdav_url) }}</span>
            </button>
            <ul class="folders">
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
          </div>
        </div>
        <p v-if="unusedAccounts.length" class="unused">
          Not used by any rule: {{ unusedAccounts.map((a) => a.label).join(', ') }}
        </p>

        <svg class="edges" :width="size.w" :height="size.h">
          <defs>
            <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill="context-stroke" />
            </marker>
          </defs>
          <path v-for="l in sameLinks" :key="'same' + l.id" class="same" :d="l.path" />
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
  display: grid;
  grid-template-columns: 260px 260px;
  justify-content: start;
  align-items: start;
  column-gap: 160px;
  padding: 8px;
}
.col { display: flex; flex-direction: column; gap: 24px; }
.col-title { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted); margin: 0; }
.unused { grid-column: 1 / -1; margin: 24px 0 0; font-size: 13px; color: var(--text-muted); }
.node { overflow: hidden; }
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
.same { fill: none; stroke: var(--error); stroke-width: 2; stroke-dasharray: 2 5; stroke-linecap: round; }
.edge { cursor: pointer; color: var(--primary); }
.edge .hit { fill: none; stroke: transparent; stroke-width: 14; pointer-events: stroke; }
.edge .line { fill: none; stroke: currentColor; stroke-width: 2; }
.edge.off .line { stroke-dasharray: 5 4; opacity: .55; }
.edge.hot .line { stroke-width: 3.5; }
.edge.hot { color: var(--primary-hover); }

@media (max-width: 640px) {
  .graph { grid-template-columns: 1fr 1fr; column-gap: 56px; }
}
</style>
