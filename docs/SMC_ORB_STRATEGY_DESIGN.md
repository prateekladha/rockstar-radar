# SMC + ORB Strategy Redesign — Confluence & Adaptive Exits

Last updated: **2026-11-21**
Status: **Design / requirements captured — not yet implemented**

> This document captures (1) the trader's actual manual process we are encoding, (2) an honest map
> of what the engine computes today vs. what is missing, (3) the phased build plan, and (4) the open
> design decisions. It exists so this design lives in the repo, not in chat history. Update it in the
> same change whenever a decision or result changes.

---

## 1. Purpose & context

One week of live manual trading produced a clear, profitable playbook (₹28K over the week; ₹8K and
₹13K on the final two days). The goal is to encode that playbook faithfully so the scanner finds the
same setups and manages exits the way the trader does — and, over time, tunes itself on **real logged
outcomes** rather than static thresholds.

Two pillars the trader called out as the foundation of success:

1. **Right stock at the right time.**
2. **Right entry / exit / stop — not a static formula**, but a decision that weighs current confluence
   and market state and adapts.

The pain points that motivated this:

- **ORB:** the signal logic (RETEST_READY / CONFIRMED) is sound, but it is locked to a **static
  wall-clock window**, so genuine opportunities get missed. Exits and stops are weak.
- **SMC:** the engine under-uses SMC vs. how the trader reads it manually; and like ORB, exits/stops
  are primitive (a recent auto paper trade bled because the stop/target never adapted).

---

## 2. The trader's manual process (the human baseline)

This is the behavior we are encoding. Treat it as the spec.

### 2.1 Stock selection — two streams
- **Pre-market (fundamental):** a shortlist chosen before the open from **results and news** expected
  that day (earnings, announcements, catalysts).
- **Intraday (technical):** the rest discovered continuously through the ORB and SMC scanners.

### 2.2 Timeframes — multi-timeframe
- **5-minute** for structure (zones, order blocks, swings, structure breaks).
- **1-minute** for the actual **entry trigger**.
- (Our engine today runs a **single** resolution — see §3. This is the biggest architectural gap.)

### 2.3 The confluence stack (how the trade is judged)
The trader does not act on any single signal — a trade requires **agreement across layers** at a
specific price and time.

**Layer 1 — SMC structure (direction & "why"):**
- Premium / Discount / Equilibrium — **anchored to the current swing leg** (see §2.4).
- Buy / Sell **order blocks** — the reaction zone / entry area.
- **FVG** — imbalance as entry refinement or target.
- **BOS vs CHoCH** — continuation vs first-sign-of-reversal; the structural trigger.
- **Strong vs Weak** highs/lows — which liquidity holds vs gets swept.
- PDH / PWH / PDL / PWL — used only as **soft** context, **not** primary (explicitly de-prioritised).

**Layer 2 — location & conviction filters:**
- **Pivots Fibonacci (Auto)** — S3–S1, P, R1–R3 — independent S/R; confluence when a pivot lines up
  with an order block / FVG.
- **Relative Volume 1D 10 Cumulative** — today's *cumulative* volume vs the average cumulative at the
  *same time of day* over the last 10 sessions; >1 = real participation/fuel.
- **RSI 14 (close)** — momentum / exhaustion / divergence.

**Layer 3 — Fixed-Range Volume Profile (price acceptance / trend context):**
- **VAH / VAL / POC** — value-area bounds (~70% of volume) and point of control; act as S/R + magnet.
- **Profile shape P / b / B / D** — **trend context, not a standalone direction.** The trader reads a
  **b-shape as ambiguous** (bearish continuation *or* accumulation/reversal) and uses the other layers
  (RSI, RVOL, order block, structure) to decide which. So shape is a **conditioning input** to the
  score, never a lone trigger.

### 2.4 Premium/Discount anchor — "swing leg" (from LuxAlgo SMC)
The trader reads zones off the **LuxAlgo Smart Money Concepts** indicator. LuxAlgo anchors
premium/discount to the **most recent swing leg**: last swing high → last swing low, with the top half
= premium, bottom half = discount, 50% midpoint = equilibrium. A **swing leg** is simply the move from
one swing point to the next (swing low → swing high = one bullish leg).

> Source: LuxAlgo SMC premium/discount zones — https://docs.luxalgo.com/docs/algos/price-action-concepts/pdzones

### 2.5 Entry logic
Primary decision = **order block + FVG + current position of price relative to zone
(premium/discount) + strong/weak context**, refined on the **1m** chart. Fib pivots add support/target
confluence; volume-profile shape adds trend context. (PDH/PDL etc. are soft, not required.)

### 2.6 Stop placement
At **structure** — beyond the order block / at the nearest fib-pivot support (long) or resistance
(short). **Not** a blind ATR distance. (ATR only as a last-resort fallback when no structure is near.)

### 2.7 Exit discipline — the adaptive part
- **Target at the nearest realistic structural level**, not always the far target.
- **Time-decay on the target is VELOCITY-based** (not a fixed clock): if the target is too far for how
  fast price is moving in the time remaining, step the target **in** to the nearest structural level
  in profit and take it.
  - See the full worked session in §2.8 (APL Apollo Tubes — 4 trades, >₹10K in one day).
- **Partial booking:** **book half at the first structural level, run the rest** toward the next level
  — by judgement, governed by the velocity-decay logic above. Move stop to **breakeven** once half is
  booked.

### 2.8 Worked session — APL Apollo Tubes (4 trades, >₹10K, one day)
A balanced/range-bound day. The trader **scalped the oscillation** between ~₹2089 support and
~₹2097–2100 resistance, **flipping direction**, using intraday MIS leverage (2×–5×) and **scaling in**
with paired limit orders.

- **T1 (morning):** Buy avg **₹2046** (200 sh = 100+100 scaled). Entry: price at a **buy order block**.
  Exit **₹2057** (+10–12/sh) at an **FVG + POC confluence** → took the safe nearer exit, didn't hold.
- **T2 (~11:30):** Stock up, following **BOS**. Spotted a last up-leg near **fib-pivot support ₹2090**.
  **Watched for a break confirmation**; on confirmation (price reaching ₹2092) entered: buy ₹2090 +
  ₹2084 (avg **₹2087**). SMC showed a **large FVG** (large because price sat **below PDL**) and
  **equilibrium at ₹2110** → aspirational target 2110. But price **rejected ₹2097 repeatedly** →
  exited **₹2097** (+10/sh) instead of waiting for 2110.
- **T3 (immediately):** **Short** 400 sh at **₹2097** (confidence from the repeated rejection). Exit
  **₹2089** (+8/sh).
- **T4:** **Buy** 450 sh at **₹2089**; wanted to run it. Reversal forming at ₹2100; choice = wait 2110
  or take 2100. **Time (14:15) + velocity** → took **₹2100**.

**Rules this validates / adds:**
1. **Nearest respected level beats the far target.** Exit at the nearest confluence/structural level in
   profit (FVG+POC, a repeatedly-rejecting price, a pivot) rather than holding for equilibrium/PDL.
2. **Repeated rejection = exit, and a reversal entry.** A level that rejects price **≈3× without
   breaking** becomes the realistic exit — and can flip into an **opposite-direction entry**
   (T2 exit 2097 → T3 short 2097).
3. **Range/oscillation scalping, both directions.** On a balanced day, trade the swing between support
   and resistance and flip long/short — not only one-directional SMC entries.
4. **Confirmation-gated entry at a level.** Don't blind-limit at the level; wait for the break/hold to
   confirm, then **scale in with two orders** to average.
5. **Velocity + time governs the runner** (T4): afternoon + slow pace → take the nearer level.

> **Design implication — re-entry model.** T2–T4 are multiple, re-entrant, both-direction trades on
> one symbol in a day. The current `_entered_today` guard (one entry per symbol/day, shared across
> sources) would have **blocked T2, T3 and T4**. The redesign must allow **multiple, re-entrant,
> long-and-short trades per symbol**, bounded by a per-symbol daily trade cap + the account risk limit
> (see §6).

---

## 3. Current engine — what exists vs what's missing

Inventory of the live code (file:line references for implementation).

| Signal / capability | Status | Where / note |
|---|---|---|
| Premium / Discount / Equilibrium | ✅ computed, **wrong anchor** | `calculate_zones` smc_engine.py:165, `get_current_zone` :196. Anchored to a rolling ~150-bar (`max_candles`, :828) trailing high/low that **never resets per session** — not the swing leg. |
| Swing highs/lows + strong/weak | ✅ | `detect_pivot` smc_engine.py:69 (size=50 swing, size=5 internal); strong/weak set :884/:906; `SMCPivot.is_strong` models.py:119. |
| Order blocks (strength + mitigation) | ✅ | `detect_order_block_enhanced` smc_detection.py:16; mitigation `update_order_block_mitigation` :190. |
| FVG (detect + fill tracking) | ✅ | `detect_fair_value_gaps` smc_detection.py:125; fill `update_fvg_fill_status` :232. |
| BOS / CHoCH | ⚠️ **crude** | smc_engine.py:933–962 — single-bar close-through-swing test, **not** a true HH/HL/LH/LL structural engine (code comment admits "simplified"). |
| PDH/PDL/PWH/PWL (daily/weekly levels) | ❌ (soft anyway) | No daily/weekly series intraday. ORB has prior-20-day high/low sets (`compute_daily_profile` selecting.py:107) but SMC can't see them. |
| Pivots Fibonacci (S3–R3, P) | ❌ | Absent. |
| RVOL 1D 10 Cumulative | ⚠️ partial | ORB has **non-cumulative** same-slot RVOL (`_rvol` engine.py:197, `same_time_baseline` :24). No cumulative variant; none on SMC side. |
| RSI 14 | ❌ | Absent. |
| Fixed-Range Volume Profile (VAH/VAL/POC + shape) | ❌ | No volume-at-price anywhere. Largest build. |
| VWAP | ⚠️ proxy | `_candle_vwap` engine.py:203 (OHLC-typical approximation), ORB side only. |
| ATR | ✅ | intraday `calculate_atr` smc_engine.py:25; daily ATR% `Instrument.daily_atr_pct` selecting.py:117. |
| SMC score | ✅ | `calculate_smc_score` smc_engine.py:268 (zone/key-level/OB/FVG/structure/recency, capped 100; <35 dropped at :1027). |
| Multi-timeframe (5m + 1m) | ❌ | Engine runs ONE resolution (`signal_bar_minutes` utils.py:50; 5m default). No 1m entry layer. |
| Exits — trailing / breakeven / partial / time-based | ❌ | `process_paper` order_engine.py:66 — stop/target **static once set**; only extra exits are ORB opposite-signal reversal (:196) and 15:15 square-off (`_square_off_paper` :308). |
| ORB signal window | ⚠️ static | Locked to 09:15 OR + 09:20→15:00 wall-clock gate (engine.py:145/419, config.json `watch_start`/`new_signals_stop`). The "static window" problem. |
| Libraries | — | No pandas/numpy/ta; all indicators hand-rolled on stdlib `statistics`. |
| Fundamentals | ❌ | None on `Instrument` (models.py:31). Pre-market news/results shortlist is currently manual. |

**Bottom line:** the SMC *primitives* exist (zones, OBs, FVG, swings) but (a) zones are anchored to the
wrong range, (b) the confluence layers the trader actually uses (fib pivots, cumulative RVOL, RSI,
volume profile) are missing, (c) BOS/CHoCH is too crude to be a trigger, (d) there is no 1m entry
layer, and (e) exits are static. ORB is locked to a fixed time window.

---

## 4. Design principles (the honest stance on "self-learning")

The ambition is an agent that adapts to market conditions. The disciplined way to get there:

1. **You can't learn a judgement you can't measure.** Every missing layer (fib pivots, cumulative
   RVOL, RSI, volume profile, real BOS/CHoCH) is an *input* the trader's brain weighs. Until the engine
   computes them, there is nothing to learn from. **Feature parity with the trader's eyes comes first.**
2. **No per-second retraining.** A model that "retrains every tick" on a few dozen trades curve-fits
   noise and fails on the next regime. Not acceptable with real money downstream.
3. **"Adaptive" = context-conditioned rules + outcome-driven re-weighting.**
   - Behaves differently by **regime** (trending P-shape day vs balanced D-shape day; high vs low RVOL).
   - **Logs every trade's full feature-set + outcome**, then **periodically** (daily/weekly) re-tunes
     the confluence weights on *accumulated real results*. Auditable; compounds as the sample grows.
4. **Exits deliver "no loss / low loss" with zero ML** — structure stops, breakeven-at-1R, partials,
   and the velocity-based time-decay target. Ship these first; they move P&L the most.
5. **Transparency over black-box.** The confluence score stays inspectable (which layers fired, what
   weight) so the trader can trust and correct it.

---

## 5. Phased build plan

### Phase 0 — ship now (no ML; hits the pain directly)
- **Re-anchor premium/discount to the swing leg** (latest strong swing high ↔ swing low), matching
  LuxAlgo. Reuses existing swing detection. Makes engine zones agree with the trader's chart.
- **Exit engine:**
  - Structure stop (beyond OB / nearest fib pivot), ATR only as fallback.
  - **Breakeven at ~1R.**
  - **Partial booking:** book half at the first structural level, run the rest.
  - **Velocity-based time-decay target:** estimate required pace to reach the target in the time left
    vs. recent realised pace; if unreachable, step the runner's target in to the nearest structural
    level and take it. (Encodes the APL Apollo behaviour.)
- **RSI-14** and **Fibonacci pivots (S3–R3, P)** — both small, pure math.

### Phase 1 — "see what you see" (feature parity)
- **Fixed-range / session Volume Profile**: VAH / VAL / POC + **P/b/B/D shape classifier** (as a
  conditioning input, not a lone signal).
- **Cumulative RVOL-at-time** on the SMC side (adapt the ORB baseline to cumulative).
- **Real BOS / CHoCH** structural engine (HH/HL/LH/LL), replacing the single-bar test.
- **1-minute entry layer** on top of 5m structure (multi-timeframe architecture).
- **ORB dynamic signal window** — replace the hard 09:20–15:00 gate with a volatility/volume-adaptive
  window so genuine retest/confirmed setups aren't missed.

### Phase 2 — the adaptive layer (the honest "learning")
- **Transparent weighted confluence score** across all layers (supersedes/augments
  `calculate_smc_score`).
- **Per-trade feature + outcome logging** → periodic re-weighting on real results.
- **Regime / shape conditioning** (behaviour differs by volume-profile shape & RVOL regime).
- Reached **only after** Phase 1 features exist to learn from.

---

## 6. Key decisions — locked & open

**Locked (from the trader):**
- b-shape is **ambiguous** → conditioning input, resolved by other layers. Never a lone trigger.
- Time-decay exit is **velocity-based**, not clock-based.
- Partials: **book half, run the rest**, stop to breakeven after.
- Timeframes: **5m structure, 1m entry.**
- PDH/PDL/PWH/PWL are **soft**, not primary.
- Zones anchored to the **swing leg** (LuxAlgo-style).
- **No drop-in LuxAlgo** — reimplement the methodology in Python (see §7).

**Recommended defaults (open for the trader's confirmation; all are config knobs):**
- **Active-leg swing lookback (zone anchor):** anchor premium/discount to the **internal swing**
  (pivot size **10** on 5m, **reset each session**), not the slow size-50 structural swing — so zones
  track the session like LuxAlgo's *internal structure*. Knob `smc_zone_swing_size` (default 10).
- **Volume-profile range:** **developing session profile** (09:15 → now, rebuilt each session) for
  VAH/VAL/POC + P/b/B/D shape. (Swing-anchored range deferred.)
- **Velocity governor:** trailing velocity window **15 min**; horizon = **15:15** square-off; step the
  runner's target to the nearest level when required pace > **1.5×** recent realised favourable pace.
  **Plus a hard repeated-rejection exit** at **≥3 touches** of a nearer level without a break.
- **First-level priority for the half-book (nearest-in-profit within the first tier that exists):**
  (1) a **confluence cluster** (≥2 of FVG / POC / VAH-VAL / fib-pivot within ~0.15%), else
  (2) **POC / VAH / VAL**, (3) **fib pivot**, (4) **unfilled FVG edge**, (5) **opposite swing / OB edge**.
- **ORB dynamic window:** open when the opening range completes **and** RVOL-at-time ≥ **1.2** with a
  clean first structure break; allow **new entries until 14:45** (volatility-scaled, not a hard 15:00);
  management/exits until 15:15. Replaces the fixed 09:20–15:00 gate.
- **Re-entry model (per §2.8):** allow **both-direction, re-entrant** trades per symbol —
  **max 1 concurrent** position per symbol, **daily trade cap 4** per symbol (`max_trades_per_symbol`),
  all under the account risk limit. Replaces the one-entry-per-symbol/day guard.
- **Pre-market shortlist:** keep **manual** — the trader tags news/results names pre-open; the engine
  **ranks tagged symbols higher**. Automated news/results feed deferred to Phase 2+.

---

## 7. On LuxAlgo SMC

LuxAlgo SMC is a **TradingView Pine Script indicator** — it runs only inside a TradingView chart and
exposes no API/library/data feed, so it **cannot be plugged into** our Python backend. The plan is to
**reimplement its methodology** (premium/discount off the swing leg, order blocks, FVG, BOS/CHoCH,
strong/weak) in Python so the engine reproduces what the trader sees on the chart. The concepts are
public (ICT-derived) and partly open-source Pine we can study; we port the **behaviour**, not copy the
code verbatim, to stay clear of their licence.

---

## 8. Status / next step

Requirements captured. **No code written yet.** Recommended start: **Phase 0** (swing-leg re-anchor +
exit engine + RSI + fib pivots) since it is low-risk, needs no ML, and most directly addresses the
weak-exits pain. All changes remain **paper-only**; live orders always require tap-to-confirm.
