# Realtime Engine (Phase 1) — Status

Built overnight 2026-11-05. **All 62 offline tests pass.** Not yet exercised in a live
FYERS market session (that needs your interactive login + market hours — see caveat below).

## What changed
- **`radar/aggregator.py`** (new) — `LiveCandleBuilder`: aggregates FYERS SymbolUpdate
  ticks into completed 5-minute candles (exchange-grid aligned, cumulative-volume deltas,
  never emits a partial bar, thread-safe). `flush_completed()` finalizes bars for thin
  symbols that get no new-bar tick.
- **`radar/engine.py`** — confirmation refactored into one shared gate `_confirm_test()`
  used by both the live and reconciliation paths (authoritative behavior unchanged).
  New: `ingest_live_bar()` (provisional path), `_reconcile()` (validate/retract),
  `_retract()`, `RETRACTED` state, and `provisional` flags on signals/state.
- **`radar/service.py`** — live loop now feeds ticks to the aggregator; completed live
  bars confirm as **PROVISIONAL** ~1s after close. REST history reconciles each one.
  A `flush-loop` thread finalizes thin-symbol bars.
- **`radar/dashboard.py`** — shows a **LIVE·PROV** badge on provisional signals, styles
  the new RETRACTED state, and explains both in the execution-gate notice.
- **Tests** — `tests/test_aggregator.py` (9) + `tests/test_realtime.py` (7): provisional
  confirm fires, authoritative validate, authoritative retract, OR never anchored from a
  provisional bar, no provisional-over-authoritative overwrite, provisional retest, and a
  full tick→aggregator→engine→signal integration.

## How to read it live tomorrow
- Signals now appear ~1s after a 5-minute bar closes (realtime), tagged **LIVE·PROV**.
- Seconds later the authoritative FYERS candle either drops the badge (validated) or flips
  the row to **RETRACTED** (false positive — stand down).
- **Real-money rule:** a LIVE·PROV signal is an early warning, not a confirmed entry.
  For real capital, wait for the badge to clear (validated), or accept provisional risk
  knowingly. The opening range is still always authoritative (never provisional).

## The one thing NOT verified (by nature)
The live FYERS WebSocket → aggregator → engine chain was tested offline with simulated
ticks that exercise the exact same code path, but a real market session has not run here
(no live token / outside market hours). First live session is the real test — watch the
`or_anchor_delays` and `signals` CSVs and compare a couple of LIVE·PROV → validated signals
against TradingView timing.

## Known follow-ups
- Volume on the FIRST live bar of a symbol is an undercount until REST seeds the baseline
  (fails closed — fewer confirmations, not more). `seed_prev_cumulative()` exists to fix
  this from the last REST candle; wiring that seed in is a small next step.
- Provisional retest reconciliation re-runs on the authoritative bar; edge cases around a
  provisional retest whose underlying confirm later retracts are handled by RETRACTED
  superseding the setup, but deserve a live-session look.
