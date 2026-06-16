<script setup>
import { RouterView, RouterLink, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

function logout() {
  auth.logout()
  router.push('/login')
}

const nav = [
  { path: '/dashboard', label: 'Dashboard', icon: '◈' },
  { path: '/accounts', label: 'Accounts', icon: '⬡' },
  { path: '/rules', label: 'Sync Rules', icon: '⇄' },
  { path: '/history', label: 'History', icon: '◷' },
]
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="sidebar-brand">
        <span class="brand-icon">⟳</span>
        <span class="brand-name">NextSync</span>
      </div>

      <nav class="sidebar-nav">
        <RouterLink
          v-for="item in nav"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: route.path.startsWith(item.path) }"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <button class="nav-item logout-btn" @click="logout">
        <span class="nav-icon">⎋</span>
        <span>Logout</span>
      </button>
    </aside>

    <main class="content">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  height: 100%;
}

.sidebar {
  width: var(--sidebar-width);
  background: var(--sidebar-bg);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  padding: 0 0 16px;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 20px 18px 18px;
  border-bottom: 1px solid rgba(255,255,255,.06);
  margin-bottom: 8px;
}
.brand-icon {
  font-size: 22px;
  color: var(--sidebar-accent);
}
.brand-name {
  font-size: 16px;
  font-weight: 700;
  color: #fff;
  letter-spacing: -.01em;
}

.sidebar-nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 8px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: var(--radius);
  color: var(--sidebar-text);
  font-size: 13.5px;
  font-weight: 500;
  text-decoration: none;
  border: none;
  background: transparent;
  cursor: pointer;
  width: 100%;
  transition: background .12s, color .12s;
}
.nav-item:hover { background: var(--sidebar-hover); color: #d0d8ef; }
.nav-item.active { background: var(--sidebar-active); color: var(--sidebar-active-text); }
.nav-item.active .nav-icon { color: var(--sidebar-accent); }

.nav-icon { font-size: 16px; width: 20px; text-align: center; }

.logout-btn {
  margin: 0 8px;
  color: var(--sidebar-text);
}
.logout-btn:hover { color: var(--error); background: rgba(239,68,68,.1); }

.content {
  flex: 1;
  overflow-y: auto;
  padding: 28px 32px;
}
</style>
