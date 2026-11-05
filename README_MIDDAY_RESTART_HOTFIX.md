# Rockstar Live Radar V1.2.2 — Midday restart and review patch

**For an existing V1.2.1 installation with the Rate Safety Patch.** Does not replace `.env`, `config.json`, `data/`, `output/`, your 100-stock selection, or your morning pins. No code places trades.

## Why the previous dashboard looked empty after sleep

The built-in `new_signals_stop` is **11:30 IST**. The V1.2.1 history reconciliation thread exits by **11:55 IST**. Restarting at ~14:00 created a fresh engine with no restored opening-range state, and the Top 5 only displays live eligible candidates. A blank Top 5 does **not** mean there are no stocks in the selection; check All Stocks and the feed-health line.

## Install safely

1. Stop Radar using Ctrl+C. Back up your entire project folder first.
2. Unzip `Rockstar_Radar_FYERS_V1_2_2_Midday_Restart_Patch.zip` into your existing V1.2.1 project directory. It overwrites `launch.py`, `radar/service.py`, `radar/engine.py`, `radar/dashboard.py`, and adds `tests/test_midday_restart.py` and this README. Do not unzip into a different folder level.
3. In that directory run these **offline** checks:

```bash
source .venv/bin/activate
python -m unittest discover -s tests -q
```

Expected: 52 offline tests passed (if your V1.2.1 installation has all previous tests). No API calls are made during tests.

## Run at different times

- **Before the configured cutoff** (default 11:30): `python launch.py run`. The scanner restores today's saved candles and the event journal, resubscribes to FYERS (if access is permitted), and waits for **fresh** completed 5-minute candles before showing new actionable states. Previously confirmed symbols are marked `SESSION_CONSUMED` to prevent repeat trade alerts. Past signals remain available for review only.
- **After the cutoff plus 20-minute retest allowance** (default 11:50): `python launch.py run` opens a **REVIEW-ONLY** dashboard with an explicit `SESSION CLOSED` banner and today's saved events. It will **not send FYERS requests** or display an actionable Top 5. The default scanner does **not** trade in the afternoon.
- **If you deliberately want an afternoon paper-only test**, back up then edit `config.json` from `"new_signals_stop": "11:30"` to `"new_signals_stop": "15:00"` **before** running `python launch.py run`. The application can attempt to rehydrate today's 9:15 OR levels and obtain fresh FYERS data. It may require time and REST calls; the patch has not been verified against your live FYERS feed. This is an experimental window extension, not an instruction to trade afternoon breakouts. Consider reverting to 11:30 for normal validation.

## Important constraints

- If the earlier session did not save any completed candles to `output/fy_history_candles_YYYY-MM-DD.csv`, there is no local opening-range history to display after cutoff. The dashboard explicitly shows `SESSION CLOSED` rather than inventing prices. For a recovery *before* cutoff, FYERS history can fetch missing opening-range candles, subject to API availability and rate limits.
- No stale signal can become a new active candidate until live ticks and recent authoritative completed 5-minute candles are available. Previously confirmed symbols are not re-alerted after restarting.
- If FYERS still shows a temporary security ban, **do not** resume any live API requests or attempt to bypass it. The `REVIEW ONLY` mode is fully local if today's selection exists.
- This hotfix passed offline simulation/tests only. No real-market timing, FYERS reconnect, or alert accuracy has been verified. Paper-test before relying on results.
