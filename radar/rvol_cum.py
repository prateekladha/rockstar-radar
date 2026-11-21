"""Cumulative Relative Volume at Time — the trader's "Relative Vol 1D 10 Cumulative".

Compares TODAY's cumulative volume from the session open up to a given point in the day against the
average cumulative volume at the SAME point over the last N sessions. >1 means today is trading
heavier than normal for this time of day (real participation / fuel); <1 means thin (fade/trap risk).

This differs from the engine's existing per-bar RVOL (radar.engine `_rvol`, which compares a single
bar's volume to a same-slot median). Here it's the running *cumulative* total, which is what the
trader reads. Pure, stdlib-only.
"""
from __future__ import annotations

from typing import Optional


def cumulative(volumes: list[float]) -> list[float]:
    """Running total of per-bar volumes."""
    out, acc = [], 0.0
    for v in volumes:
        acc += (v or 0.0)
        out.append(acc)
    return out


def rvol_cumulative(today_volumes: list[float], prior_sessions_volumes: list[list[float]],
                    idx: Optional[int] = None, min_days: int = 5) -> Optional[float]:
    """Cumulative RVOL at bar `idx` (default: the last bar of `today_volumes`).

    today_volumes          : today's per-bar volumes from the open (index 0 = first bar of session).
    prior_sessions_volumes : one per-bar volume list per prior session (same bar alignment / cadence).
    Returns today's cumulative volume at `idx` divided by the mean prior-session cumulative at the
    same `idx`, or None if fewer than `min_days` prior sessions reach that bar, or the baseline is 0.
    """
    if not today_volumes:
        return None
    i = (len(today_volumes) - 1) if idx is None else idx
    if i < 0 or i >= len(today_volumes):
        return None
    today_cum = sum((v or 0.0) for v in today_volumes[:i + 1])

    prior_cums = []
    for sess in (prior_sessions_volumes or []):
        if sess and len(sess) > i:
            prior_cums.append(sum((v or 0.0) for v in sess[:i + 1]))
    if len(prior_cums) < min_days:
        return None
    baseline = sum(prior_cums) / len(prior_cums)
    if baseline <= 0:
        return None
    return round(today_cum / baseline, 2)
