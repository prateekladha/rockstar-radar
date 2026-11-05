# Rockstar Radar — Platform Architecture & Product Blueprint

> Reframe: today's code is a **single-user localhost scanner**. Target is a **multi-tenant,
> multi-broker trading platform** (accounts, DB, RBAC/family, per-user broker connections,
> alerts, audit/insights, security, scale). This document is the system design that gets us
> there, addressing every requirement raised, with concrete tech choices and a phased plan.

Last updated: **2026-11-05**

---

## 0. The honest scope statement
A platform at TradingView/FYERS quality is a **multi-month, phased build**, not a single day.
For the **beta tomorrow**, the realistic move is to ship the **demo** (current UI, simulated data)
for UX feedback *while* we build the real platform underneath. Shipping half of 15 subsystems
would be worse than shipping a polished demo + a credible plan.

---

## 1. Target system architecture
```
 Browser (SPA + live WebSocket)            Telegram / Email / Web-push
        │  HTTPS (Caddy, auto-TLS)                 ▲
        ▼                                          │ (alert channels)
 ┌─────────────────────────────────────────────────────────────┐
 │ API / App tier  — FastAPI (async), session auth, RBAC guard  │
 │   • Auth & onboarding    • Settings/Watchlist svc            │
 │   • Broker-connection svc (encrypted creds)                  │
 │   • Alerts rules engine  • Audit/Insights svc               │
 └───────────────┬───────────────────────────┬─────────────────┘
                 │                             │
     ┌───────────▼─────────┐        ┌──────────▼───────────┐
     │ Database (Postgres) │        │ Scanner orchestrator │
     │  users, households, │        │  per-user workers;   │
     │  roles, settings,   │        │  market-data (WS) +  │
     │  broker_conns (enc), │        │  realtime engine;    │
     │  signals, trades,   │◄──────►│  writes signals/     │
     │  alerts, audit_log  │        │  events to DB        │
     └─────────────────────┘        └──────────┬───────────┘
                                                │ broker adapters
                               ┌────────────────┼─────────────────┐
                            FYERS data    FYERS orders      Zerodha Kite …
```

## 2. Decisions by requirement

### 2a. Auth & onboarding (NO OTP/SMS — zero cost)
- **Email + password** (Argon2id hashing) as the baseline — fully free, no SMS/WhatsApp.
- **Google Sign-In (OAuth)** as the easy path — free, no password handling. (Add later.)
- **Email verification / password reset via magic link** — free tier email (e.g. Resend/SES
  free tier) — email only, never SMS. Optional, not required to log in.
- **Sessions:** httpOnly, Secure, SameSite cookies (server-side session or signed JWT).
- **Onboarding wizard:** sign up → create/join a Household → connect a broker (guided) →
  pick watchlist → done. Clear progress, skippable steps, resumable.

### 2b. Database & persistence
- **Postgres** in prod, **SQLite** in dev — via **SQLAlchemy ORM + Alembic** migrations, so the
  switch is one env var. Runs on the single OCI VM now; managed Postgres when we scale.
- Everything currently in files (settings, watchlist, token, CSV audit) moves into the DB,
  scoped per user/household.

### 2c. Multi-tenancy, RBAC & the "family" model
- Entities: **Household** (tenant) → **Users** → **Memberships(role)**. Roles:
  `owner, admin, trader, viewer`. One household = one family/firm; members share or keep
  private watchlists/settings; billing at household level.
- **Row-level tenant scoping** on every query (household_id / user_id) + an RBAC guard that
  checks role→permission per action. A family sets up **once**; members just log in.

### 2d. Broker abstraction (data vs orders; FYERS + Kite + …)
- A `BrokerConnection` per (user, broker, capability): **market-data** app and **order-placement**
  app are *separate* connections (FYERS non-trading app for data, FYERS trading app for orders;
  Zerodha Kite likewise). Capability flags: `{data, orders}`.
- A `Broker` interface: `MarketData` (quotes, history, websocket) + `Orders` (place/modify/cancel,
  status) — brokers implement what they support. The engine depends on the interface, not FYERS.
- Order placement stays **opt-in and confirmed** (CLAUDE.md: never auto-fire without the ticket).

### 2e. Security
- Secrets (broker tokens/keys) **encrypted at rest** (AES-GCM/Fernet with a server KMS key);
  never logged, never sent to the browser. Per-tenant isolation enforced in the data layer.
- CSRF protection, rate limiting (per-IP + per-user), input validation (Pydantic), security
  headers (CSP, HSTS), dependency scanning, audit log of sensitive actions, least-privilege.
- HTTPS everywhere (Caddy). Session fixation/replay protections. Secrets via env/secret store.

### 2f. Runtime & performance under load
- **Per-user scanner workers** orchestrated by a scheduler/queue (the FYERS 100-symbol-per-account
  cap means data is per-user; we can't share one feed across users — licensing + limits).
  Workers run as async tasks / a worker pool; autoscale horizontally; back-pressure + circuit
  breakers (we already fail-closed on bans).
- Caching (quotes/history), DB indexing + pagination, async I/O throughout.
- **UI perf:** push updates over **WebSocket** (replace 3s polling), virtualized tables for 100+
  rows, code-splitting, skeleton loaders, debounced inputs.
- **Observability:** structured logs, metrics (Prometheus), tracing, error tracking (Sentry free
  tier), health/readiness probes, load tests (Locust/k6) before each scale milestone.

### 2g. Alerts (multi-channel, configurable)
- **Alert rules** per user: which states (RETEST_READY/CONFIRMED/RETRACTED…), which symbols/
  watchlist, quiet hours, channels. **Channels:** Telegram (free), email, web-push, in-app feed.
- Telegram for **alerts** now; **order placement via Telegram** (one-tap confirm → routes to the
  order broker) is a later, security-gated capability.

### 2h. Audit, insights, trade journal, debugging
- **Event-sourced**: persist every signal transition (WATCH→…→RETEST_READY→outcome), every user
  action, every order/trade + fills + P&L. This is the backbone of "learn from mistakes."
- **Insights dashboard:** win rate, avg R, expectancy, by setup/time-of-day/sector/side; discipline
  metrics (entered late? moved stop? traded outside plan?).
- **Trade debugger:** a per-signal timeline — tick → provisional → authoritative reconcile →
  retest → exit — with the exact data (RVOL, VWAP, extension, feed latency) behind each decision,
  so a user can see *why* a trade went wrong. TradingView deep-link + (later) embedded chart.
- **Audit-in-UI + CSV export** of signals/trades/journal.

### 2i. UI/UX (TradingView/FYERS-grade)
- A real **design system** + component library; **charts** via TradingView's free
  `lightweight-charts`; candlesticks with OR/entry/stop/target overlays.
- Live via WebSocket (not poll); optimistic updates; responsive + accessible (WCAG AA);
  dark/light; keyboard shortcuts. Reconsider **SPA (React/Svelte)** for the heavy live surface
  while keeping SSR for marketing/onboarding.

## 3. Phased roadmap (realistic)
- **Phase A — Foundation:** Postgres/SQLAlchemy, auth (email+password, no OTP), Household/User/RBAC,
  onboarding wizard; migrate settings/watchlist/token into the DB (per user). *Unblocks everything.*
- **Phase B — Broker connections:** encrypted per-user creds; data vs order apps; FYERS + Kite adapters.
- **Phase C — Scanner at scale:** per-user worker orchestration; WebSocket push to the browser.
- **Phase D — Alerts engine:** rules + channels (Telegram/email/web-push/in-app).
- **Phase E — Audit/Insights/Journal/Debugger:** event store + analytics + trade timeline + CSV.
- **Phase F — Hardening:** security review, load/perf, observability, RBAC/family polish, Control-Center auth.
- **Phase G — UI/UX elevation:** design system v2, charts, SPA for live surface.

## 4. What "today" can honestly deliver
Start **Phase A** (the foundation the whole product stands on). Everything else sequences off it.
Ship the **demo** for tomorrow's beta UX feedback in parallel.
