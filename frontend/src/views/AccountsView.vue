<script setup>
/**
 * Manages everything the overview shows as endpoints: WebDAV accounts, devices
 * synced by the Nextcloud client, and apps using account folders via WebDAV.
 *
 * Deep links from the overview: /accounts?account=<id> | ?device=<id> | ?app=<id>
 */
import { ref, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AccountsPanel from '@/components/AccountsPanel.vue'
import DevicesPanel from '@/components/DevicesPanel.vue'
import AppsPanel from '@/components/AppsPanel.vue'

const route = useRoute()
const router = useRouter()

// Read once: the panels open the matching entry when they have loaded
const open = {
  account: Number(route.query.account) || null,
  device: Number(route.query.device) || null,
  app: Number(route.query.app) || null,
}
const accountsVersion = ref(0)
const sections = { account: ref(null), device: ref(null), app: ref(null) }

onMounted(async () => {
  if (!Object.values(open).some(Boolean)) return
  router.replace({ path: '/accounts' })
  await nextTick()
  const kind = Object.keys(open).find((k) => open[k])
  sections[kind].value?.scrollIntoView({ block: 'start' })
})
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h1>Accounts, Devices &amp; Apps</h1>
        <p>Everything the sync overview connects: WebDAV accounts, client-synced devices and WebDAV apps.</p>
      </div>
    </div>

    <section :ref="sections.account" class="section">
      <AccountsPanel :open-id="open.account" @changed="accountsVersion++" />
    </section>
    <section :ref="sections.device" class="section">
      <DevicesPanel :open-id="open.device" :accounts-version="accountsVersion" />
    </section>
    <section :ref="sections.app" class="section">
      <AppsPanel :open-id="open.app" :accounts-version="accountsVersion" />
    </section>
  </div>
</template>

<style scoped>
.section + .section {
  margin-top: 36px;
  padding-top: 28px;
  border-top: 1px solid var(--border);
}
</style>
