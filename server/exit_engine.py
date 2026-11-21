"""Adaptive paper-exit decisions (Phase 0): breakeven@1R, partial book-half, velocity time-decay.

These are PURE functions (no ORM, no DB, no clock reads beyond what's passed in) so they're trivially
unit-testable. `server.order_engine.process_paper` reads the live price + config, calls these, and
applies the results to the Order. Everything is gated by config and safe when inputs are missing
(e.g. legacy orders with no captured initial stop simply don't get adaptive management).

Encodes the trader's discipline (see docs/SMC_ORB_STRATEGY_DESIGN.md §2.7-2.8):
  - move stop to breakeven once the trade is +1R (a winner can't flip to a loser),
  - book half at +1R and run the rest,
  - and the APL Apollo rule: if the far target is unreachable at the realised favourable pace before
    the management cutoff, book the profit now instead of waiting.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional


def favorable(side: str, fill: float, px: float) -> float:
    """Signed profit distance per share (+ve = in profit) for the trade's direction."""
    return (px - fill) if side == 'LONG' else (fill - px)


def r_distance(fill: float, init_stop: float) -> float:
    """1R in price terms = |fill - original stop|."""
    return abs(fill - init_stop) if (fill and init_stop) else 0.0


def reached_r(side: str, fill: float, init_stop: float, px: float, r_mult: float) -> bool:
    """True once the position is at least `r_mult` R in profit (measured from the ORIGINAL stop)."""
    rd = r_distance(fill, init_stop)
    if rd <= 0 or r_mult <= 0:
        return False
    return favorable(side, fill, px) >= r_mult * rd


def mins_until(now_ist_dt: datetime, cutoff_hhmm: str) -> float:
    """Minutes from `now` (IST) to a HH:MM cutoff the same day (negative if already past)."""
    try:
        h, m = (int(x) for x in cutoff_hhmm.split(':'))
    except Exception:
        return 0.0
    cutoff = now_ist_dt.replace(hour=h, minute=m, second=0, microsecond=0)
    return (cutoff - now_ist_dt).total_seconds() / 60.0


def velocity_exit(side: str, fill: float, px: float, target: Optional[float], elapsed_min: float,
                  now_ist_dt: datetime, cutoff_hhmm: str, slack: float,
                  min_elapsed_min: float = 5.0) -> bool:
    """Book-the-profit-now decision (the APL Apollo velocity rule).

    True when the position is IN PROFIT but the far target is unreachable at the realised favourable
    pace before the management cutoff — so take the nearest profit now rather than waiting. Also True
    once past the cutoff while in profit. Never forces an exit at a loss.
    """
    fav = favorable(side, fill, px)
    if fav <= 0 or target is None:
        return False
    remaining = (target - px) if side == 'LONG' else (px - target)
    if remaining <= 0:
        return False  # target essentially reached — let the normal target fill handle it
    mins_left = mins_until(now_ist_dt, cutoff_hhmm)
    if mins_left <= 0:
        return True   # past the management cutoff and in profit -> book it
    if elapsed_min < min_elapsed_min:
        return False  # too little history to judge pace
    realized_pace = fav / elapsed_min                      # ₹/min achieved (favourable)
    if realized_pace <= 0:
        return True   # in profit but no forward progress -> book it
    required_pace = remaining / mins_left                  # ₹/min needed to still hit target in time
    return required_pace > slack * realized_pace
