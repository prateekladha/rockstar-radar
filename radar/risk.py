"""Position sizing for the full trade ticket (CLAUDE.md: configurable % risk, hard ceiling).

Pure, side-effect-free. Given an entry and stop, size the position so the rupee loss if
the stop is hit stays within risk_pct of capital. This is a SUGGESTED quantity for a manual
trade — the scanner never places orders.
"""
from __future__ import annotations
from math import floor
from typing import Optional


def position_size(entry: Optional[float], stop: Optional[float],
                  capital: float, risk_pct: float) -> dict:
    """Return {qty, risk_budget, per_share_risk, actual_risk}.

    qty = floor(risk_budget / per_share_risk). Returns qty 0 when it cannot be sized
    (missing/zero prices or non-positive stop distance), never a negative or guessed size.
    """
    risk_budget = round(max(0.0, capital) * max(0.0, risk_pct) / 100.0, 2)
    if not entry or not stop or entry <= 0 or stop <= 0:
        return {'qty': 0, 'risk_budget': risk_budget, 'per_share_risk': None, 'actual_risk': 0.0}
    per_share = abs(entry - stop)
    if per_share <= 0 or risk_budget <= 0:
        return {'qty': 0, 'risk_budget': risk_budget,
                'per_share_risk': round(per_share, 4), 'actual_risk': 0.0}
    qty = int(floor(risk_budget / per_share))
    return {'qty': qty, 'risk_budget': risk_budget,
            'per_share_risk': round(per_share, 4),
            'actual_risk': round(qty * per_share, 2)}
