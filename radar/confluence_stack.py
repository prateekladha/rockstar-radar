"""Compute the trader's full confluence stack from live SMC state — for DECISION SUPPORT.

Pulls together everything the trader reads (RSI, Fibonacci pivots, volume profile VAH/VAL/POC + shape,
cumulative RVOL, structure trend/event) plus the weighted confluence score, into one dict attached to
each SMC opportunity and shown on the radar. This is to AMPLIFY the trader's judgment — the backtest
proved these signals have no standalone mechanical edge, so the score is context, never an auto gate.

Pure: a function of the symbol's candle buffer + state. Degrades gracefully (None fields) when the
in-memory buffer lacks the history a given indicator needs.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from . import indicators, volume_profile, rvol_cum, confluence


def compute_confluence_stack(state, side: Optional[str] = None) -> Optional[dict]:
    candles = getattr(state, 'candles', None)
    if not candles:
        return None
    closes = [c.close for c in candles]
    price = closes[-1]

    by_day = defaultdict(list)
    for c in candles:
        by_day[c.at.date()].append(c)
    all_days = sorted(by_day)
    today = all_days[-1]
    today_candles = by_day[today]
    prior_days = all_days[:-1]

    # RSI
    rsi = indicators.rsi(closes, 14)

    # Fibonacci pivots from the previous session in the buffer
    pivots = None
    if prior_days:
        pc = by_day[prior_days[-1]]
        try:
            pivots = indicators.fib_pivots(max(c.high for c in pc), min(c.low for c in pc), pc[-1].close)
        except ValueError:
            pivots = None

    # Volume profile over today's candles
    vp_full = volume_profile.volume_profile(today_candles, bins=20) if len(today_candles) >= 5 else None
    vp = {k: vp_full[k] for k in ('vah', 'val', 'poc', 'shape')} if vp_full else None

    # Cumulative RVOL-at-time
    rvolc = rvol_cum.rvol_cumulative([c.volume for c in today_candles],
                                     [[c.volume for c in by_day[d]] for d in prior_days], min_days=2)

    # Structure
    trend = getattr(state, 'trend', 'NEUTRAL')
    structs = getattr(state, 'structures', None)
    last_event = structs[-1].structure_type if structs else None

    # Confluence score (context only). Infer side from the plan/zone if not given.
    if side is None:
        plan = getattr(getattr(state, 'opportunity', None), 'trade', None) or {}
        side = plan.get('side')
    vp_support = 0.5
    if vp:
        if side == 'LONG':
            vp_support = 1.0 if price <= vp['val'] else (0.6 if price <= vp['poc'] else 0.2)
        elif side == 'SHORT':
            vp_support = 1.0 if price >= vp['vah'] else (0.6 if price >= vp['poc'] else 0.2)
    opp = getattr(state, 'opportunity', None)
    sig = {
        'side': side,
        'zone_strength': 0.8 if (opp and opp.zone and opp.zone.zone_type in ('DISCOUNT', 'PREMIUM')) else 0.3,
        'ob_strength': 0.8 if (opp and opp.trade and opp.trade.get('in_fresh_ob')) else 0.0,
        'fvg_strength': 0.0,
        'structure': 1 if trend == ('BULLISH' if side == 'LONG' else 'BEARISH') else 0,
        'rvol': rvolc,
        'rsi': rsi,
        'vp_support': vp_support,
    }
    cs = confluence.confluence_score(sig)

    return {
        'rsi': rsi,
        'pivots': pivots,
        'vp': vp,
        'rvol_cum': rvolc,
        'trend': trend,
        'structure_event': last_event,
        'score': cs['score'],
        'components': cs['components'],
    }
