"""Market-structure engine — HH/HL/LH/LL labelling, trend, and BOS vs CHoCH.

A proper structural read over the sequence of confirmed swings, replacing the engine's crude
single-bar close-through-swing test (smc_engine `_analyze_symbol`). Distinguishes:
  - BOS  (Break of Structure)      : price breaks structure IN the prevailing trend -> continuation.
  - CHoCH (Change of Character)     : price breaks structure AGAINST the trend -> potential reversal
                                      (and flips the structural bias).

Pure, stdlib-only. `swings` is a time-ordered list of (kind, level) with kind in {'H','L'}.
"""
from __future__ import annotations

from typing import Optional


def label_swings(swings: list[tuple[str, float]]) -> list[str]:
    """Label each swing HH/LH (highs) or HL/LL (lows) vs the previous same-type swing. The first of
    each type is just 'H'/'L' (no prior to compare)."""
    labels, prev_h, prev_l = [], None, None
    for kind, level in swings:
        if kind == 'H':
            lab = 'H' if prev_h is None else ('HH' if level > prev_h else 'LH')
            prev_h = level
        else:
            lab = 'L' if prev_l is None else ('HL' if level > prev_l else 'LL')
            prev_l = level
        labels.append(lab)
    return labels


def market_trend(swings: list[tuple[str, float]]) -> str:
    """'BULLISH' (HH + HL), 'BEARISH' (LH + LL), else 'NEUTRAL' from the latest high & low labels."""
    labels = label_swings(swings)
    last_h = next((labels[i] for i in range(len(swings) - 1, -1, -1) if swings[i][0] == 'H'), None)
    last_l = next((labels[i] for i in range(len(swings) - 1, -1, -1) if swings[i][0] == 'L'), None)
    if last_h == 'HH' and last_l == 'HL':
        return 'BULLISH'
    if last_h == 'LH' and last_l == 'LL':
        return 'BEARISH'
    return 'NEUTRAL'


def _last_level(swings: list[tuple[str, float]], kind: str) -> Optional[float]:
    for k, lvl in reversed(swings):
        if k == kind:
            return lvl
    return None


def break_event(swings: list[tuple[str, float]], price: float) -> Optional[dict]:
    """If `price` breaks the most recent structural high/low, classify it BOS vs CHoCH.

    Returns {'type': 'BOS'|'CHOCH', 'dir': 'BULLISH'|'BEARISH', 'level', 'from_trend'} or None.
    A break in the trend's direction is BOS (continuation); against it (or from NEUTRAL) is CHoCH.
    """
    if not swings or not price:
        return None
    trend = market_trend(swings)
    last_high = _last_level(swings, 'H')
    last_low = _last_level(swings, 'L')
    if last_high is not None and price > last_high:
        return {'type': 'BOS' if trend == 'BULLISH' else 'CHOCH', 'dir': 'BULLISH',
                'level': last_high, 'from_trend': trend}
    if last_low is not None and price < last_low:
        return {'type': 'BOS' if trend == 'BEARISH' else 'CHOCH', 'dir': 'BEARISH',
                'level': last_low, 'from_trend': trend}
    return None
