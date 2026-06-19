import { ref } from 'vue'

export const backendOnline = ref(true)

let _timer = null

export function markOnline() {
  backendOnline.value = true
  if (_timer) { clearInterval(_timer); _timer = null }
}

export function markOffline() {
  backendOnline.value = false
  if (!_timer) _timer = setInterval(_probe, 5000)
}

async function _probe() {
  try {
    // Any HTTP response (even 401/403) means the server is reachable
    await fetch('/api/rules', { method: 'HEAD' })
    markOnline()
  } catch {
    // still unreachable
  }
}
