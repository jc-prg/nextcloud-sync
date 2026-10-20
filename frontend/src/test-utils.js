// Shared helpers for the *.spec.js files

function base64url(obj) {
  return btoa(JSON.stringify(obj)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

// An unsigned JWT whose `exp` lies `secondsFromNow` in the future (negative = expired)
export function makeToken(secondsFromNow = 3600, extra = {}) {
  const exp = Math.floor(Date.now() / 1000) + secondsFromNow
  return `${base64url({ alg: 'HS256', typ: 'JWT' })}.${base64url({ sub: 'admin', exp, ...extra })}.sig`
}
