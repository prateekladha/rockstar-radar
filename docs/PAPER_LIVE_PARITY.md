# Paper → Live Parity Spec

> **Goal:** paper auto-trading must be a faithful replica of what a real INTRADAY order through
> FYERS would do, so a green paper month is evidence of edge — not an artifact of optimistic
> simulation. Nothing here is "made up": every number is sourced from a broker API or FYERS's
> published rate card, and every rate is config-tunable so it can be trued-up against a real
> contract note.
>
> Last updated: **2026-11-23**

---

## 1. Why this exists (the 2026-11-23 trigger)

A single paper session showed an "unbelievable" profit. Audit of the engine found the P&L was
*real engine output* (deterministic Python, no human/model picking trades) but **systematically
optimistic** for concrete reasons. Before leaning on paper to justify real money, we close each gap.

### Findings (what inflates paper P&L today)

| # | Gap | Evidence in code | Effect |
|---|-----|------------------|--------|
| G1 | **No account-level margin cap.** Each trade is sized against `max_risk` in isolation; nothing checks the *sum* of open notional against buying power. | `order_engine.py` `_auto_trade` / `_auto_trade_smc` — `qty = floor(max_risk/|entry-stop|)`, no exposure check. | Book can deploy many× the real account; absolute ₹ P&L inflated. |
| G2 | **Risk-normalised sizing + let-winners-run concentrates P&L in a few tight-stop names.** qty ∝ 1/stop-distance, so tight stops get huge qty; downside capped ~1R, upside uncapped. | `radar/risk.py::position_size`. | A couple of tight-stop runners dominate the day — the "few winners, huge qty" pattern. Real-world those tight stops slip most. |
| G3 | **Perfect fills.** Paper entry fills exactly at the signal level; stop/target exit exactly at the level. No slippage. | `order_engine.py::process_paper` (`fill_price = order.entry`), `_exit_hit`. | Overstates winners, understates stop-out cost (<1R where live would be >1R). |
| G4 | **No trading costs.** Brokerage, STT, exchange, SEBI, IPFT, stamp, GST are never deducted. | `mark_closed` books gross `(exit-fill)*qty`. | Small paper winners that are net losers live. The single biggest distortion for "actual profit." |
| G5 | **Manual exit doesn't stop re-entry.** After a user manually closes an auto position, the symbol frees up and a fresh signal can re-open it (only a *stop-out* blocks re-entry). | `trading.py::close_order` → `mark_closed`; `_auto_trade` re-entry guard = `smc_block_reentry_after_stop` only. | Bot fights the trader's override; extra trades the user didn't intend. |
| G6 | **SMC score is an unvalidated heuristic.** `score≥80` gates auto-SMC entries, but no mapping from score → realized R exists. Plus: OB loop breaks on the *first* scoring block not the strongest; a strong-but-far (>2%) key level still adds points; score computed at live price so it's noisy at the cutoff; div-by-zero risk if a zone collapses. | `smc_engine.py::calculate_smc_score` (L303). | Selection quality unproven; borderline entries partly timing luck. |

No double-exit bug: once `status='closed'` the engine skips the order on every pass (verified). G5 is
about *re-entry*, not double-exit.

---

## 2. Broker-sourced facts (verified 2026-11-23)

### 2.1 Margin Calculator API (real per-stock INTRADAY margin)
- `POST https://api-t1.fyers.in/api/v3/multiorder/margin`
- Headers: `Authorization: <APP_ID>:<ACCESS_TOKEN>`, `Content-Type: application/json`
- Body: `{"data":[{"symbol": <FYERS sym>, "qty": <int>, "side": 1|-1, "type": 2, "productType": "INTRADAY", "limitPrice": 0.0, "stopPrice": 0.0, "stopLoss": 0.0, "takeProfit": 0.0}]}`
- Response `data`: `margin_total` (margin the order needs), `margin_avail` (= available balance, same as Funds API), `margin_new_order`, `prevMargin`.
- **Fundable iff** `margin_total ≤ margin_avail`.
- Source: https://fyers.in/api-docs/v3/api/calculators/multi-order-margin-calculator/ (updated 2026-10-14).
- **Residual gap (honest):** the doc states the calculator *"does not check whether the instrument is
  eligible for the product type."* So it returns an INTRADAY margin even for a non-MIS-eligible stock
  and gives **no explicit eligibility flag**. True eligibility only surfaces as a live-order rejection,
  which paper cannot trigger. We approximate eligibility (see Phase 2); we do **not** claim it is a
  perfect replica.

### 2.2 Funds API (account buying power)
- Already wrapped: `server/broker_orders.py::fetch_funds` → broker "Available Balance" (₹).

### 2.3 Statutory + brokerage charges — INTRADAY EQUITY (NSE)
Sourced from FYERS's statutory-charges KB (updated 2026-04-01) + rate card. Config-tunable.

| Component | Rate | Applied to |
|-----------|------|-----------|
| Brokerage | min(₹20, 0.03%) per executed order | each leg's turnover |
| STT | 0.025% | **sell** leg only |
| Exchange txn (NSE) | 0.00297% | both legs |
| SEBI turnover | ₹10 / crore (0.0001%) | both legs |
| IPFT (NSE) | ₹10 / crore (0.0001%) | both legs |
| Stamp duty | 0.003% | **buy** leg only |
| GST | 18% | on (brokerage + exchange txn + IPFT) — **not** STT/stamp/SEBI |

Sources: https://support.fyers.in/portal/en/kb/articles/what-are-the-brokerage-statutory-and-other-applicable-charges-at-fyers ,
https://fyers.in/calculator/brokerage/ . Implemented in `server/charges.py`.

---

## 3. Build phases

### Phase 1 — the P&L-distorting cores ✅ DONE (PR #54)
1. ✅ **Charges model** (`server/charges.py`) — `mark_closed` now stores `gross_pnl`, `charges`, and a
   NET `pnl`; R stays measured on the gross edge. Paper only (live books real charges). *(G4)*
2. ✅ **Real margin gate** (`order_engine._parity_ctx` / `_gate_entry`, `broker_orders.fetch_order_margin`)
   — each auto-entry calls FYERS `multiorder/margin`; a running `committed` pool (sum of open paper
   positions' `margin_used`) is checked against live `margin_avail`; over-budget entries are skipped.
   **Can't read the broker → skip all that user's auto entries** (user's choice). Sim bypasses it. *(G1)*
3. ✅ **Slippage** (`_apply_slippage`) — adverse on entries, stop exits, velocity/reversal/square-off
   market exits; favourable limit targets fill clean. `paper_slippage_bps` (default 5). *(G3)*
4. ✅ **Manual-exit re-entry guard** — manual close tags `exit_reason='manual'`; both auto strategies
   skip a symbol manually exited today. `block_reentry_after_manual_exit` (default on). *(G5)*
5. ✅ **SMC score fixes** — strongest-OB (not first), zero-width-zone guard, far (>2%) key levels
   down-weighted; `smc_engine.score_bucket_report()` buckets realised R by entry score to validate or
   kill the 80 gate with our own trades. *(G6)*

### Phase 2 — remaining realism (status)
- ✅ **MIS eligibility — leverage proxy. ON by default (`intraday_leverage_floor` = 1.5).** An order
  whose broker implied leverage (notional / real margin) is below 1.5 is skipped as "no real intraday
  benefit." FYERS intraday leverage is bimodal — eligible names get ~5x, non-MIS names ~1x — so a 1.5
  floor cleanly drops the non-MIS (~1x) names while never tripping a genuine MIS name. **Honest
  residual:** this is a proxy, not FYERS's eligibility flag (which the API doesn't expose); a true
  list needs a live reject. Set 1.0 to disable.
- ✅ **Liquidity sanity. ON by default (`fill_max_pct_daily_turnover` = 2.0%).** Skip a position whose
  notional exceeds 2% of the stock's median daily turnover — at the min-liquidity universe (₹15cr/day)
  that's a ₹30L position, far above any risk-sized entry, so it only trips genuinely oversized
  (tight-stop, huge-qty) positions. Uses daily turnover (per-bar depth isn't in the feed) — a coarse
  guard, not an order-book fill model. Set 0 to disable.
- ⬜ **Deferred (no data in the current feed):** per-bar depth/partial-fill microstructure, circuit
  (UC/LC) limits, freeze-qty caps, and per-leg charges for partial books (Phase 1 charges the full
  round-trip at blended fills). Documented here so they're not silently assumed solved.

### Config keys (all tunable, in `radar/control.py::EDITABLE_CONFIG`, defaults in `config.json`)
`paper_apply_charges` (bool), `paper_slippage_bps` (num), `paper_margin_gate` (bool),
`intraday_leverage_floor` (num), `block_reentry_after_manual_exit` (bool),
`fill_max_pct_daily_turnover` (num), and the `cost_*` charge rates (§2.3).

### DB columns added (`orders`, additive migration in `server/db.py`)
`gross_pnl`, `charges`, `margin_used`, `exit_reason`.

---

## 4. Non-goals / honesty notes
- Paper can never be a *100%* replica of MIS **eligibility** without placing a real order (§2.1).
- Charges/rates are trued-up against a real contract note once live; defaults are from FYERS's
  published card, not a contract note.
- A good paper month under this model is *evidence*, not proof. Validate the SMC threshold against
  logged R before sizing up.
