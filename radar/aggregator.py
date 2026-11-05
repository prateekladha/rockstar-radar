"""Realtime 5-minute candle aggregation from FYERS SymbolUpdate ticks.

Phase 1 of the product roadmap: lets breakout confirmation fire ~1 second after a
5-minute bar closes, instead of waiting for the throttled REST-history sweep.

IMPORTANT — these are PROVISIONAL candles. A tick stream is LTP snapshots plus a
cumulative daily volume counter, not every executed trade. Open/high/low/close and
volume are therefore close estimates, never tick-exact. The authoritative FYERS
historical 5-minute candle must still reconcile every provisional bar (upgrade a
real breakout, or retract a local false positive). This module NEVER emits an
in-progress (unfinished) bar, mirroring the no-lookahead discipline of the engine.
"""
from __future__ import annotations
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional
from .models import Candle, Tick
from .utils import bar_start


@dataclass
class _Partial:
    """In-progress bar accumulator for one symbol."""
    start: datetime
    open: float
    high: float
    low: float
    close: float
    last_cum_vol: int            # cumulative vol_traded_today at the most recent tick
    close_time: datetime         # exchange time of the most recent tick in this bar


class LiveCandleBuilder:
    """Aggregates ticks into completed 5-minute candles aligned to the exchange grid.

    Volume for a bar = (cumulative daily volume at bar end) - (cumulative at previous
    bar end). The first bar observed for a symbol can only measure the intra-bar delta
    (trades before its first tick are unknown), so it is an UNDERCOUNT, which fails
    closed (lower RVOL => fewer confirmations) and is corrected by REST reconciliation.
    """

    def __init__(self, bar_minutes: int = 5,
                 on_bar: Optional[Callable[[str, Candle], None]] = None):
        self.bar_minutes = bar_minutes
        self.on_bar = on_bar
        self._partial: dict[str, _Partial] = {}
        # Cumulative daily volume at the close of the last EMITTED bar, per symbol.
        self._prev_cum: dict[str, int] = {}
        # Guards concurrent access: the websocket thread (add_tick) and the flush
        # thread (flush_completed) both mutate the dicts below. Lock order is always
        # builder -> engine (on_bar never calls back into the builder), so no deadlock.
        self._lock = threading.RLock()

    def _finalize(self, symbol: str, p: _Partial) -> Candle:
        baseline = self._prev_cum.get(symbol)
        if baseline is None:
            # First bar for this symbol: no prior cumulative reference available.
            baseline = p.last_cum_vol  # yields 0 volume unless more arrives; undercount.
        volume = max(0, int(p.last_cum_vol - baseline))
        self._prev_cum[symbol] = p.last_cum_vol
        candle = Candle(at=p.start, open=p.open, high=p.high,
                        low=p.low, close=p.close, volume=volume)
        if self.on_bar:
            self.on_bar(symbol, candle)
        return candle

    def add_tick(self, tick: Tick) -> Optional[Candle]:
        """Fold a tick into its bar. Returns a completed Candle when a tick from a
        later bar rolls the current one over, otherwise None."""
        if tick.price <= 0:
            return None
        bs = bar_start(tick.time)
        with self._lock:
            p = self._partial.get(tick.symbol)
            if p is None:
                self._prev_cum.setdefault(tick.symbol, int(tick.daily_volume))
                self._partial[tick.symbol] = _Partial(
                    start=bs, open=tick.price, high=tick.price, low=tick.price,
                    close=tick.price, last_cum_vol=int(tick.daily_volume),
                    close_time=tick.time)
                return None
            if bs < p.start:
                # Backdated / out-of-order tick: ignore for bar building.
                return None
            if bs == p.start:
                p.high = max(p.high, tick.price)
                p.low = min(p.low, tick.price)
                p.close = tick.price
                p.last_cum_vol = max(p.last_cum_vol, int(tick.daily_volume))
                p.close_time = max(p.close_time, tick.time)
                return None
            # bs > p.start: the current bar is complete; emit it, then open the new one.
            completed = self._finalize(tick.symbol, p)
            self._partial[tick.symbol] = _Partial(
                start=bs, open=tick.price, high=tick.price, low=tick.price,
                close=tick.price, last_cum_vol=int(tick.daily_volume),
                close_time=tick.time)
            return completed

    def flush_completed(self, now: datetime, grace_seconds: float = 2.0) -> list[tuple[str, Candle]]:
        """Finalize any in-progress bar whose 5-minute window has already elapsed,
        even if no new-bar tick has arrived yet (thin/illiquid symbols). Keeps the
        feed realtime without fabricating empty bars for symbols with no ticks."""
        emitted: list[tuple[str, Candle]] = []
        cutoff = now - timedelta(seconds=grace_seconds)
        with self._lock:
            for symbol, p in list(self._partial.items()):
                if p.start + timedelta(minutes=self.bar_minutes) <= cutoff:
                    emitted.append((symbol, self._finalize(symbol, p)))
                    del self._partial[symbol]
        return emitted

    def seed_prev_cumulative(self, symbol: str, cumulative_volume: int) -> None:
        """Optional: seed the volume baseline from an authoritative source (e.g. the
        last REST candle) so the first live bar measures a correct volume delta."""
        with self._lock:
            self._prev_cum[symbol] = int(cumulative_volume)
