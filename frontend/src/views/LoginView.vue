<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const password = ref('')
const error = ref('')
const loading = ref(false)

onMounted(async () => {
  // Already logged in
  if (auth.token) { router.push('/dashboard'); return }
  // App not configured yet
  const configured = await auth.checkSetup()
  if (!configured) router.push('/setup')
})

async function submit() {
  error.value = ''
  loading.value = true
  try {
    await auth.login(password.value)
    router.push('/dashboard')
  } catch (e) {
    error.value = e?.response?.data?.detail || 'Login failed.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card card">
      <div class="auth-logo">⟳</div>
      <h1 class="auth-title">jc://next-sync/</h1>
      <p class="auth-sub">Sign in to manage your sync rules.</p>

      <form class="auth-form" @submit.prevent="submit">
        <div class="form-group">
          <label>Password</label>
          <input
            v-model="password"
            type="password"
            class="input"
            placeholder="Your password"
            autocomplete="current-password"
            autofocus
            required
          />
        </div>

        <div v-if="error" class="alert alert-error">{{ error }}</div>

        <button type="submit" class="btn btn-primary" :disabled="loading">
          <span v-if="loading" class="spinner" />
          Sign in
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg);
  padding: 24px;
}
.auth-card {
  width: 100%;
  max-width: 360px;
  padding: 36px 32px;
  text-align: center;
}
.auth-logo { font-size: 40px; margin-bottom: 12px; color: var(--primary); }
.auth-title { font-size: 20px; font-weight: 700; margin-bottom: 6px; }
.auth-sub { color: var(--text-muted); font-size: 13.5px; margin-bottom: 24px; }
.auth-form { display: flex; flex-direction: column; gap: 16px; text-align: left; }
.btn-primary { width: 100%; justify-content: center; padding: 10px; }
</style>
