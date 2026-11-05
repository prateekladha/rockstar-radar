// Thin API client. Returns {__unauth:true} on 401 so the app can show the login screen.
export async function api(path, opts = {}) {
  const init = { credentials: 'same-origin', ...opts }
  if (opts.body && typeof opts.body !== 'string') {
    init.headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) }
    init.body = JSON.stringify(opts.body)
  }
  const r = await fetch(path, init)
  if (r.status === 401) return { __unauth: true }
  let j = {}
  try { j = await r.json() } catch (e) { /* no body */ }
  if (!r.ok) throw new Error(j.error || `HTTP ${r.status}`)
  return j
}

export const fmt = (x) =>
  typeof x === 'number' ? x.toLocaleString('en-IN', { maximumFractionDigits: 2 }) : '—'
export const bare = (s) => (s || '').replace('NSE:', '').replace('-EQ', '')

// Readable date-time, e.g. "5 Nov, 12:37" (never MM-dd).
export function fmtDateTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d)) return iso
  return d.toLocaleString('en-IN', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
}
