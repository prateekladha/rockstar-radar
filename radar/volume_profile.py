"""Fixed-range / session Volume Profile — VAH, VAL, POC and the P/b/B/D shape.

Pure, stdlib-only (no numpy). Builds a volume-at-price histogram from intraday candles, then derives:
  - POC  : point of control (price bin with the most traded volume) — the session magnet.
  - VA    : value area — the smallest contiguous band around the POC holding ~`value_area_pct`
            (default 70%) of total volume; its bounds are VAH (high) and VAL (low).
  - shape : the auction shape the trader reads (docs §2.3):
              D = balanced (POC central),
              P = rally-then-consolidation / bullish bias (POC high),
              b = sell-off-then-consolidation / bearish bias (POC low),
              B = two stacked distributions / trend continuation (bimodal).
            The trader treats the shape as CONTEXT, not a lone signal — see docs §2.3.

Each candle's volume is distributed uniformly across the price bins its [low, high] range spans, so a
wide bar spreads its volume and a tight bar concentrates it (a reasonable stdlib approximation of a
true tick/TPO profile).
"""
from __future__ import annotations

from typing import Optional


def _candle_fields(c):
    """Accept a Candle-like object (attrs) or a dict; return (low, high, volume)."""
    if isinstance(c, dict):
        return float(c['low']), float(c['high']), float(c.get('volume') or 0.0)
    return float(c.low), float(c.high), float(getattr(c, 'volume', 0) or 0.0)


def build_histogram(candles, bins: int = 24) -> Optional[dict]:
    """Volume-at-price histogram over the candles. Returns dict with lo, hi, bin_width, vols (list),
    centers (list), total — or None if there's no usable range/volume."""
    if not candles or bins < 2:
        return None
    lows, highs, vols_in = [], [], []
    for c in candles:
        lo, hi, v = _candle_fields(c)
        if hi < lo:
            lo, hi = hi, lo
        lows.append(lo); highs.append(hi); vols_in.append(v)
    lo_all, hi_all = min(lows), max(highs)
    rng = hi_all - lo_all
    if rng <= 0 or sum(vols_in) <= 0:
        return None
    bw = rng / bins
    vols = [0.0] * bins

    def _bin(p: float) -> int:
        idx = int((p - lo_all) / bw)
        return 0 if idx < 0 else (bins - 1 if idx >= bins else idx)

    for lo, hi, v in zip(lows, highs, vols_in):
        if v <= 0:
            continue
        b0, b1 = _bin(lo), _bin(hi)
        span = b1 - b0 + 1
        share = v / span
        for b in range(b0, b1 + 1):
            vols[b] += share

    centers = [lo_all + (i + 0.5) * bw for i in range(bins)]
    return {'lo': lo_all, 'hi': hi_all, 'bin_width': bw, 'vols': vols,
            'centers': centers, 'total': sum(vols)}


def _value_area(vols: list[float], poc_idx: int, value_area_pct: float) -> tuple[int, int]:
    """Expand from the POC bin, always taking the higher-volume neighbour, until >= target volume.
    Returns (low_idx, high_idx) inclusive."""
    total = sum(vols)
    target = value_area_pct * total
    lo = hi = poc_idx
    acc = vols[poc_idx]
    n = len(vols)
    while acc < target and (lo > 0 or hi < n - 1):
        below = vols[lo - 1] if lo > 0 else -1.0
        above = vols[hi + 1] if hi < n - 1 else -1.0
        if above >= below:
            hi += 1; acc += max(above, 0.0)
        else:
            lo -= 1; acc += max(below, 0.0)
    return lo, hi


def _classify_shape(vols: list[float], poc_idx: int) -> str:
    """P / b / B / D from the POC position and bimodality."""
    n = len(vols)
    pos = poc_idx / (n - 1) if n > 1 else 0.5
    peak = max(vols) or 1.0
    # Bimodal (B): a second strong, separated peak (>=60% of the POC, >=3 bins away).
    for i, v in enumerate(vols):
        if i == poc_idx:
            continue
        if v >= 0.6 * peak and abs(i - poc_idx) >= 3:
            # ensure a genuine valley between the two peaks
            a, b = sorted((i, poc_idx))
            if min(vols[a + 1:b]) <= 0.5 * peak:
                return 'B'
    if pos >= 0.6:
        return 'P'   # POC in the upper part -> bullish P-shape
    if pos <= 0.4:
        return 'b'   # POC in the lower part -> bearish b-shape
    return 'D'       # balanced


def volume_profile(candles, bins: int = 24, value_area_pct: float = 0.70) -> Optional[dict]:
    """Full profile: {poc, vah, val, shape, total, lo, hi}. None if no usable data.

    poc/vah/val are prices. `shape` is one of 'P','b','B','D'. See module docstring.
    """
    h = build_histogram(candles, bins)
    if h is None:
        return None
    vols, centers, bw = h['vols'], h['centers'], h['bin_width']
    poc_idx = max(range(len(vols)), key=lambda i: vols[i])
    lo_idx, hi_idx = _value_area(vols, poc_idx, value_area_pct)
    return {
        'poc': round(centers[poc_idx], 2),
        'vah': round(centers[hi_idx] + bw / 2, 2),   # top edge of the highest VA bin
        'val': round(centers[lo_idx] - bw / 2, 2),   # bottom edge of the lowest VA bin
        'shape': _classify_shape(vols, poc_idx),
        'total': round(h['total'], 2),
        'lo': round(h['lo'], 2),
        'hi': round(h['hi'], 2),
    }
