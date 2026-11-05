// PostHog product analytics — async, non-blocking, privacy-proxied.
//   * posthog-js is DYNAMICALLY imported (its own chunk) so it never sits in the critical path
//     or delays first paint.
//   * Events are sent to our own /ingest path (Caddy reverse-proxies it to PostHog) — first-party,
//     so ad-blockers don't drop them and no third-party host is hit directly.
//   * Fully env-gated: with no VITE_POSTHOG_KEY it is a complete no-op (zero network, zero cost).
// Autocapture records clicks/inputs; capture_pageleave records scroll depth; SPA page views are
// sent manually on route change (see App.jsx). identify() attaches user attributes.

const KEY = import.meta.env.VITE_POSTHOG_KEY
const HOST = import.meta.env.VITE_POSTHOG_HOST || '/ingest'

let ph = null
let queue = []

export function initAnalytics() {
  if (!KEY || ph) return
  import('posthog-js').then(({ default: posthog }) => {
    posthog.init(KEY, {
      api_host: HOST,
      ui_host: 'https://us.posthog.com',
      capture_pageview: false,       // we send $pageview on SPA route change
      capture_pageleave: true,       // scroll depth + time on page
      autocapture: true,             // clicks, inputs, form submits
      person_profiles: 'identified_only',
    })
    ph = posthog
    queue.forEach((fn) => { try { fn(posthog) } catch { /* ignore */ } })
    queue = []
  }).catch(() => { /* analytics must never break the app */ })
}

function withPH(fn) {
  if (ph) { try { fn(ph) } catch { /* ignore */ } }
  else if (KEY) queue.push(fn)   // buffer until posthog finishes loading
}

export function identify(u) {
  if (!u) return
  withPH((p) => p.identify(String(u.id), {
    email: u.email, name: u.name, role: u.role, household_id: u.household_id,
  }))
}

export function resetIdentity() { withPH((p) => p.reset()) }
export function capture(event, props) { withPH((p) => p.capture(event, props)) }
export function pageview() { withPH((p) => p.capture('$pageview')) }
