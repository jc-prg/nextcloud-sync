<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { RouterView, RouterLink, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'
import { backendOnline } from '@/stores/connectivity'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const mobileMenuOpen = ref(false)
const mobileHeaderRef = ref(null)

function logout() {
  auth.logout()
  router.push('/login')
}

function closeMobileMenu() {
  mobileMenuOpen.value = false
}

function onClickOutside(e) {
  if (mobileMenuOpen.value && mobileHeaderRef.value && !mobileHeaderRef.value.contains(e.target)) {
    mobileMenuOpen.value = false
  }
}

watch(() => route.path, closeMobileMenu)
onMounted(() => document.addEventListener('click', onClickOutside))
onUnmounted(() => document.removeEventListener('click', onClickOutside))

const nav = [
  { path: '/dashboard', label: 'Dashboard', icon: '◈' },
  { path: '/accounts', label: 'Accounts', icon: '⬡' },
  { path: '/rules', label: 'Sync Rules', icon: '⇄' },
  { path: '/history', label: 'History', icon: '◷' },
]
</script>

<template>
  <div class="layout">
    <!-- Desktop sidebar -->
    <aside class="sidebar">
      <div class="sidebar-brand">
        <span class="brand-icon">⟳</span>
        <span class="brand-name">jc://next-sync/</span>
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

    <!-- Mobile header -->
    <header class="mobile-header" ref="mobileHeaderRef">
      <div class="mobile-brand">
        <span class="brand-icon">⟳</span>
        <span class="brand-name">jc://next-sync/</span>
      </div>
      <button class="hamburger" @click="mobileMenuOpen = !mobileMenuOpen" :aria-expanded="mobileMenuOpen">
        <span></span><span></span><span></span>
      </button>
      <!-- Dropdown -->
      <div v-if="mobileMenuOpen" class="mobile-dropdown">
        <RouterLink
          v-for="item in nav"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: route.path.startsWith(item.path) }"
          @click="closeMobileMenu"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
        </RouterLink>
        <button class="nav-item logout-btn" @click="logout">
          <span class="nav-icon">⎋</span>
          <span>Logout</span>
        </button>
      </div>
    </header>

    <main class="content">
      <div v-if="!backendOnline" class="offline-banner">
        <span class="offline-icon">⚠</span>
        Backend unreachable — retrying…
      </div>
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

.offline-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 20px;
  padding: 10px 16px;
  background: #451a03;
  border: 1px solid #92400e;
  border-radius: var(--radius);
  color: #fbbf24;
  font-size: 13.5px;
  font-weight: 500;
}
.offline-icon { font-size: 15px; }

/* Mobile header */
.mobile-header {
  display: none;
  position: relative;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  height: 54px;
  background: var(--sidebar-bg);
  flex-shrink: 0;
  z-index: 100;
}
.mobile-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}
.mobile-brand .brand-icon { font-size: 20px; color: var(--sidebar-accent); }
.mobile-brand .brand-name { font-size: 15px; font-weight: 700; color: #fff; }

.hamburger {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 5px;
  width: 36px;
  height: 36px;
  background: transparent;
  border: none;
  cursor: pointer;
  padding: 4px;
}
.hamburger span {
  display: block;
  height: 2px;
  background: #fff;
  border-radius: 2px;
  transition: opacity .15s;
}

.mobile-dropdown {
  position: absolute;
  top: 54px;
  left: 0;
  right: 0;
  background: var(--sidebar-bg);
  border-top: 1px solid rgba(255,255,255,.06);
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px;
  box-shadow: 0 8px 16px rgba(0,0,0,.25);
}

@media (max-width: 640px) {
  .sidebar { display: none; }
  .mobile-header { display: flex; }
  .layout { flex-direction: column; }
  .content { padding: 16px; }
}
</style>
