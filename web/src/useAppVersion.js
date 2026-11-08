import { useEffect, useState } from 'react'

// Detects when a newer build has been deployed while this tab is open. The build ID is baked into the
// bundle at build time (__BUILD_ID__, injected by vite.config.js); we poll /version.json (which carries
// the ID of whatever build the server is currently serving) and flag a mismatch so the app can prompt
// a reload — instead of the user unknowingly running stale JS until they happen to refresh.
const CURRENT = typeof __BUILD_ID__ !== 'undefined' ? __BUILD_ID__ : null

export function useUpdateAvailable() {
  const [stale, setStale] = useState(false)
  useEffect(() => {
    if (!CURRENT) return
    let alive = true
    const check = async () => {
      if (!alive || stale) return
      try {
        const r = await fetch('/version.json?t=' + Date.now(), { cache: 'no-store' })
        if (!r.ok) return
        const j = await r.json()
        if (alive && j.build && j.build !== CURRENT) setStale(true)
      } catch { /* offline, or not served (dev) — ignore */ }
    }
    check()
    const iv = setInterval(check, 60000)                       // poll every minute
    const onFocus = () => check()                              // and whenever the tab regains focus
    window.addEventListener('focus', onFocus)
    return () => { alive = false; clearInterval(iv); window.removeEventListener('focus', onFocus) }
  }, [stale])
  return stale
}
