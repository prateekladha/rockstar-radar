# ⚡ Rockstar Radar

**Your intraday co-pilot for the Indian (NSE) markets.** A real-time opening-range breakout (ORB)
radar: connect your own broker, get ranked intraday setups with entry / stop-loss / targets, a smart
daily watchlist, and a full trade journal. You review and confirm every trade — nothing fires on its
own, and paper-trading is the default.

> **Not investment advice.** Short-term trading is risky. This is a personal tooling project; every
> rule in it exists to *limit* damage, not to guarantee gains. Backtest and paper-trade first.

---

## What it does

- **Opening-range radar** — scans the day's liquid NSE stocks live, builds each one's opening range,
  and ranks breakout setups by strength with entry, stop and targets.
- **Smart watchlist** — an auto-generated daily long/short shortlist with levels and invalidation.
- **Trade journal & insights** — persists every opportunity the radar flagged and every trade you
  took; win rate, expectancy (in R), equity curve.
- **Bring your own broker** — connect your own FYERS account today (Zerodha, Upstox, Angel One, Dhan,
  Groww, Paytm Money, 5paisa planned). Your login, your data; secrets are encrypted at rest.
- **Multi-tenant** — Google sign-in, households (family/team) with Admin/Trader roles.

## Architecture

| Layer | Tech |
|---|---|
| API | FastAPI (`server/`) — auth, per-user DB, serves the SPA, market-open scheduler |
| Frontend | React 18 + Vite + React Router (`web/`), built to `web/dist` |
| Database | SQLAlchemy — **SQLite** for local dev, **PostgreSQL** for production (via `DATABASE_URL`) |
| Market data | FYERS API v3 (`radar/`) — REST history/quotes + WebSocket; per-household scanner subprocess |
| Secrets | Fernet-encrypted broker tokens/secrets at rest (`server/crypto.py`) |
| Deploy | Docker + Caddy (auto-HTTPS) on a single VM — see [`deploy/oci/`](deploy/oci/) |

> **Regulatory note:** SEBI requires a fresh broker login **every trading day** for all Indian
> brokers — programmatic token refresh is disabled. Rockstar Radar makes this a one-tap daily login.

---

## Local development

Requires **Python 3.11** (the FYERS SDK doesn't support 3.13+) and **Node 18+**.

```bash
# 1. Clone
git clone https://github.com/prateekladha/rockstar-radar.git
cd rockstar-radar

# 2. Python env
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 3. Build the SPA (served by the API from web/dist)
cd web && npm install && npm run build && cd ..

# 4. Run — SQLite is the default DB; DEV_LOGIN gives a one-click test user (no Google needed)
DEV_LOGIN=1 SESSION_SECRET=dev-secret .venv/bin/python -m uvicorn server.main:app --port 8080
```

Open **http://127.0.0.1:8080** and click **"Continue as test user (dev)"**.

**Frontend hot-reload** (optional, in a second terminal): `cd web && npm run dev` — proxies
`/api` and `/auth` to port 8080.

### Environment variables

| Var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///data/radar.db` | DB connection. Use `postgresql+psycopg://…` in prod |
| `SESSION_SECRET` | `dev-insecure-change-me` | Signs session cookies — **set a strong value** |
| `ENCRYPTION_KEY` | auto-file `data/.enc_key` | Fernet key for encrypting broker secrets at rest |
| `DEV_LOGIN` | off | `1` enables the local test-user button |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | — | Google OAuth (prod sign-in) |
| `PUBLIC_BASE_URL` | request-derived | Public https origin (for the broker OAuth callback) |
| `RADAR_SCHED` | `1` | Market-open scheduler (`0` to disable) |
| `RADAR_DEMO` | off | `1` serves a simulated feed (public marketing demo only) |
| `VITE_POSTHOG_KEY` | — | PostHog analytics key (build-time; blank = analytics off) |

### Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

---

## Production

A single-VM Docker stack (Postgres + API + Caddy auto-HTTPS) is in [`deploy/oci/`](deploy/oci/) —
tuned for an Oracle Cloud Always-Free VM. Secrets live in a git-ignored `.env` on the VM (never in
the image); broker tokens are additionally Fernet-encrypted in the database.

## Security

- `.env` and `data/` are git-ignored — **never commit** API keys, tokens, or the encryption key.
- The scanner is **read-only**: it never places real orders. Orders are **paper** by default and
  always require your confirmation.
- Broker secrets and access tokens are encrypted at rest.
