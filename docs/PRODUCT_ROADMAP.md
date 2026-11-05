# Rockstar Radar — Product Roadmap

> From "a script one person runs in a terminal" to "a product any user can use."
> Scope decision (2026-11-05): **build private now, architect for public.** Each user connects
> their **own** FYERS account; the product computes signals on that user's own data, for that user
> only. This keeps us clear of market-data redistribution limits and SEBI advisory registration
> (personal tool, not a published-advice service), and happens to match FYERS' per-account limits.

Last updated: **2026-11-05**

---

## Guiding architecture principle (the "design for public" cost, paid now)
- **Per-user isolation from day one.** No shared global broker state. Credentials, tokens, selections,
  baselines, and the radar engine are all scoped to a `user_id` / session.
- **Broker behind an interface.** All FYERS calls go through a `MarketDataProvider` abstraction so a
  second broker (or a hosted multi-tenant variant) is config, not a rewrite.
- **Secrets never logged, never shared.** Tokens are per-user secrets; encrypted at rest once hosted.

## Phase 1 — Realtime engine (backend, offline-testable) — DONE (offline), pending live session
Built & tested offline 2026-11-05. See `docs/REALTIME_PHASE1_STATUS.md`.
**Goal:** confirmations fire ~1s after a 5-minute bar closes, not minutes later.
- `radar/aggregator.py` — `LiveCandleBuilder`: aggregate FYERS SymbolUpdate ticks into completed
  5-minute candles (exchange-time aligned, cumulative-volume deltas, never emits a partial bar).
- Feed completed **local** bars into confirmation as **PROVISIONAL** signals.
- Keep REST history as the **authoritative backstop**: it reconciles each provisional bar — upgrading
  it to confirmed, or retracting a local false positive. (This deliberately relaxes the current
  "never confirm from non-authoritative data" rule, with an explicit provisional label.)
- Tests: aggregation correctness, no-partial-bar, volume deltas, reconcile upgrade/retract.

## Phase 2 — Real app + onboarding (kills the terminal) — DONE (offline), pending live use
Built & tested 2026-11-05 (80 tests pass). **FastAPI Control Center** at `radar/api.py` +
`radar/control.py` + `webapp/index.html`; launch with `python launch.py app` (default port 8765).
- One web page: FYERS connect, watchlist editor, strategy settings, scanner start/stop, live radar.
- **One-click login** via `/auth/callback` (needs FYERS app Redirect URL = `http://127.0.0.1:8765/auth/callback`
  + matching `FYERS_REDIRECT_URI` in `.env`). Manual-paste fallback works with any redirect URL.
- Scanner managed as the proven `launch.py run` subprocess (internal port 8899), live state proxied.
- `launch.py app` is exempt from the API file-lock so its scanner subprocess can take the lock.

Added 2026-11-05: **₹-risk position sizing** (`radar/risk.py`; `capital_inr`+`risk_pct` config;
qty + rupee risk in every ticket/snapshot row and the live table), **Telegram alerts**
(`radar/notify.py`), **trading-grade UI** (design system `webapp/static/app.css`; app shell with
app-bar/pills, KPI strip, trade-ticket cards, full 100-stock table with search + source/side/state
filters, live signal journal — all 4 tabs verified in-browser), and **demo/beta mode** (`RADAR_DEMO`
auto-starts the simulated scanner — no credentials). Rendering is **Jinja2 SSR** (not Next.js).
95 automated tests pass; UI + flows verified end-to-end via browser screenshots.

Phase 2 is **feature-complete for the beta**. Remaining (not blockers for a demo beta): audit view
in the UI (CLI only today), CSV export, Control-Center auth (needed only for a public multi-user
live deployment). Phase 3 = OCI deploy (kit ready in `deploy/oci/`) + multi-tenant live.

## Phase 3 — Cloud, multi-tenant (24/7 off the laptop)
- Hosted service; per-user broker keys + encrypted token vault; background daily token refresh.
- Per-user WebSocket sessions (respecting FYERS' 100-symbol per-account cap).
- Monitoring, auto-restart, broker-outage handling, audit storage per user.
- Compliance gate before any public launch: FYERS/NSE data terms, SEBI RA/IA review.

## Non-negotiables carried from CLAUDE.md
- Read-only / no auto order placement; always show the full ticket (symbol, side, qty, entry, SL,
  target, ₹ risk ≤ limit). India intraday flat by 3:20 PM IST. 1% hard risk ceiling.
