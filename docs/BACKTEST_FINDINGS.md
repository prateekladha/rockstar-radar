# Backtest Findings — SMC auto-trade + exit engine

Last updated: **2026-11-21**
Harness: `tools/backtest.py` · Data: prod SMC history cache `smc_history_2026-11-20_5m.json`

## Method
Replays the **real strategy** bar-by-bar over cached 5-minute candles: `SMCEngine`
(zones/OBs/FVG/structure) → score gate → `derive_smc_trade_plan` (score-driven, both directions) →
exits. Position sizing = ₹196,000 × 1% = **₹1,960 risk/trade**; entry gate = net R:R ≥ 2.0; re-entry
cap 4/day/symbol, 1 concurrent; square-off 15:15. Runs **adaptive** exits vs a **static** stop/target
baseline so the exit engine's impact is isolable.

**Data window:** 100 symbols, **Nov 16–19 2026** (4 trading days; ~101-bar warmup leaves ~2.5 days of
entries). **This is a tiny sample dominated by one trend day (Nov 19) — directional, not conclusive.**

## Results

### Score threshold × total P&L (adaptive vs static)
| min_score | trades (adaptive) | win% | **adaptive P&L** | static P&L |
|---|---|---|---|---|
| 70 | 290 | 70% | **−₹2,763** | **+₹51,947** |
| 80 | 79 | 72% | **−₹6,855** | −₹18,964 |
| 85 | 29 | 72% | −₹1,658 | −₹9,003 |
| 90 | 11 | 64% | −₹4,714 | −₹2,958 |

### Exit-component isolation (which layer helps / hurts)
| config | score 70 | score 80 |
|---|---|---|
| **Static** (stop/target only, let winners run) | **+₹51,947** | −₹18,964 |
| Breakeven only | +₹9,960 | −₹35,797 |
| Breakeven + partial | +₹21,669 | −₹27,624 |
| Full adaptive (BE + partial + velocity) | −₹2,763 | −₹6,855 |

### Day-level (static @70) — note the single trend day
Nov 17 **+₹14,745** · Nov 18 **−₹15,819** · Nov 19 **+₹53,021**

## Findings
1. **The strategy's edge, when present, is letting 2:1 winners run.** On the Nov 19 trend day, static
   exits captured +₹53k; every layer of exit-management booked those winners early and gave it back.
2. **The adaptive exit engine (from PR #28) HURTS in the profitable regime.** At score 70 it turns
   static's +₹52k into −₹3k. The **velocity governor is the biggest winner-cutter** and also inflates
   churn (freeing symbols to re-enter → more net-negative trades: 163 → 290).
3. **Breakeven@1R also hurts** here — it stops out trades at entry on a pullback that would have gone
   on to hit the 2:1 target.
4. The adaptive exits only "help" at the high threshold (≥80) where the raw strategy *loses anyway* —
   they just lose less. That is not an edge.
5. **Mechanising the trader's discretionary "book early" (APL Apollo) as a blanket velocity rule was
   wrong.** The trader books early on a *real level rejection* he reads; a time/velocity formula books
   good trades indiscriminately.

## Decisions taken
- **Exit-engine extras defaulted OFF** (`config.json`: `exit_velocity_governor=false`,
  `exit_partial_frac=0`, `exit_breakeven_at_r=0`) → live paper reverts to **let-winners-run** static
  stop/target, which the evidence supports. The machinery stays, fully tunable, dormant until a larger
  backtest justifies turning it on.

## Next
- **Get more data** (2+ weeks) before trusting any magnitude — 2.5 days + one trend day is not enough.
- **Rebuild "smart early exit" around actual structure/level rejection** (the ≥3-rejection + VP/pivot
  levels), not a velocity formula, then re-backtest.
- Add ORB and confluence-gated entries to the harness to compare entry quality.

---

# UPDATE — 22-day backtest on real NSE data (Oct 21 – Nov 20 2026)

Fetched ~1 month of real NSE 5-minute history for 98 symbols from Yahoo (public tickers, no token;
`tools/fetch_yahoo.py`). **This overturns the 4-day conclusions — the small sample was luck.**

### Native runs (static let-winners-run; weekly P&L in brackets)
| config | trades | win% | TOTAL | weekly swings |
|---|---|---|---|---|
| score≥60 raw | 2604 | 31% | **+₹133,260** | W45 **−₹132k**, W46 +₹123k — unusable variance |
| score≥70 raw | 1359 | 31% | **−₹28,314** | −8/−47/−117/+88/+56 k |
| **score≥70 + confluence≥50** | 120 | 30% | **+₹1,421** | **+2/−16/−9/+16/+8 k** (tame) |
| score≥60 + confluence≥50 | 140 | 30% | −₹991 | similar tame profile |

### Findings (robust)
1. **The raw SMC strategy is NOT a reliable edge.** Win% is ~30–31% at *every* score threshold
   (50→90) — a higher score does **not** mean a better trade. Totals are dominated by **variance**,
   not edge: score≥60 "+₹133k" comes with a **−₹132k single week**. Not deployable for real money.
2. **Adaptive exits hurt — confirmed on 22 days** (score≥70: static −₹44k vs adaptive −₹125k; 72% win
   but big loss = winners cut, losers full). The exit-defaults-OFF decision holds.
3. **The confluence layer's real value is RISK CONTROL, not higher return.** `confluence≥50` collapses
   the weekly swings from ±₹130k to ±₹16k and nudges the month to ~break-even (+₹1.4k). On the small
   4-day sample confluence looked anti-predictive; on a month it clearly tames variance.
4. So the hand-weighted confluence already helps consistency. **Learning the weights from logged
   outcomes (Phase 2) is the lever to turn break-even into positive** — with a proper train/test split.

### Bottom line
As configured, the strategy is **break-even at best after variance control, not yet profitable.** Do
NOT put real money on it. The path: confluence-gate for consistency → **learn the confluence weights on
real outcomes (train/test)** → re-backtest. The harness + the month of data make that measurable now.

---

# FULL EXPERIMENT CAMPAIGN (22 days real data) — honest verdict

Every main lever tested on the month of real NSE data:

| experiment | result | verdict |
|---|---|---|
| Score threshold 50→90 (static) | win% flat ~30% at **every** threshold; totals are variance (+133k w/ a −132k week) | score is **not** a quality filter |
| Adaptive exits (velocity/partial/BE) | −125k vs −44k static; 72% win but winners cut | **hurts** — defaulted off |
| Hand-weighted confluence gate | collapses weekly swing ±130k → ±16k, ~break-even | **risk control only**, no return |
| Learned weights (logreg, train/test) | only durable signal is `is_long` (regime-fit); SMC score **−0.17** (anti-predictive) | **no learnable edge** in these features |
| Nearest-level targets (trader's exit) | win% 31→44% but **−164k** (small reward, full stop) | **worse** mechanically |

## The honest conclusion
**No mechanical configuration of the current SMC feature set has a durable edge over a month of real
data.** Win rate sits at ~30% regardless of filters; P&L is dominated by **market regime and variance**,
not signal. The SMC score is slightly anti-predictive. The trader is profitable *manually* because of
**discretionary skill** these mechanical features don't capture — specific multi-indicator confluence
read in real time, tight adaptive stops (not wide structure/ATR stops), and level-rejection exits.

**What this rules out:** more parameter tuning on this feature set. **What the data still supports:**
confluence gating for *consistency* (not profit). **Realistic forks (fundamentally different, need a
decision):** (1) encode the trader's execution far more faithfully — 1-minute timing + tight stops +
exact confluence — and re-test; (2) ship this as a **scanner/alert** tool (surface setups, trader
executes) rather than an auto-trader; (3) richer data/features (order flow, more indicators) for ML.
The harness + Yahoo fetcher make any of these measurable.

## Follow-up: tight stops + regime filters (exhaustive) — still beta, not edge
- **Tight ATR stops** flip per-trade expectancy positive (0.3×ATR + nearest target: +₹345k, avg
  +₹133/trade) — BUT a train/test split exposes it as pure beta: **1st half −₹73k, 2nd half +₹419k**.
  All the profit is the bull fortnight (W46–47); choppy/down weeks lose in every config.
- **Intraday regime filter** (trade only strong-trend days): non-monotonic, overfit; the one "good"
  threshold (+₹80k) concentrates entirely in W46–47 too.
- **Market-regime trend-following** (trade with the universe's prior-3-day trend — the principled lever
  that *should* capture the good beta): **−₹65,921, BOTH halves negative.** It destroyed the beta
  rather than capturing it — intraday regime does not persist usefully here.

## FINAL VERDICT
Across entries (score, hand + learned confluence), exits (adaptive, nearest-level), stops (wide, tight),
and regime filters (intraday, market trend) — **no durable, regime-independent mechanical edge exists in
this data.** Winning configs are unpredictable long-beta. **A mechanical auto-trader on these features
should not trade real money.**

### The honest path to the real goal (auto-trade on real money)
The edge that exists is the **trader's discretionary skill**. The way to eventually automate it is to
**learn from the trader, not from mechanical labels**:
1. **Scanner/decision-support** — compute the full confluence stack and show it on the radar so the
   trader acts faster and better (plays to the real edge). *(Being built.)*
2. **Log the trader's ACTUAL trades + reasoning + outcomes** (the `Order.features` + feature-logging
   plumbing already exists) — this is real labelled data of *what actually works*, far richer than the
   ~30%-win mechanical signals.
3. **Learn a model on that human-generated data** once enough accumulates (weeks/months), then and only
   then consider auto-trading what's been proven to work. This reaches the goal *through* the trader's
   edge instead of pretending a mechanical edge exists where the data says it doesn't.

---

## Addendum (2026-11-23): static risk:reward — does structure stops / no-2:1-gate / let-run help?

The trader flagged that the **static R:R** (fixed ATR stops + a hard 2:1 reward:risk reject + a fixed
target) causes frequent stop-outs and caps profit, and that they never use those parameters manually.
We built reversible flags for all three (`smc_stop_mode`, `smc_enforce_min_rr`, `smc_runner_target`) and
backtested every combination on the 22-day real dataset (98 symbols, score≥80, ₹1,000/trade), split
first-half / second-half to catch regime luck:

| config | trades | win% | total | 1st-half | 2nd-half |
|---|---:|---:|---:|---:|---:|
| CURRENT (plan stop, fixed target, 2:1 gate) | 254 | 28% | −54,673 | −47,860 | −6,814 |
| No 2:1 gate | 255 | 28% | −52,655 | −45,841 | −6,814 |
| Structure stop only | 271 | 26% | −51,922 | −39,471 | −12,452 |
| Let-run only (no cap) | 255 | 28% | −51,466 | −45,841 | −5,625 |
| TRADER-FAITHFUL (structure + run + no gate) | 275 | 26% | −55,914 | −42,468 | −13,445 |

**Verdict: no mechanical improvement.** All five land within ~₹4k of each other (noise), every variant
loses on this (bear-leaning) stretch, and the full trader-faithful combo is marginally the *worst*. This
is consistent with the main campaign: the P&L is driven by regime, not by the stop/target/R:R rule. The
trader's manual edge is real-time discretion — *where* structure actually sits and *when* to exit — which
a fixed swing-level + hold-to-square-off approximation does not reproduce. **Decision: ship the flags
default-OFF** (so the trader can still experiment live in paper/sim, where their timing differs from a
mechanical replay), do **not** flip defaults, and keep the real path = learn from the trader's own logged
discretionary trades.
