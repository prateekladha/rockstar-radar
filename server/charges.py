"""Statutory + brokerage cost model for INTRADAY EQUITY on NSE (FYERS schedule).

Pure, side-effect-free. Given the buy-leg and sell-leg values of a round-trip intraday trade,
return the itemised costs a real FYERS order would incur, so paper P&L can be booked NET of costs
(the single biggest reason a paper "winner" is a live loser).

Every rate is sourced from FYERS's published charges (verified 2026-11-23 — see
docs/PAPER_LIVE_PARITY.md) and is overridable via config so it can be trued-up against a real
contract note. Nothing here is estimated beyond what FYERS publishes.

Intraday equity specifics baked in:
  - Brokerage: min(cap, pct% of each leg's turnover), charged PER executed order (both legs).
  - STT: sell side only.
  - Stamp duty: buy side only.
  - Exchange txn + SEBI + IPFT: both sides (on total turnover).
  - GST: on (brokerage + exchange txn + IPFT) only — not on STT, stamp, or SEBI.
"""
from __future__ import annotations

# FYERS INTRADAY EQUITY (NSE) rate card — defaults; override via config (see _rates()).
DEFAULT_RATES = {
    'brokerage_pct': 0.03,     # % of each leg's turnover
    'brokerage_cap': 20.0,     # ₹ cap per executed order (leg)
    'stt_sell_pct': 0.025,     # % on the SELL leg only
    'exch_txn_pct': 0.00297,   # % NSE equity, both legs
    'sebi_per_cr': 10.0,       # ₹ per crore of turnover, both legs
    'ipft_per_cr': 10.0,       # ₹ per crore NSE, both legs
    'stamp_buy_pct': 0.003,    # % on the BUY leg only
    'gst_pct': 18.0,           # % on (brokerage + exch_txn + ipft)
}

_PER_CR = 1e7  # ₹ per crore -> fraction: amount * rate_per_cr / 1e7


def _rates(cfg: dict | None) -> dict:
    """Merge config overrides over the published defaults. Accepts a flat cfg dict whose keys match
    DEFAULT_RATES (missing/None keys keep the default)."""
    r = dict(DEFAULT_RATES)
    if cfg:
        for k in r:
            v = cfg.get(k)
            if v is not None:
                try:
                    r[k] = float(v)
                except (TypeError, ValueError):
                    pass
    return r


def _leg_brokerage(turnover: float, r: dict) -> float:
    return min(r['brokerage_cap'], r['brokerage_pct'] / 100.0 * turnover) if turnover > 0 else 0.0


def round_trip_charges(buy_value: float, sell_value: float, cfg: dict | None = None) -> dict:
    """Itemised intraday round-trip costs for a trade with the given buy-leg and sell-leg values (₹).

    Returns a dict: brokerage, stt, exch_txn, sebi, ipft, stamp, gst, total (all ₹, rounded 2dp).
    buy_value/sell_value are price*qty of each leg (order of legs doesn't matter for cost)."""
    r = _rates(cfg)
    buy_value = max(0.0, float(buy_value or 0.0))
    sell_value = max(0.0, float(sell_value or 0.0))
    turnover = buy_value + sell_value

    brokerage = _leg_brokerage(buy_value, r) + _leg_brokerage(sell_value, r)
    stt = r['stt_sell_pct'] / 100.0 * sell_value
    exch_txn = r['exch_txn_pct'] / 100.0 * turnover
    sebi = r['sebi_per_cr'] / _PER_CR * turnover
    ipft = r['ipft_per_cr'] / _PER_CR * turnover
    stamp = r['stamp_buy_pct'] / 100.0 * buy_value
    gst = r['gst_pct'] / 100.0 * (brokerage + exch_txn + ipft)
    total = brokerage + stt + exch_txn + sebi + ipft + stamp + gst
    return {
        'brokerage': round(brokerage, 2), 'stt': round(stt, 2), 'exch_txn': round(exch_txn, 2),
        'sebi': round(sebi, 2), 'ipft': round(ipft, 2), 'stamp': round(stamp, 2),
        'gst': round(gst, 2), 'total': round(total, 2),
    }


def trade_charges(side: str, entry_fill: float, exit_fill: float, qty: int,
                  cfg: dict | None = None) -> dict:
    """Round-trip costs for one intraday position, mapping entry/exit fills to buy/sell legs by side.

    LONG  -> buy at entry, sell at exit.   SHORT -> sell at entry, buy at exit.
    Returns the same dict as round_trip_charges (zeros if qty/prices missing)."""
    try:
        q = int(qty or 0)
    except (TypeError, ValueError):
        q = 0
    if q <= 0 or not entry_fill or not exit_fill:
        return round_trip_charges(0.0, 0.0, cfg)
    entry_val, exit_val = float(entry_fill) * q, float(exit_fill) * q
    if side == 'LONG':
        buy_value, sell_value = entry_val, exit_val
    else:  # SHORT: entry is the sell leg
        buy_value, sell_value = exit_val, entry_val
    return round_trip_charges(buy_value, sell_value, cfg)
