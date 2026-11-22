"""Single source of truth for RVOL (relative volume) across the whole product.

Every strategy (ORB radar, SMC/confluence, the Debug tab) computes RVOL through THIS module,
parameterised by the user's settings (calculation mode + lookback length). Before this module the
product had two divergent metrics — per-bar RVOL in the ORB engine and cumulative RVOL-at-time in
SMC/confluence — so the same stock could read differently on different screens. Now there is one.

Two calculation modes on the `day` anchor are implemented (mean/median and week/month anchors are
intentionally not wired yet — the Settings UI only offers what this module supports):

- ``per_bar``   : a single bar's volume / the median same-clock-slot volume on prior sessions.
                  Spiky; good for "is THIS 5-minute bar unusually heavy".
- ``cumulative``: today's cumulative volume from the open up to a slot / the mean prior-session
                  cumulative volume at the same slot. Smooth; "is the DAY trading heavier than
                  normal so far" — the trader's "Relative Vol 1D cumulative". This is the default.

Baselines (the denominators) are precomputed once per session from prior-session candles into BOTH
per-slot dicts, so the live engine can evaluate either mode per bar with no raw-series storage.

Pure, stdlib-only. `cutoff` is exclusive (prior sessions only).
"""
from __future__ import annotations

import os
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Optional

from .models import Candle

VALID_MODES = ('cumulative', 'per_bar')
DEFAULT_MODE = 'cumulative'
DEFAULT_LENGTH = 10

# Minimum prior sessions before a baseline is trustworthy. Cumulative is stable with few sessions
# (it's one number per session); per-bar wants a denser same-slot sample to median over.
_MIN_SESSIONS = 2
_MIN_BAR_SAMPLES = 8
# Baseline schema version — bump to invalidate on-disk baseline caches when the format changes.
BASELINE_SCHEMA = 2


@dataclass(frozen=True)
class RvolConfig:
    """The user's RVOL calculation choice. `anchor` is 'day' for now (only one implemented)."""
    mode: str = DEFAULT_MODE
    length: int = DEFAULT_LENGTH
    anchor: str = 'day'

    @classmethod
    def from_config(cls, config: dict) -> 'RvolConfig':
        """Build from the scanner config dict (keys `rvol_mode`, `rvol_length`).

        utils.load_config injects these from the RADAR_RVOL_* env the scanner is spawned with, so a
        per-user choice reaches the subprocess exactly like the one-minute-candle flag does.
        """
        mode = str(config.get('rvol_mode', DEFAULT_MODE) or DEFAULT_MODE).lower()
        if mode not in VALID_MODES:
            mode = DEFAULT_MODE
        try:
            length = int(config.get('rvol_length', DEFAULT_LENGTH) or DEFAULT_LENGTH)
        except (TypeError, ValueError):
            length = DEFAULT_LENGTH
        return cls(mode=mode, length=max(1, min(100, length)), anchor='day')


def _prior_sessions(history: list[Candle], cutoff: date, length: int) -> list[list[Candle]]:
    """The last `length` prior sessions (date < cutoff), each sorted, in-session bars only."""
    by_day: dict = defaultdict(list)
    for c in history:
        if c.at.date() < cutoff and c.at.hour in range(9, 16):
            by_day[c.at.date()].append(c)
    days = sorted(by_day)[-max(1, length):]
    return [sorted(by_day[d], key=lambda c: c.at) for d in days]


def build_baseline(history: list[Candle], cutoff: date, length: int = DEFAULT_LENGTH) -> dict:
    """Precompute BOTH per-slot baselines from the last `length` prior sessions.

    Returns ``{'v': BASELINE_SCHEMA, 'sessions': n,
               'bar': {HH:MM: median_bar_vol}, 'cum': {HH:MM: mean_cumulative_vol}}``.
    Either sub-dict may be empty when history is too thin for that mode; the caller decides whether
    the symbol is tradeable. Slot keys are 'HH:MM' and align across sessions.
    """
    sessions = _prior_sessions(history, cutoff, length)
    n = len(sessions)
    bar_slots: dict = defaultdict(list)   # slot -> [this-bar volume per session]
    cum_slots: dict = defaultdict(list)   # slot -> [cumulative-from-open volume per session]
    for sess in sessions:
        running = 0.0
        for c in sess:
            slot = c.at.strftime('%H:%M')
            vol = c.volume or 0.0
            if vol > 0:
                bar_slots[slot].append(vol)
            running += vol
            cum_slots[slot].append(running)
    bar: dict = {}
    cum: dict = {}
    if n >= _MIN_SESSIONS:
        bar = {k: statistics.median(v) for k, v in bar_slots.items()
               if len(v) >= min(_MIN_BAR_SAMPLES, n)}
        cum = {k: statistics.fmean(v) for k, v in cum_slots.items()
               if len(v) >= _MIN_SESSIONS}
    return {'v': BASELINE_SCHEMA, 'sessions': n, 'bar': bar, 'cum': cum}


def synthetic_baseline(per_slot: dict, sessions: int = DEFAULT_LENGTH) -> dict:
    """Wrap a flat {HH:MM: per-bar volume} baseline into the rich schema (for sim/demo feeds).

    `cum` is the running sum of `per_slot` in time order, so for a constant synthetic volume the
    cumulative-mode RVOL equals the per-bar RVOL — the practice feed stays calibrated either way.
    """
    bar = dict(per_slot)
    cum: dict = {}
    running = 0.0
    for slot in sorted(per_slot):
        running += per_slot[slot]
        cum[slot] = running
    return {'v': BASELINE_SCHEMA, 'sessions': sessions, 'bar': bar, 'cum': cum}


def baseline_has_data(baseline: Optional[dict], mode: str = DEFAULT_MODE) -> bool:
    """True when `baseline` can actually yield an RVOL for `mode` (non-empty relevant sub-dict)."""
    if not baseline:
        return False
    key = 'bar' if mode == 'per_bar' else 'cum'
    return bool(baseline.get(key))


def is_current_baseline(baseline: Optional[dict]) -> bool:
    """True when a baseline dict is in the current schema (used to invalidate stale caches)."""
    return bool(baseline) and baseline.get('v') == BASELINE_SCHEMA


def rvol_runtime(cfg: RvolConfig, baseline: Optional[dict], *, slot: str,
                 bar_volume: float, today_cum: float) -> Optional[float]:
    """RVOL for the LIVE engine at one bar. Dispatch on the user's mode.

    slot       : the current bar's 'HH:MM'.
    bar_volume : the current bar's volume (used by per_bar).
    today_cum  : today's cumulative in-session volume up to AND INCLUDING this slot (used by
                 cumulative). The engine accumulates this from the session's completed bars.
    Returns None when the relevant baseline slot is missing/zero.
    """
    if not baseline:
        return None
    if cfg.mode == 'per_bar':
        # Tolerate a legacy flat {HH:MM: vol} baseline (no schema keys) as a per-bar table.
        bar = baseline.get('bar') if ('bar' in baseline or 'cum' in baseline) else baseline
        denom = (bar or {}).get(slot)
        return round(bar_volume / denom, 4) if denom and denom > 0 else None
    denom = baseline.get('cum', {}).get(slot)
    return round(today_cum / denom, 4) if denom and denom > 0 else None


def rvol_from_candles(cfg: RvolConfig, candles: list[Candle]) -> Optional[float]:
    """One-shot RVOL from a full multi-session candle buffer (Debug tab / confluence stack).

    Uses the LAST session in the buffer as 'today' and the preceding `length` sessions as the
    baseline, then evaluates the user's mode at today's latest in-session bar. Returns None when
    there are too few prior sessions or no in-session bars today.
    """
    if not candles:
        return None
    by_day: dict = defaultdict(list)
    for c in candles:
        if c.at.hour in range(9, 16):
            by_day[c.at.date()].append(c)
    days = sorted(by_day)
    if len(days) < 2:
        return None
    today = days[-1]
    today_sess = sorted(by_day[today], key=lambda c: c.at)
    if not today_sess:
        return None
    baseline = build_baseline(candles, today, cfg.length)
    running = sum((c.volume or 0.0) for c in today_sess)
    last = today_sess[-1]
    return rvol_runtime(cfg, baseline, slot=last.at.strftime('%H:%M'),
                        bar_volume=(last.volume or 0.0), today_cum=running)


def rvol_thresholds(config: dict, mode: str) -> dict:
    """Per-mode ORB gate thresholds, so the gates stay calibrated to whichever metric is active.

    Reads `config['rvol_thresholds'][mode]`; falls back to flat legacy keys / safe defaults. Keys:
    watch (WATCH floor), ready (READY gate, was the hardcoded 1.25), confirm (breakout confirm).
    """
    table = (config.get('rvol_thresholds') or {})
    md = table.get(mode) or {}
    if mode == 'per_bar':
        return {
            'watch': float(md.get('watch', config.get('min_watch_rvol', 1.0))),
            'ready': float(md.get('ready', 1.25)),
            'confirm': float(md.get('confirm', config.get('min_confirm_rvol', 1.5))),
        }
    # cumulative — conservative principled defaults (PR-2 calibrates these empirically).
    return {
        'watch': float(md.get('watch', 1.0)),
        'ready': float(md.get('ready', 1.1)),
        'confirm': float(md.get('confirm', 1.2)),
    }
