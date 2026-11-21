"""Pure, stdlib-only technical indicators for the SMC/ORB confluence layer.

Every function here is a pure function of its inputs (no I/O, no engine state) so it is trivially
unit-testable and reusable by both the live engine and backtests. No pandas/numpy — the rest of the
codebase is hand-rolled on the stdlib and we keep it that way.

Currently:
  - rsi()         : Wilder's RSI (the TradingView "RSI 14 close" default).
  - fib_pivots()  : Fibonacci pivot points (P, R1-R3, S1-S3) from a prior period's H/L/C.
  - nearest_level(): closest level to a price from a set, with side/distance helpers.
"""
from __future__ import annotations

from typing import Optional


# --------------------------------------------------------------------------------------------------
# RSI (Wilder)
# --------------------------------------------------------------------------------------------------
def rsi(closes: list[float], period: int = 14) -> Optional[float]:
    """Latest Wilder's RSI over `closes`, or None if there isn't enough data.

    Matches TradingView's default RSI (Wilder smoothing / RMA), which is what the trader reads as
    "RSI 14 close". Needs at least `period + 1` closes. Returns a value in [0, 100].

    Edge cases: an all-up series (no losses) -> 100; an all-down series (no gains) -> 0.
    """
    if period < 1 or closes is None or len(closes) < period + 1:
        return None

    # Seed: simple average of the first `period` gains/losses.
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period

    # Wilder smoothing across the remaining closes.
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = delta if delta > 0 else 0.0
        loss = -delta if delta < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0  # flat series -> neutral
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


# --------------------------------------------------------------------------------------------------
# Fibonacci pivot points
# --------------------------------------------------------------------------------------------------
# TradingView "Pivots Fibonacci" multipliers for R1-R3 / S1-S3.
_FIB_MULTS = (0.382, 0.618, 1.0)


def fib_pivots(high: float, low: float, close: float) -> dict[str, float]:
    """Fibonacci pivot levels from a prior period's High/Low/Close.

    Returns {'P','R1','R2','R3','S1','S2','S3'}. P = (H+L+C)/3; Rn = P + mult_n*(H-L);
    Sn = P - mult_n*(H-L) with mults (0.382, 0.618, 1.0). This is the standard TradingView
    "Pivots Fibonacci" calculation (the trader's "Pivots Fibonacci Auto" uses prior-session H/L/C).

    Raises ValueError on invalid input (non-positive prices or high < low).
    """
    if high is None or low is None or close is None:
        raise ValueError('fib_pivots: high/low/close are required')
    if high <= 0 or low <= 0 or close <= 0:
        raise ValueError(f'fib_pivots: prices must be positive (h={high}, l={low}, c={close})')
    if high < low:
        raise ValueError(f'fib_pivots: high ({high}) < low ({low})')

    p = (high + low + close) / 3.0
    rng = high - low
    r1, r2, r3 = (p + m * rng for m in _FIB_MULTS)
    s1, s2, s3 = (p - m * rng for m in _FIB_MULTS)
    return {
        'P': round(p, 2),
        'R1': round(r1, 2), 'R2': round(r2, 2), 'R3': round(r3, 2),
        'S1': round(s1, 2), 'S2': round(s2, 2), 'S3': round(s3, 2),
    }


# --------------------------------------------------------------------------------------------------
# Level helpers (used by the exit engine's "nearest structural level" logic)
# --------------------------------------------------------------------------------------------------
def nearest_level(price: float, levels: list[float], *, above: Optional[bool] = None
                  ) -> Optional[float]:
    """Closest level to `price` from `levels`.

    `above=True` restricts to levels strictly above price (e.g. a LONG target / SHORT stop),
    `above=False` to levels strictly below, `above=None` considers both sides. Returns None if no
    candidate qualifies.
    """
    if not price or not levels:
        return None
    if above is True:
        cands = [x for x in levels if x is not None and x > price]
    elif above is False:
        cands = [x for x in levels if x is not None and x < price]
    else:
        cands = [x for x in levels if x is not None]
    if not cands:
        return None
    return min(cands, key=lambda x: abs(x - price))
