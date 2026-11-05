# Rockstar Radar V1.2.1: FYERS temporary-ban safety patch

This patch is for an existing Rockstar Radar V1.2 installation (including V1.1 that has been upgraded using the V1.2 morning-watchlist patch).

## IMPORTANT: A patch cannot unblock a FYERS/Cloudflare ban

If FYERS says `The owner of this website ... has banned you temporarily`, **stop all API requests**. Do not retry `login`, `doctor`, `prepare`, `run`, or use another IP to get around the restriction. Contact FYERS privately and wait for confirmation of restored access. Never share your access token, API secret or redirect authorization code.

## Safe upgrade, no API requests needed

1. Stop Radar with Ctrl+C. Back up the complete existing project folder.
2. Download the small `Rockstar_Radar_FYERS_V1_2_1_Rate_Safety_Patch.zip` and unzip it *into your existing project folder*.
3. In Terminal, change to that project directory, activate the existing `.venv`, then run **offline tests only**:

```bash
source .venv/bin/activate
python -m unittest discover -s tests -q
```

This patch replaces only `launch.py`, `radar/fyers.py`, `radar/selecting.py`, `radar/service.py`, `radar/engine.py`, and tests. It does NOT overwrite `.env`, `config.json`, `data/morning_rockstars.txt`, existing caches or `output/` logs. `README_RATE_SAFETY_HOTFIX.md` is added.

## What changes

- REST calls are safety-limited to at most **24 per minute**, with **2.5 seconds** between calls regardless of an older `history_request_interval_seconds` in `config.json`. This is deliberately below FYERS Standard's published 50 requests/minute ceiling and is not a guarantee against provider-side restrictions.
- The app refuses simultaneous API jobs **from the same project folder** using a macOS/Linux process lock. It does not control other apps or other folders using your FYERS token.
- On a recognizable block/1015 or rate-limit response, history/selection preparation **stops immediately**, rather than retrying all remaining symbols.
- When the SDK returns ambiguous `-99`, a failed GET and POST quote batch stops without recursively splitting into dozens of requests. Explicit input/symbol errors can still be isolated conservatively.
- When a fatal FYERS access failure occurs during live reconciliation, live scanning is halted and the dashboard no longer displays actionable top-five signals. Existing historical logs are retained.
- Cache progress is written before stopping. Empty daily-history cache entries from earlier failed runs will be retried **only after access is restored**.

## Once FYERS confirms the restriction is lifted

Open only one Radar instance. Authenticate once with your normal local application and run:

```bash
python launch.py login
python launch.py run
```

It may take significant time to prepare 100 volume baselines at the conservative REST rate. **This patch improves API safety but does not validate real-time ORB alert timeliness.** The existing 100-stock historical-candle confirmation process can lag by several minutes; do not use it for real-money entry decisions until time-to-signal has been measured and improved.

## When contacting FYERS

Provide the API hostname `api-t1.fyers.in`, the exact error text, date/time in IST, and any Cloudflare Ray ID shown. Share account/client details only through FYERS private support. Ask whether the problem is rate limiting / Cloudflare Error 1015, whether the block is account- or IP-scoped, and when API access will be restored.
