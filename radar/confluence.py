"""Transparent weighted confluence score (Phase 2).

Combines the layers the trader reads (docs §2.3) into one 0-100 score for a given direction, with a
full per-component BREAKDOWN so every number is explainable. Weights are hand-set defaults now; the
per-trade feature/outcome logging (see server.trade_features) accumulates real results so these can be
re-weighted later on data — NOT a per-tick black box.

This is a PURE combiner: it takes already-computed component strengths (0..1) and raw RSI/RVOL values,
and returns points. The wiring that computes those inputs from live engine state lives elsewhere, so
this stays deterministic and unit-testable.
"""
from __future__ import annotations

from typing import Optional

# Hand-set initial weights (sum = 100). Tunable via config later; re-weighted on logged outcomes.
DEFAULT_WEIGHTS = {
    'zone': 20,            # premium/discount location (discount->long, premium->short)
    'order_block': 20,     # price in a fresh order block of the matching bias
    'fvg': 10,             # price in an unfilled fair value gap
    'structure': 15,       # BOS/CHoCH supporting the direction
    'rvol': 10,            # cumulative RVOL-at-time (participation / fuel)
    'rsi': 10,             # momentum, not exhausted
    'volume_profile': 15,  # price vs VAH/VAL/POC + supportive shape
}


def _clamp01(x: Optional[float]) -> float:
    if x is None:
        return 0.0
    return 0.0 if x < 0 else (1.0 if x > 1 else float(x))


def _trapezoid(x: float, a: float, b: float, c: float, d: float) -> float:
    """1.0 on [b,c], ramping from 0 at a->b and back to 0 at c->d, 0 outside [a,d]."""
    if x <= a or x >= d:
        return 0.0
    if x < b:
        return (x - a) / (b - a)
    if x <= c:
        return 1.0
    return (d - x) / (d - c)


def rvol_strength(rvol: Optional[float]) -> float:
    """0 at/below average (1.0x), ramping to 1.0 at 2.0x participation."""
    if rvol is None:
        return 0.0
    return _clamp01(rvol - 1.0)


def rsi_strength(rsi: Optional[float], side: Optional[str]) -> float:
    """Directional momentum support: LONG likes a rising-but-not-overbought RSI (peak ~55-65),
    SHORT likes a falling-but-not-oversold RSI (peak ~35-45). Neutral (0.5) when RSI is unknown."""
    if rsi is None:
        return 0.5
    if side == 'LONG':
        return _trapezoid(rsi, 40, 55, 65, 80)
    if side == 'SHORT':
        return _trapezoid(rsi, 20, 35, 45, 60)
    return 0.0


def confluence_score(signals: dict, weights: Optional[dict] = None) -> dict:
    """Weighted confluence score for signals['side'] ('LONG'|'SHORT').

    signals keys (all optional, default to no contribution):
      side            : 'LONG' | 'SHORT'
      zone_strength   : 0..1  (depth into discount for long / premium for short)
      ob_strength     : 0..1  (fresh order-block confluence; 0 if not in one)
      fvg_strength    : 0..1  (unfilled FVG confluence)
      structure       : >0 supports the side (BOS/CHoCH aligned), else 0
      rvol            : cumulative RVOL-at-time (raw ratio)
      rsi             : RSI value (raw)
      vp_support      : 0..1  (price vs VAH/VAL/POC + shape, supportive of the side)

    Returns {'side', 'score' (0-100), 'components': {name: points}, 'weights'}.
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    side = signals.get('side')
    comp = {
        'zone': w['zone'] * _clamp01(signals.get('zone_strength')),
        'order_block': w['order_block'] * _clamp01(signals.get('ob_strength')),
        'fvg': w['fvg'] * _clamp01(signals.get('fvg_strength')),
        'structure': w['structure'] * (1.0 if (signals.get('structure') or 0) > 0 else 0.0),
        'rvol': w['rvol'] * rvol_strength(signals.get('rvol')),
        'rsi': w['rsi'] * rsi_strength(signals.get('rsi'), side),
        'volume_profile': w['volume_profile'] * _clamp01(signals.get('vp_support')),
    }
    score = round(sum(comp.values()), 1)
    return {
        'side': side,
        'score': min(100.0, score),
        'components': {k: round(v, 1) for k, v in comp.items()},
        'weights': w,
    }
