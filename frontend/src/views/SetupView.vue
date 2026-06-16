<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const password = ref('')
const confirm = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  error.value = ''
  if (password.value.length < 8) {
    error.value = 'Password must be at least 8 characters.'
    return
  }
  if (password.value !== confirm.value) {
    error.value = 'Passwords do not match.'
    return
  }
  loading.value = true
  try {
    await auth.setup(password.value)
    router.push('/dashboard')
  } catch (e) {
    error.value = e?.response?.data?.detail || 'Setup failed.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card card">
      <div class="auth-logo">⟳</div>
      <h1 class="auth-title">Welcome to NextSync</h1>
      <p class="auth-sub">Set a password to protect this instance.</p>

      <form class="auth-form" @submit.prevent="submit">
        <div class="form-group">
          <label>Password</label>
          <input
            v-model="password"
            type="password"
            class="input"
            placeholder="Min. 8 characters"
            autocomplete="new-password"
            required
          />
        </div>
        <div class="form-group">
          <label>Confirm password</label>
          <input
            v-model="confirm"
            type="password"
            class="input"
            placeholder="Repeat password"
            autocomplete="new-password"
            required
          />
        </div>

        <div v-if="error" class="alert alert-error">{{ error }}</div>

        <button type="submit" class="btn btn-primary" :disabled="loading">
          <span v-if="loading" class="spinner" />
          Set password &amp; continue
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
  max-width: 380px;
  padding: 36px 32px;
  text-align: center;
}
.auth-logo { font-size: 40px; margin-bottom: 12px; color: var(--primary); }
.auth-title { font-size: 20px; font-weight: 700; margin-bottom: 6px; }
.auth-sub { color: var(--text-muted); font-size: 13.5px; margin-bottom: 24px; }
.auth-form { display: flex; flex-direction: column; gap: 16px; text-align: left; }
.btn-primary { width: 100%; justify-content: center; padding: 10px; }
</style>
