<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { settingsApi } from '@/api/settings'

const router = useRouter()
const props = defineProps({
  rules: { type: Array, required: true },
  accounts: { type: Array, required: true },
  devices: { type: Array, default: () => [] },
  apps: { type: Array, default: () => [] },
})
const rules = computed(() => props.rules)
const accounts = computed(() => props.accounts)
const wrap = ref(null)
const edges = ref([])
const clientEdges = ref([])
const appEdges = ref([])
const sameLinks = ref([])
const size = ref({ w: 0, h: 0 })
const hovered = ref(null)

let ro = null

onMounted(async () => {
  loadOrder()
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
// side is 'dev' (devices column), 'src' (sources), 'dst' (destinations) or 'app' (apps, below the destinations)
const nodeKey = (side, accId, p) => `${side}:${accId}:${normPath(p)}`

const accountIds = computed(() => new Set(accounts.value.map((a) => a.id)))

// Only rules whose accounts still exist can be drawn
const drawable = computed(() =>
  rules.value.filter(
    (r) => accountIds.value.has(r.source_account_id) && accountIds.value.has(r.dest_account_id),
  ),
)

// Device and app folders link to the account's source card; to its destination card
// only if rules use the account as destination alone.
const linkSide = computed(() => {
  const ruleSrc = new Set(drawable.value.map((r) => r.source_account_id))
  const ruleDst = new Set(drawable.value.map((r) => r.dest_account_id))
  return (id) => (ruleSrc.has(id) || !ruleDst.has(id) ? 'src' : 'dst')
})

// Folders of devices (synced by the Nextcloud client) linked to an existing account
const deviceLinks = computed(() =>
  props.devices.flatMap((device) =>
    device.folders
      .filter((folder) => accountIds.value.has(folder.account_id))
      .map((folder) => ({ device, folder, side: linkSide.value(folder.account_id) })),
  ),
)

// Account folders used by apps via WebDAV
const appLinks = computed(() =>
  props.apps.flatMap((app) =>
    app.folders
      .map((folder, idx) => ({ app, folder, idx, side: linkSide.value(folder.account_id) }))
      .filter((l) => accountIds.value.has(l.folder.account_id)),
  ),
)

// Build one card per account and side, listing the folders used on that side (plus ancestors)
function buildCards(side) {
  const idKey = side === 'src' ? 'source_account_id' : 'dest_account_id'
  const pathKey = side === 'src' ? 'source_path' : 'dest_path'
  const trees = new Map()
  const endpoints = [
    ...drawable.value.map((r) => [r[idKey], r[pathKey]]),
    ...[...deviceLinks.value, ...appLinks.value]
      .filter((l) => l.side === side)
      .map((l) => [l.folder.account_id, l.folder.account_path]),
  ]

  for (const [accId, path] of endpoints) {
    if (!trees.has(accId)) trees.set(accId, { endpoint: false, children: new Map() })
    let node = trees.get(accId)
    for (const seg of segments(path)) {
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

// Device folders are kept as a flat, tree-ordered list by the backend
const deviceCards = computed(() =>
  props.devices.map((device) => ({
    device,
    headKey: `dev:${device.id}`,
    rows: device.folders.map((f) => ({
      key: nodeKey('dev', device.id, f.path),
      name: segments(f.path).at(-1),
      depth: segments(f.path).length - 1,
      endpoint: accountIds.value.has(f.account_id),
    })),
  })),
)
// One row per account folder the app uses
const appCards = computed(() =>
  props.apps.map((app) => ({
    app,
    headKey: `app:${app.id}`,
    rows: app.folders.map((f, idx) => ({
      key: `app:${app.id}:${idx}`,
      name: `${accountLabel(f.account_id)}:${normPath(f.account_path)}`,
      depth: 0,
      endpoint: accountIds.value.has(f.account_id),
    })),
  })),
)
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

  const client = []
  for (const { device, folder, side } of deviceLinks.value) {
    const s = rects.get(nodeKey('dev', device.id, folder.path))
    const d = rects.get(nodeKey(side, folder.account_id, folder.account_path))
    if (!s || !d) continue
    const sy = s.cy + slot('v' + device.id + folder.path)
    const dy = d.cy + slot(side[0] + folder.account_id + normPath(folder.account_path))
    const mid = Math.max(40, (d.left - s.right) / 2)
    client.push({
      key: `${device.id}:${folder.path}`,
      device,
      title: `${device.label}:${folder.path} ⇄ ${accountLabel(folder.account_id)}:${normPath(folder.account_path)}\nNextcloud client`,
      path: `M${s.right},${sy} C${s.right + mid},${sy} ${d.left - mid},${dy} ${d.left},${dy}`,
    })
  }
  clientEdges.value = client

  const appOut = []
  for (const { app, folder, idx, side } of appLinks.value) {
    const s = rects.get(nodeKey(side, folder.account_id, folder.account_path))
    const d = rects.get(`app:${app.id}:${idx}`)
    if (!s || !d) continue
    const sy = s.cy + slot(side[0] + folder.account_id + normPath(folder.account_path))
    const dy = d.cy
    let path
    if (side === 'dst') {
      // Account card sits in the same column above the app: loop around the right side
      const out = Math.max(s.right, d.right) + 48
      path = `M${s.right},${sy} C${out},${sy} ${out},${dy} ${d.right},${dy}`
    } else {
      const mid = Math.max(40, (d.left - s.right) / 2)
      path = `M${s.right},${sy} C${s.right + mid},${sy} ${d.left - mid},${dy} ${d.left},${dy}`
    }
    appOut.push({
      key: `${app.id}:${idx}`,
      app,
      title: `${app.label} ⇄ ${accountLabel(folder.account_id)}:${normPath(folder.account_path)}\nWebDAV app`,
      path,
    })
  }
  appEdges.value = appOut

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

watch(columns, async () => {
  await nextTick()
  layoutEdges()
})

function openRule(rule) {
  router.push(`/rules/${rule.id}/edit`)
}

function openAccount(acc) {
  router.push({ path: '/accounts', query: { account: acc.id } })
}

function openDevice(device) {
  router.push({ path: '/accounts', query: { device: device.id } })
}

function openApp(app) {
  router.push({ path: '/accounts', query: { app: app.id } })
}

function accountLabel(id) {
  return accounts.value.find((a) => a.id === id)?.label ?? `#${id}`
}

// ── Card order per column (drag & drop, stored in the backend) ────────────

const ORDER_KEY = 'overview_order'
const order = ref({}) // side → [headKey, …]; cards not listed keep their default order at the end
const drag = ref(null) // { side, key, before } while a card is dragged

async function loadOrder() {
  try {
    order.value = (await settingsApi.get(ORDER_KEY)) ?? {}
  } catch {
    // keep the default order
  }
}

function sorted(side, cards) {
  const keys = order.value[side] ?? []
  const pos = (c) => {
    const i = keys.indexOf(c.headKey)
    return i < 0 ? Infinity : i
  }
  return [...cards].sort((a, b) => pos(a) - pos(b)) // stable: unlisted cards keep their order
}

const columns = computed(() => [
  ...(props.devices.length ? [{ side: 'dev', title: 'Devices', cards: sorted('dev', deviceCards.value) }] : []),
  { side: 'src', title: 'Sources', cards: sorted('src', sourceCards.value) },
  {
    side: 'dst',
    title: props.apps.length ? 'Destinations & Apps' : 'Destinations',
    cards: sorted('dst', [...destCards.value, ...appCards.value]),
  },
])

function onDragStart(e, col, card) {
  drag.value = { side: col.side, key: card.headKey, before: order.value[col.side] }
  e.dataTransfer.effectAllowed = 'move'
  e.dataTransfer.setData('text/plain', card.headKey) // Firefox only starts a drag with data
}

// Reorders live while dragging over another card of the same column
function onDragOver(e, col, card) {
  if (!drag.value || drag.value.side !== col.side) return
  e.preventDefault()
  e.dataTransfer.dropEffect = 'move'
  if (card.headKey === drag.value.key) return
  const r = e.currentTarget.getBoundingClientRect()
  const after = e.clientY > r.top + r.height / 2
  const keys = col.cards.map((c) => c.headKey).filter((k) => k !== drag.value.key)
  keys.splice(keys.indexOf(card.headKey) + (after ? 1 : 0), 0, drag.value.key)
  if (keys.join() !== col.cards.map((c) => c.headKey).join()) {
    order.value = { ...order.value, [col.side]: keys }
  }
}

async function onDragEnd(e) {
  const d = drag.value
  drag.value = null
  if (!d) return
  if (e.dataTransfer.dropEffect === 'none') {
    // Cancelled (Esc or dropped outside the column): restore the previous order
    order.value = { ...order.value, [d.side]: d.before }
    return
  }
  try {
    await settingsApi.put(ORDER_KEY, order.value)
  } catch {
    alert('Could not save the order')
  }
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
    <div class="graph-scroll">
      <div ref="wrap" class="graph" :class="{ 'with-apps': apps.length }" :style="{ '--cols': columns.length }">
        <div
          v-for="col in columns"
          :key="col.side"
          class="col"
          @dragover="drag?.side === col.side && $event.preventDefault()"
          @drop.prevent
        >
          <h2 class="col-title">{{ col.title }}</h2>
          <div
            v-for="c in col.cards"
            :key="c.headKey"
            class="node card"
            :class="{ device: c.device, app: c.app, dragging: drag?.key === c.headKey }"
            draggable="true"
            title="Drag to reorder within the column"
            @dragstart="onDragStart($event, col, c)"
            @dragover="onDragOver($event, col, c)"
            @drop.prevent
            @dragend="onDragEnd"
          >
            <button v-if="c.device" class="node-head" :data-node="c.headKey" title="Edit device" @click="openDevice(c.device)">
              <strong>{{ c.device.label }}</strong>
              <span class="host">Nextcloud client</span>
            </button>
            <button v-else-if="c.app" class="node-head" :data-node="c.headKey" title="Edit app" @click="openApp(c.app)">
              <strong>{{ c.app.label }}</strong>
              <span class="host">{{ c.app.note || 'WebDAV app' }}</span>
            </button>
            <button v-else class="node-head" :data-node="c.headKey" title="Open account" @click="openAccount(c.acc)">
              <strong>{{ c.acc.label }}</strong>
              <span class="mono host">{{ host(c.acc.webdav_url) }}</span>
            </button>
            <p v-if="c.rows.length === 0" class="none">No folders yet</p>
            <ul v-else class="folders">
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
            <marker
              v-for="m in [{ id: 'arrow', color: 'var(--primary)' }, { id: 'arrow-hot', color: 'var(--primary-hover)' }, { id: 'arrow-client', color: 'var(--client)' }, { id: 'arrow-app', color: 'var(--app)' }]"
              :id="m.id"
              :key="m.id"
              viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"
            >
              <path d="M0,0 L10,5 L0,10 z" :style="{ fill: m.color }" />
            </marker>
          </defs>
          <path v-for="l in sameLinks" :key="'same' + l.id" class="same" :d="l.path" />
          <g
            v-for="e in appEdges"
            :key="'app' + e.key"
            class="edge app"
            :class="{ hot: hovered === 'app' + e.key }"
            @click="openApp(e.app)"
            @mouseenter="hovered = 'app' + e.key"
            @mouseleave="hovered = null"
          >
            <title>{{ e.title }}</title>
            <path class="hit" :d="e.path" />
            <path class="line" :d="e.path" marker-start="url(#arrow-app)" marker-end="url(#arrow-app)" />
          </g>
          <g
            v-for="e in clientEdges"
            :key="'client' + e.key"
            class="edge client"
            :class="{ hot: hovered === 'client' + e.key }"
            @click="openDevice(e.device)"
            @mouseenter="hovered = 'client' + e.key"
            @mouseleave="hovered = null"
          >
            <title>{{ e.title }}</title>
            <path class="hit" :d="e.path" />
            <path class="line" :d="e.path" marker-start="url(#arrow-client)" marker-end="url(#arrow-client)" />
          </g>
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
              
              :marker-end="`url(#${hovered === e.rule.id ? 'arrow-hot' : 'arrow'})`"
              :marker-start="e.rule.direction === 'two_way' ? `url(#${hovered === e.rule.id ? 'arrow-hot' : 'arrow'})` : undefined"
            />
          </g>
        </svg>
      </div>
    </div>
</template>

<style scoped>
.graph-scroll { overflow-x: auto; }
.graph {
  position: relative;
  display: grid;
  grid-template-columns: repeat(var(--cols), 260px);
  justify-content: start;
  --client: #8b5cf6;
  --app: #0d9488;
  align-items: start;
  column-gap: 160px;
  padding: 8px;
}
/* Room for edges looping from a destination card to an app card in the same column */
.graph.with-apps { padding-right: 64px; }
.col { display: flex; flex-direction: column; gap: 24px; }
.col-title { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted); margin: 0; }
.unused { grid-column: 1 / -1; margin: 24px 0 0; font-size: 13px; color: var(--text-muted); }
.node { overflow: hidden; cursor: grab; }
.node.dragging { opacity: .45; outline: 2px dashed var(--primary); outline-offset: -2px; }
.node-head {
  display: flex; flex-direction: column; align-items: flex-start; gap: 2px;
  width: 100%; padding: 12px 14px;
  background: var(--primary-light); border: 0; border-bottom: 1px solid var(--border);
  color: var(--text); text-align: left; cursor: pointer; font: inherit;
}
.node-head:hover { background: var(--border-light); }
.host { font-size: 12px; color: var(--text-muted); }
.device .node-head { background: color-mix(in srgb, var(--client) 12%, var(--card-bg)); }
.device .node-head:hover { background: color-mix(in srgb, var(--client) 20%, var(--card-bg)); }
.app .node-head { background: color-mix(in srgb, var(--app) 12%, var(--card-bg)); }
.app .node-head:hover { background: color-mix(in srgb, var(--app) 20%, var(--card-bg)); }
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
.edge.client, .edge.client.hot { color: var(--client); }
.edge.app, .edge.app.hot { color: var(--app); }

@media (max-width: 640px) {
  .graph { grid-template-columns: repeat(var(--cols), minmax(160px, 1fr)); column-gap: 56px; }
}
</style>
