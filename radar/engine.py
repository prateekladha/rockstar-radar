"""Deterministic five-minute opening-range radar.

No order placement. Live alerts are only hypotheses; execution requires manual checking.
"""
from __future__ import annotations
import statistics
import threading
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Callable
from .models import Candle, Instrument, Signal, SymbolState, Tick
from .risk import position_size
from .rvol import RvolConfig, baseline_has_data, rvol_runtime, rvol_thresholds
from .utils import IST, bar_start, market_dt, now_ist, signal_bar_minutes


SIGNAL_STATES = {'WATCH', 'READY', 'BREAKOUT_PENDING', 'CONFIRMED',
                 'RETEST_CANDIDATE', 'RETEST_READY', 'RISK_FAIL', 'FAILED',
                 'EXPIRED', 'RETRACTED'}
PERSISTENT_STATES = {'CONFIRMED', 'RETEST_CANDIDATE', 'RETEST_READY',
                     'RISK_FAIL', 'FAILED', 'EXPIRED', 'RETRACTED', 'SESSION_CONSUMED'}


def same_time_baseline(history: list[Candle], cutoff: date, lookback_sessions: int = 20):
    """Median volume of the same clock slot on previous sessions.

    Slot width is whatever the supplied history uses, so feeding 1-minute candles yields a
    1-minute baseline. RVOL is then a ratio of like for like and stays comparable across both
    settings — a 1-minute bar is measured against 1-minute norms, not against a 5-minute one.
    """
    days = sorted({c.at.date() for c in history if c.at.date() < cutoff})[-lookback_sessions:]
    included = set(days)
    volumes = defaultdict(list)
    for c in history:
        if c.at.date() in included and c.volume > 0 and c.at.hour in range(9, 16):
            volumes[c.at.strftime('%H:%M')].append(c.volume)
    # Only use sufficiently populated history; don't fake normal volumes when missing.
    return {key: statistics.median(v) for key, v in volumes.items()
            if len(v) >= min(8, len(days)) and len(days) >= 10}


class RadarEngine:
    def __init__(self, instruments: list[Instrument], config: dict,
                 session: date, mode: str = 'LIVE', on_signal: Callable[[Signal], None] | None = None):
        self.config = config
        self.mode = mode
        self.session = session
        # Candle the state machine evaluates. The opening range is a fixed wall-clock window
        # (09:15-09:20) and keeps its own width; `bar_minutes` only sets how finely the session is
        # watched afterwards, so on 1m the OR is assembled from five bars instead of being one.
        self.bar_minutes = signal_bar_minutes(config)
        self.bar_seconds = self.bar_minutes * 60
        self.bar_delta = timedelta(minutes=self.bar_minutes)
        self.or_minutes = max(1, int(config.get('open_range_minutes', 5) or 5))
        self.or_bar_count = max(1, self.or_minutes // self.bar_minutes)
        self.lock = threading.RLock()
        self.states = {info.symbol: SymbolState(info) for info in instruments}
        # ONE RVOL metric for the whole product, driven by the user's settings (radar.rvol).
        # `baselines` now holds the richer {'bar':…, 'cum':…} dict build_baseline() produces, so
        # either mode can be evaluated per bar. Gate thresholds are per-mode so switching the metric
        # keeps the WATCH/READY/confirm gates calibrated to whatever scale is active.
        self.rvol_cfg = RvolConfig.from_config(config)
        self.rvol_th = rvol_thresholds(config, self.rvol_cfg.mode)
        self.baselines: dict[str, dict] = {}
        self.events: list[Signal] = []
        self.on_signal = on_signal
        self.feed_health = 'DISCONNECTED' if mode == 'LIVE' else 'SIMULATED'
        self.halted = False
        self.notes: list[str] = []

    def reset(self):
        """Re-initialize all symbol states for a fresh session (the simulation loop replays)."""
        with self.lock:
            self.states = {sym: SymbolState(st.info) for sym, st in self.states.items()}
            self.events = []
            self.halted = False
            self.feed_health = 'SIMULATED'

    def set_baseline(self, symbol: str, values: dict[str, float]):
        with self.lock:
            if symbol in self.states:
                self.baselines[symbol] = values

    def update_health(self, health: str):
        with self.lock:
            if self.halted:
                return
            self.feed_health = health[:250]
            self.notes = ([f'{now_ist().strftime("%H:%M:%S")} {health[:160]}'] + self.notes)[:15]

    def halt(self, reason: str):
        """Fail closed: suppress all active trading signals after an upstream block."""
        with self.lock:
            self.halted = True
            self.feed_health = ('HALTED — ' + reason)[:250]
            self.notes = ([f'{now_ist().strftime("%H:%M:%S")} {self.feed_health[:160]}']
                          + self.notes)[:15]
            for st in self.states.values():
                st.state = 'HALTED'
                st.score = 0
                st.reason = 'FYERS data unavailable; no actionable signals'

    def _event(self, st: SymbolState, new_state: str, when: datetime,
               note: str, level: float, provisional: bool = False):
        # Dedup transitions; no repeated noisy WATCH events every tick.
        # Provisional and authoritative share a key so a later authoritative bar
        # does not re-emit an already-delivered signal; upgrades update reason in place
        # and retractions emit a distinct RETRACTED state (its own key) so the user
        # is told to stand down.
        key = f'{when.date()}:{st.side}:{new_state}'
        if key == st.last_event_key:
            return
        st.last_event_key = key
        st.last_signal_time = when
        actual = now_ist() if self.mode == 'LIVE' else when
        lag_sec = max(0.0, (actual - when).total_seconds())
        sig = Signal(time=when.astimezone(IST).strftime('%Y-%m-%d %H:%M:%S'),
                     symbol=st.info.symbol, side=st.side, state=new_state,
                     score=st.score, price=round(st.last_tick.price if st.last_tick else 0, 2),
                     rvol=round(st.rvol, 2) if st.rvol is not None else None,
                     note=note, level=round(level, 2),
                     entry=st.entry, stop=st.stop, target=st.target,
                     net_rr=round(st.net_rr, 2) if st.net_rr is not None else None,
                     delivered_time_ist=actual.astimezone(IST).strftime('%Y-%m-%d %H:%M:%S'),
                     detection_lag_seconds=round(lag_sec, 1), provisional=provisional)
        self.events.append(sig)
        if self.on_signal:
            self.on_signal(sig)

    def update_tick(self, t: Tick, received_at: datetime | None = None):
        """Early warning can be intrabar; never mark breakout confirmed from a tick."""
        with self.lock:
            if self.halted:
                return
            st = self.states.get(t.symbol)
            if st is None or t.price <= 0 or t.time.date() != self.session:
                return
            current_time = (received_at or now_ist()).astimezone(IST)
            # Backdated/out-of-order ticks and stale feed cannot trigger live alerts.
            if self.mode == 'LIVE' and (abs((current_time - t.time).total_seconds()) >
                                         self.config['market_feed_stale_seconds']):
                st.stale = True
                return
            if st.last_tick and t.time < st.last_tick.time:
                return
            st.last_tick = t
            st.stale = False
            if not st.opening:
                st.state = 'WAIT_OR'
                return
            if not (market_dt(self.session, self.config['watch_start']) <= t.time <=
                    market_dt(self.session, self.config['new_signals_stop'])):
                return
            if st.confirmed_at or st.state in PERSISTENT_STATES:
                return
            op = st.opening
            width = (op.high - op.low) / op.open * 100
            if not (self.config['min_open_range_width_pct'] <= width <=
                    self.config['max_open_range_width_pct']):
                st.state, st.reason = 'FILTERED', 'Opening range too narrow/wide'
                return
            # After laptop sleep/restart the newest stored bar may be hours old.
            # Suppress WATCH/READY until a recent authoritative completed bar exists.
            # An unfinished websocket tick is not a substitute for volume history.
            last = max(st.completed.values(), key=lambda x: x.at)
            if (self.mode == 'LIVE' and
                (current_time - (last.at + self.bar_delta)).total_seconds() > 600):
                st.state, st.reason, st.score = (
                    'RECOVERING',
                    f'Waiting for recent completed {self.bar_minutes}-minute candle after restart', 0)
                return
            st.rvol = self._rvol(st, last)
            st.vwap = t.avg_trade_price or self._candle_vwap(st)
            if st.rvol is None or st.vwap is None:
                st.state, st.reason = 'WAIT_VOLUME', 'Insufficient baseline / VWAP data'
                return
            lo_dist = (t.price - op.low) / op.low * 100
            hi_dist = (op.high - t.price) / op.high * 100
            options = [('LONG', hi_dist, op.high, t.price >= st.vwap),
                       ('SHORT', lo_dist, op.low, t.price <= st.vwap)]
            # Only candidates approaching/outside OR boundary by a controlled amount.
            options = [x for x in options if -self.config['max_extension_pct'] <= x[1] <=
                       self.config['near_boundary_pct'] and x[3]]
            if not options or st.rvol < self.rvol_th['watch']:
                st.state, st.reason, st.score = 'NONE', 'No active qualifying approach', 0
                return
            side, distance, level, _ = min(options, key=lambda x: abs(x[1]))
            st.side, st.distance_pct = side, round(distance, 3)
            st.score = self._score(st, distance)
            if distance < 0:
                next_state = 'BREAKOUT_PENDING'
                st.reason = f'Intrabar breach; wait for complete {self.bar_minutes}-minute close'
            elif distance <= self.config['ready_boundary_pct'] and st.rvol >= self.rvol_th['ready']:
                next_state = 'READY'
                st.reason = 'Near OR boundary; VWAP aligned and volume improving'
            else:
                next_state = 'WATCH'
                st.reason = 'Approaching OR boundary; breakout not yet confirmed'
            if next_state != st.state:
                st.state = next_state
                self._event(st, next_state, t.time, st.reason, level)

    def _rvol(self, st: SymbolState, candle: Candle):
        """RVOL for this bar in the user's configured mode (radar.rvol — one metric product-wide).

        per_bar uses this bar's volume vs the same-slot prior-session median; cumulative uses
        today's cumulative in-session volume up to this bar vs the prior-session cumulative mean at
        the same slot. today_cum is summed from today's completed bars (plus this candle).
        """
        baseline = self.baselines.get(st.info.symbol)
        if not baseline:
            return None
        today = {c.at: c for c in st.completed.values()
                 if c.at.date() == candle.at.date() and c.at.hour in range(9, 16)
                 and c.at <= candle.at}
        today[candle.at] = candle
        today_cum = sum((c.volume or 0.0) for c in today.values())
        return rvol_runtime(self.rvol_cfg, baseline, slot=candle.at.strftime('%H:%M'),
                            bar_volume=(candle.volume or 0.0), today_cum=today_cum)

    @staticmethod
    def _candle_vwap(st: SymbolState):
        # OHLC typical-price approximation; price is approximate, not quote-level true VWAP.
        bars = sorted(st.completed.values(), key=lambda x: x.at)
        denominator = sum(c.volume for c in bars)
        return (sum(((c.high + c.low + c.close) / 3) * c.volume for c in bars)
                / denominator) if denominator else None

    def _score(self, st: SymbolState, distance: float) -> int:
        cfg = self.config
        proximity = max(0, 30 * (1 - max(0.0, distance) / cfg['near_boundary_pct']))
        # Volume term, normalised to the ACTIVE RVOL metric's confirm threshold so the 0-30 points mean
        # the same thing in either mode. (The old hardcoded /1.5 + cap 3.0 was the per-bar confirm scale;
        # on the now-default cumulative metric — which sits ~1.0-1.3, not 1.5-3.0 — it scored volume
        # ~2-3x too low and under-ranked genuinely heavy stocks.) confirm points → 14, 2x → the 30 cap;
        # for per_bar (confirm 1.5) this is identical to the previous formula.
        _cfm = self.rvol_th.get('confirm') or 1.5
        volume = min(30, 14 * min(st.rvol or 0, 2 * _cfm) / _cfm)
        liquidity = min(20, st.info.median_turnover_cr / 100 * 20)
        momentum = 12 if (st.last_tick and st.vwap and
                          ((st.last_tick.price >= st.vwap) == (st.side == 'LONG'))) else 0
        width = (8 if st.opening and 0.25 <=
                 (st.opening.high - st.opening.low) / st.opening.open * 100 <= 1.8 else 2)
        return int(min(100, round(proximity + volume + liquidity + momentum + width)))

    def _in_or_window(self, candle: Candle) -> bool:
        start = market_dt(self.session, self.config['open_range_start'])
        return start <= candle.at < start + timedelta(minutes=self.or_minutes)

    def _build_opening(self, st: SymbolState) -> Candle | None:
        """Merge the opening-range bars into the one candle the rules are written against.

        Returns None until every bar of the window has arrived. A range built from four of five
        minutes can understate the high or the low, and those two numbers set every breakout,
        retest and stop for the rest of the day — so an incomplete range yields no signals at all,
        which is the safe way to be wrong.
        """
        if len(st.or_bars) < self.or_bar_count:
            return None
        bars = [st.or_bars[k] for k in sorted(st.or_bars)]
        return Candle(at=bars[0].at, open=bars[0].open,
                      high=max(b.high for b in bars), low=min(b.low for b in bars),
                      close=bars[-1].close, volume=sum(b.volume for b in bars))

    def ingest_live_bar(self, symbol: str, candle: Candle,
                        observed_at: datetime | None = None):
        """Feed a websocket-aggregated 5m candle as a PROVISIONAL bar (realtime path).

        Provisional confirmations/retests fire ~1s after a bar closes and are later
        reconciled (validated or retracted) by the authoritative FYERS history bar.
        """
        self.ingest_closed_bar(symbol, candle, observed_at=observed_at, provisional=True)

    def is_provisional(self, symbol: str, ts: int) -> bool:
        with self.lock:
            st = self.states.get(symbol)
            return bool(st and ts in st.provisional_ts)

    def _confirm_test(self, st: SymbolState, prev, candle: Candle):
        """Pure breakout gate, shared by live confirmation and REST reconciliation.

        Returns (side, level, extension, ok, reason). side/level/extension are set
        whenever a boundary close occurred (even if a later gate fails); ok is True
        only when every gate passes. side is None when no boundary close happened.
        """
        op = st.opening
        width = (op.high - op.low) / op.open * 100
        if not (self.config['min_open_range_width_pct'] <= width <=
                self.config['max_open_range_width_pct']):
            return None, None, None, False, 'Opening range width out of configured range'
        if prev is None:
            return (None, None, None, False,
                    f'Missing previous {self.bar_minutes}-minute candle; cannot confirm breakout')
        for side, passed, level, extension in (
            ('LONG', prev.close <= op.high and candle.close > op.high,
             op.high, (candle.close - op.high) / op.high * 100),
            ('SHORT', prev.close >= op.low and candle.close < op.low,
             op.low, (op.low - candle.close) / op.low * 100)
        ):
            if not passed:
                continue
            if extension > self.config['max_extension_pct']:
                return side, level, extension, False, 'Breakout closed too far beyond OR boundary (extended)'
            if not st.rvol or st.rvol < self.rvol_th['confirm']:
                return side, level, extension, False, 'Breakout closed with insufficient historical RVOL'
            if candle.close * candle.volume / 1e7 < self._min_bar_turnover_cr():
                return (side, level, extension, False,
                        f'Insufficient {self.bar_minutes}-minute traded value')
            if st.vwap is None or ((side == 'LONG') != (candle.close > st.vwap)):
                return (side, level, extension, False,
                        f'Breakout not aligned with {self.bar_minutes}-minute OHLC-derived VWAP proxy')
            return (side, level, extension, True,
                    f'Completed {self.bar_minutes}m close beyond OR + RVOL + VWAP; waiting for retest')
        return None, None, None, False, 'No completed close beyond opening range'

    def _min_bar_turnover_cr(self) -> float:
        """Per-bar traded-value floor, scaled to the bar being measured.

        `min_bar_turnover_cr` is calibrated against a 5-minute bar. A 1-minute bar carries roughly
        a fifth of the turnover, so applying the raw figure would reject nearly every breakout and
        the 1-minute setting would look broken rather than merely stricter.
        """
        return self.config['min_bar_turnover_cr'] * self.bar_minutes / 5

    def _breakout_levels(self, st: SymbolState, op, entry: float, side: str,
                         ref_low: float, ref_high: float):
        """Stop / nearest prior-session target / net-R:R for an entry at `entry`. Shared by the retest
        entry and the aggressive CONFIRMED (breakout) entry so both price the trade identically.
        `ref_low`/`ref_high` are the signal candle's wick (the retest candle, or the confirming candle
        for a breakout entry).

        Stop placement (orb_stop_mode):
          'atr_floor': stop beyond the OR level and the signal wick, WIDENED to at least atr_mult ×
              daily ATR so it isn't a sub-0.2% hair-trigger noise takes out. Risk = max(structure
              distance, atr_mult × ATR). On a nearby target the wide risk can drop net R:R under the
              gate (setup then hidden / not entered).
          'structure': stop at the structural level only (just beyond the OR level / wick), no ATR
              widening — the way a discretionary trader places it. Tighter risk, better R:R, more
              exposed to noise. ATR is still the fallback when there's no structural level.
        The struct buffer (orb_struct_buffer_pct, default 0.10%) is how far beyond the OR level the
        stop sits; the wick buffer tracks at half of it, preserving the original 2:1 ratio."""
        atr_mult = self.config.get('intraday_atr_stop_mult', 0.5)
        stop_mode = self.config.get('orb_stop_mode', 'atr_floor')
        struct_buf = (self.config.get('orb_struct_buffer_pct', 0.10) or 0.10) / 100.0
        wick_buf = struct_buf / 2.0
        atr_dist = entry * (st.info.daily_atr_pct or 0) / 100 * atr_mult
        if side == 'LONG':
            struct_stop = min(op.high * (1 - struct_buf), ref_low * (1 - wick_buf))
            stop = struct_stop if stop_mode == 'structure' else (
                min(struct_stop, entry - atr_dist) if atr_dist else struct_stop)
            targets = sorted(x for x in st.info.resistance if x > entry * 1.001)
        else:
            struct_stop = max(op.low * (1 + struct_buf), ref_high * (1 + wick_buf))
            stop = struct_stop if stop_mode == 'structure' else (
                max(struct_stop, entry + atr_dist) if atr_dist else struct_stop)
            targets = sorted((x for x in st.info.support if x < entry * 0.999), reverse=True)
        target = targets[0] if targets else None
        rr = None
        if target:
            cost = entry * self.config['estimated_roundtrip_cost_pct'] / 100
            reward = ((target - entry) if side == 'LONG' else (entry - target)) - cost
            risk = abs(entry - stop) + cost
            if risk > 0:
                rr = reward / risk
        return stop, target, rr

    def _attach_breakout_ticket(self, st: SymbolState, side: str, candle: Candle):
        """Price the breakout (CONFIRMED) entry itself and attach it to the state, so auto-trade with
        trigger=CONFIRMED can enter on the breakout instead of only on a later retest. Entry is the
        confirming close; stop/target/net-R:R come from the shared pricing. Gated by the SAME net-R:R
        floor as the retest: if the breakout entry doesn't clear it (or there's no prior-session
        target), the ticket is left UNSET and the signal simply waits for a tighter-risk retest entry
        — exactly the pre-fix behaviour for those breakouts. Idempotent: safe to re-run when an
        authoritative bar validates a provisional confirmation (re-prices off the authoritative bar)."""
        op = st.opening
        if op is None:
            st.entry = st.stop = st.target = st.net_rr = None
            return
        entry = candle.close
        stop, target, rr = self._breakout_levels(st, op, entry, side, candle.low, candle.high)
        if rr is not None and rr >= self.config['min_net_reward_risk']:
            st.entry, st.stop, st.target, st.net_rr = entry, stop, target, rr
        else:
            st.entry = st.stop = st.target = st.net_rr = None

    def _apply_confirmation(self, st: SymbolState, side: str, level: float,
                            candle: Candle, ts: int, provisional: bool):
        st.state, st.confirmed_side = 'CONFIRMED', side
        st.confirmed_at = candle.at + self.bar_delta
        st.confirmed_low, st.confirmed_high = candle.low, candle.high
        st.confirm_bar_ts = ts
        st.confirm_provisional = provisional
        st.score = max(st.score, 65)
        st.reason = (('PROVISIONAL (live) — ' if provisional else '') +
                     f'Completed {self.bar_minutes}m close beyond OR + RVOL + VWAP; '
                     'waiting for retest')
        # Attach a breakout-entry ticket so trigger=CONFIRMED can enter on the breakout itself (was a
        # no-op before: CONFIRMED carried no entry/stop and the order engine skipped it). Gated by the
        # same net-R:R floor; set BEFORE the event so the CONFIRMED signal is recorded with its ticket.
        self._attach_breakout_ticket(st, side, candle)
        self._event(st, 'CONFIRMED', st.confirmed_at, st.reason, level, provisional=provisional)

    def _retract(self, st: SymbolState, candle: Candle, reason: str):
        """Stand down: an authoritative bar did not confirm a live-provisional signal."""
        level = (st.opening.high if st.confirmed_side == 'LONG' else st.opening.low) if st.opening else 0
        st.side = st.confirmed_side or st.side
        st.state = 'RETRACTED'
        st.score = 0
        st.reason = reason
        st.confirmed_at = None
        st.confirmed_side = ''
        st.confirm_provisional = False
        st.retest_provisional = False
        st.entry = st.stop = st.target = st.net_rr = None
        self._event(st, 'RETRACTED', candle.at + self.bar_delta, reason, level or 0)

    def _reconcile(self, st: SymbolState, candle: Candle, ts: int, prev, wall: datetime):
        """Authoritative candle replacing a provisional bar: validate or retract."""
        st.rvol = self._rvol(st, candle)
        st.vwap = self._candle_vwap(st)
        if ts == st.confirm_bar_ts and st.confirm_provisional:
            side, level, extension, ok, reason = self._confirm_test(st, prev, candle)
            if ok and side == st.confirmed_side:
                st.confirm_provisional = False
                st.reason = (f'Breakout validated by authoritative FYERS {self.bar_minutes}m '
                             'candle; waiting for retest')
                # Re-price the breakout ticket off the authoritative bar: only now (non-provisional)
                # will trigger=CONFIRMED actually enter, so the entry/stop must reflect real data.
                self._attach_breakout_ticket(st, st.confirmed_side, candle)
                return
            self._retract(st, candle,
                          'Provisional breakout not confirmed by authoritative data: ' + reason)
            return
        if ts == st.retest_bar_ts and st.retest_provisional and st.confirmed_at:
            # Re-run the retest on the authoritative bar; it may validate or overturn it.
            st.state = 'CONFIRMED'
            st.retest_provisional = False
            self._evaluate_retest(st, candle, wall, provisional=False)
            return
        if st.confirmed_at and st.state not in (
                'RETEST_READY', 'RISK_FAIL', 'FAILED', 'EXPIRED', 'RETRACTED'):
            self._evaluate_retest(st, candle, wall, provisional=False)

    def ingest_closed_bar(self, symbol: str, candle: Candle,
                          observed_at: datetime | None = None, provisional: bool = False):
        """Ingest a COMPLETED 5m candle.

        provisional=False: authoritative FYERS history candle — the source of truth.
        provisional=True: live candle aggregated from the websocket tick stream, used
        to confirm breakouts ~1s after bar close; always reconciled later. The opening
        range is NEVER anchored from a provisional bar.
        """
        with self.lock:
            if self.halted:
                return
            st = self.states.get(symbol)
            if st is None or candle.at.date() != self.session:
                return
            wall = observed_at or now_ist()
            if candle.at + self.bar_delta > wall:
                # Explicit guard against future/partially completed candles.
                return
            # Session candle window — config-driven so non-standard sessions work (e.g. the practice
            # simulation can run an evening window). Defaults to the normal NSE day.
            _sess_open = self.config.get('session_open') or self.config.get('open_range_start') or '09:15'
            _sess_close = self.config.get('session_close') or '15:30'
            if not (market_dt(self.session, _sess_open) <= candle.at < market_dt(self.session, _sess_close)):
                return
            ts = int(candle.at.timestamp())
            is_or = self._in_or_window(candle)
            if is_or and provisional:
                return  # opening range must be authoritative; wait for REST history
            existing = ts in st.completed
            if existing and not (ts in st.provisional_ts and not provisional):
                # Already stored, and this is not an authoritative reconciliation.
                return
            # If bar feed is discontinuous, don't silently confirm a transition.
            prev = st.completed.get(ts - self.bar_seconds)
            st.completed[ts] = candle
            if provisional:
                st.provisional_ts.add(ts)
            else:
                st.provisional_ts.discard(ts)
            if is_or:
                st.or_bars[ts] = candle
                opening = self._build_opening(st)
                if opening is None:
                    st.state = 'WAIT_OR'
                    st.reason = (f'Opening range forming: {len(st.or_bars)}/{self.or_bar_count} '
                                 f'{self.bar_minutes}m bars of {self.or_minutes}m window received')
                    return
                st.opening = opening
                st.state = 'NO_SETUP'
                st.reason = (f'Opening range finalized from {self.or_bar_count} authoritative '
                             f'{self.bar_minutes}m candle(s)')
                return
            if st.opening is None:
                return
            # Authoritative bar replacing a provisional one -> reconcile and stop.
            if not provisional and existing:
                if self.mode == 'LIVE' and (st.last_tick is None or
                        (wall - st.last_tick.time).total_seconds() >
                        self.config['market_feed_stale_seconds']):
                    st.reason = 'FYERS market feed stale; defer reconciliation'
                    return
                self._reconcile(st, candle, ts, prev, wall)
                return
            if st.state in ('RETEST_READY', 'RISK_FAIL', 'FAILED', 'EXPIRED',
                            'RETRACTED', 'SESSION_CONSUMED'):
                return
            if not (market_dt(self.session, self.config['watch_start']) <= candle.at <
                    market_dt(self.session, self.config['new_signals_stop'])):
                # A confirmed breakout just before the cutoff may retest shortly after.
                if not (st.confirmed_at is not None and
                        candle.at < market_dt(self.session, self.config['new_signals_stop']) +
                        timedelta(minutes=self.config['retest_expiry_minutes'])):
                    return
            st.rvol = self._rvol(st, candle)
            st.vwap = self._candle_vwap(st)
            if st.confirmed_at:
                if self.mode == 'LIVE' and (st.last_tick is None or
                        (wall - st.last_tick.time).total_seconds() >
                        self.config['market_feed_stale_seconds']):
                    st.reason = 'FYERS market feed stale; refuse retest evaluation'
                    return
                self._evaluate_retest(st, candle, wall, provisional=provisional)
                return
            if prev is None:
                st.reason = (f'Missing previous {self.bar_minutes}-minute candle; '
                             'cannot confirm breakout')
                return
            if self.mode == 'LIVE' and (st.last_tick is None or
                    (wall - st.last_tick.time).total_seconds() >
                    self.config['market_feed_stale_seconds']):
                st.reason = 'FYERS market feed stale; refuse new confirmation'
                return
            side, level, extension, ok, reason = self._confirm_test(st, prev, candle)
            if side is None:
                return  # no boundary close (or width out of range): unchanged, as before
            st.side = side
            st.distance_pct = -round(extension, 3)
            st.reason = reason
            if not ok:
                return
            self._apply_confirmation(st, side, level, candle, ts, provisional)

    def _evaluate_retest(self, st: SymbolState, c: Candle, now: datetime,
                         provisional: bool = False):
        if st.state in ('RETEST_READY', 'FAILED', 'EXPIRED', 'RISK_FAIL'):
            return
        op = st.opening
        assert op is not None
        st.retest_bar_ts = int(c.at.timestamp())
        st.retest_provisional = provisional
        prov_tag = 'PROVISIONAL (live) — ' if provisional else ''
        age = (c.at + self.bar_delta - st.confirmed_at).total_seconds() / 60
        if age > self.config['retest_expiry_minutes']:
            st.state, st.reason = 'EXPIRED', 'No clean retest in allowed window'
            self._event(st, 'EXPIRED', c.at + self.bar_delta, st.reason,
                        op.high if st.confirmed_side == 'LONG' else op.low,
                        provisional=provisional)
            return
        tol = self.config['retest_tolerance_pct'] / 100
        if st.confirmed_side == 'LONG':
            if c.close < op.high * (1 - tol):
                st.state, st.reason = 'FAILED', 'Retest candle closed below ORH support'
                self._event(st, 'FAILED', c.at + self.bar_delta, st.reason, op.high,
                            provisional=provisional)
                return
            retest_ok = c.low <= op.high * (1 + tol) and c.close >= op.high
        else:
            if c.close > op.low * (1 + tol):
                st.state, st.reason = 'FAILED', 'Retest candle closed above ORL resistance'
                self._event(st, 'FAILED', c.at + self.bar_delta, st.reason, op.low,
                            provisional=provisional)
                return
            retest_ok = c.high >= op.low * (1 - tol) and c.close <= op.low
        if not retest_ok:
            return
        entry = c.close
        # Retest enters at the OR level; stop / nearest prior-session target / net-R:R are priced by the
        # shared helper (orb_stop_mode honoured) — the identical math the aggressive CONFIRMED entry uses.
        stop, target, rr = self._breakout_levels(st, op, entry, st.confirmed_side, c.low, c.high)
        st.entry, st.stop, st.target, st.net_rr = entry, stop, target, rr
        if rr is None or rr < self.config['min_net_reward_risk']:
            st.state = 'RISK_FAIL'
            st.reason = (prov_tag + ('No known prior-session target above/below entry'
                         if rr is None else f'Nearest-target net R:R {rr:.2f} < 2.0'))
        else:
            st.state = 'RETEST_READY'
            st.reason = (prov_tag + f'Price retested OR, nearest prior-session target supports '
                         f'net {rr:.2f}:1 (ESTIMATE ONLY). Check MIS, spreads, resistance.')
        st.side = st.confirmed_side
        st.score = max(st.score, 80 if st.state == 'RETEST_READY' else 40)
        self._event(st, st.state, c.at + self.bar_delta, st.reason,
                    op.high if st.side == 'LONG' else op.low, provisional=provisional)

    def needs_verification(self, symbol: str) -> bool:
        with self.lock:
            st = self.states[symbol]
            if not st.opening or not st.last_tick or st.stale or st.state == 'SESSION_CONSUMED':
                return False
            if self.mode == 'LIVE' and (now_ist() - st.last_tick.time).total_seconds() > \
                    self.config['market_feed_stale_seconds']:
                return False
            if st.confirmed_at and st.state not in ('RETEST_READY', 'FAILED', 'EXPIRED', 'RISK_FAIL'):
                return True
            p = st.last_tick.price
            buf = self.config['near_boundary_pct'] * 2 / 100
            return ((abs(p - st.opening.high) / st.opening.high <= buf) or
                    (abs(p - st.opening.low) / st.opening.low <= buf))

    def pending_reconcile(self, symbol: str) -> bool:
        """Symbols REST reconciliation must re-fetch this cycle: those with a FIRED-but-unvalidated
        provisional breakout/retest signal, or a confirmed setup still tracking toward its retest.

        Deliberately NARROWER than needs_verification (which returns True for ANY symbol merely within
        ~0.7% of its opening range — most of the universe, most of the day). A breakout is always
        detected first by the websocket (ingest_live_bar fires the PROVISIONAL signal and sets
        confirm_provisional/retest_provisional); REST only validates it afterwards. So a near-boundary
        symbol with no fired provisional has nothing to validate — and the moment it breaks out on the
        websocket it re-enters this set. This keeps REST spend proportional to real signals, not to the
        ~80 symbols/bar that just hover near their range (which is what exhausted the daily budget)."""
        with self.lock:
            st = self.states.get(symbol)
            if st is None or not st.opening or st.state == 'SESSION_CONSUMED':
                return False
            if st.confirm_provisional or st.retest_provisional:
                return True                                  # a fired provisional awaiting validation
            if st.confirmed_at and st.state not in ('RETEST_READY', 'FAILED', 'EXPIRED', 'RISK_FAIL'):
                return True                                  # confirmed, tracking toward the retest
            return False

    def _ticket_size(self, st: SymbolState) -> dict:
        """Suggested qty + rupee risk for the full ticket (manual trade; no auto-orders)."""
        if not st.entry or not st.stop:
            return {'qty': None, 'risk_budget': None, 'risk_amount': None}
        s = position_size(st.entry, st.stop, self.config.get('capital_inr', 0),
                          self.config.get('risk_pct', 0))
        return {'qty': s['qty'] or None, 'risk_budget': s['risk_budget'],
                'risk_amount': s['actual_risk']}

    def replay(self, symbol: str) -> dict:
        """One symbol's whole session, bar by bar: completed candles plus every state transition
        with the reasoning behind it.

        This is the trade debugger's data source. The scrubber replays the session so a user can
        see exactly what the engine saw at the moment it fired — or refused to. Events carry an
        epoch `t` so the UI can align them to the bar that produced them; provisional bars are
        flagged so a retraction reads as 'this bar was live-only and the authoritative one
        disagreed' rather than an unexplained reversal.
        """
        with self.lock:
            st = self.states.get(symbol)
            if st is None:
                return {}
            bars = sorted(st.completed.values(), key=lambda c: c.at)
            candles = [{'t': int(c.at.timestamp()), 'open': c.open, 'high': c.high, 'low': c.low,
                        'close': c.close, 'volume': c.volume,
                        'provisional': int(c.at.timestamp()) in st.provisional_ts}
                       for c in bars]
            events = []
            for e in self.events:
                if e.symbol != symbol:
                    continue
                try:
                    at = datetime.strptime(e.time, '%Y-%m-%d %H:%M:%S').replace(tzinfo=IST)
                except ValueError:
                    continue   # a malformed restored row must not break the whole replay
                events.append({**asdict(e), 't': int(at.timestamp())})
            events.sort(key=lambda e: e['t'])
            op = st.opening
            # Is this session still producing bars? The UI polls to follow along live, and must
            # stop once the day is done rather than re-fetching an unchanging payload forever.
            # One bar of slack past the close so the final bar's reconciliation still arrives.
            sess_close = self.config.get('session_close') or '15:30'
            wall = now_ist()
            live = (wall.date() == self.session and
                    wall < market_dt(self.session, sess_close) + self.bar_delta)
            return {
                'symbol': symbol, 'session': self.session.isoformat(), 'mode': self.mode,
                'live': live,
                'opening': ({'t': int(op.at.timestamp()), 'high': round(op.high, 2),
                             'low': round(op.low, 2), 'minutes': self.or_minutes} if op else None),
                'candles': candles, 'events': events,
                'final': {'state': st.state, 'side': st.side, 'score': st.score,
                          'reason': st.reason, 'entry': st.entry, 'stop': st.stop,
                          'target': st.target,
                          'net_rr': round(st.net_rr, 2) if st.net_rr is not None else None},
                'info': {'industry': st.info.industry, 'atr_pct': st.info.daily_atr_pct,
                         'turnover_cr': st.info.median_turnover_cr},
                'bar_minutes': self.bar_minutes,
            }

    def snapshot(self, reference_time: datetime | None = None):
        with self.lock:
            now = (reference_time or now_ist()).astimezone(IST)
            rows = []
            for st in self.states.values():
                t = st.last_tick
                stale = (t is None or
                         (self.mode == 'LIVE' and
                          (now - t.time).total_seconds() > self.config['market_feed_stale_seconds']))

                # Determine visible state (for filtering/priority)
                if self.halted:
                    visible = 'HALTED'
                elif st.state == 'SESSION_CLOSED':
                    visible = 'SESSION_CLOSED'
                elif stale and self.mode == 'LIVE':
                    visible = 'STALE' if st.opening else st.state
                else:
                    # Keep the actual state (don't change RETEST_READY to SIGNAL_AGED)
                    visible = st.state

                # Calculate entry status for smart display
                entry_status = None
                signal_age_sec = None
                if st.last_signal_time is not None:
                    signal_age_sec = round((now - st.last_signal_time).total_seconds())

                # For RETEST_READY signals, provide contextual status based on age
                if st.state == 'RETEST_READY' and signal_age_sec is not None:
                    if signal_age_sec <= 120:  # 0-2 minutes: Fresh
                        entry_status = 'fresh'
                    elif signal_age_sec <= 300:  # 2-5 minutes: Aging
                        entry_status = 'aging'
                    else:  # >5 minutes: Entry window closed
                        entry_status = 'aged'
                rows.append({
                    'symbol': st.info.symbol, 'source': st.info.source,
                    'state': visible, 'underlying_state': st.state,
                    'side': st.side, 'score': st.score,
                    'price': round(t.price, 2) if t else None,
                    'orh': round(st.opening.high, 2) if st.opening else None,
                    'orl': round(st.opening.low, 2) if st.opening else None,
                    'rvol': round(st.rvol, 2) if st.rvol is not None else None,
                    'vwap_proxy': round(st.vwap, 2) if st.vwap else None,
                    'distance_pct': st.distance_pct,
                    'turnover_cr': st.info.median_turnover_cr,
                    'last_tick_ist': t.time.strftime('%H:%M:%S') if t else None,
                    'reason': st.reason, 'entry': st.entry, 'stop': st.stop,
                    'target': st.target, 'net_rr': round(st.net_rr, 2) if st.net_rr else None,
                    'stale': bool(stale),
                    'provisional': bool(st.confirm_provisional or st.retest_provisional),
                    # Seconds since this state was reached (uses the engine's own clock, so it's
                    # correct in both LIVE and accelerated SIMULATION time). Lets the alert dispatcher
                    # skip a stale CONFIRMED that has sat on the radar for hours.
                    'signal_age_sec': signal_age_sec,
                    # Entry status for smart display: 'fresh' (0-2m), 'aging' (2-5m), 'aged' (>5m), or None
                    'entry_status': entry_status,
                    **self._ticket_size(st)
                })
            priority = {'RETEST_READY': 0, 'CONFIRMED': 1, 'BREAKOUT_PENDING': 2,
                        'READY': 3, 'WATCH': 4, 'RISK_FAIL': 5, 'FAILED': 6}
            # An unchanged persistent state after the configured cutoff is not
            # a current actionable opportunity, even with a recent websocket tick.
            if self.mode == 'LIVE' and now > market_dt(self.session, self.config['new_signals_stop']) + timedelta(
                    minutes=self.config['retest_expiry_minutes']):
                priority = {}
            actionable = [r for r in rows if r['state'] in priority and not r['stale']]
            actionable.sort(key=lambda r: (priority[r['state']], -r['score']))
            counts = defaultdict(int)
            for r in rows:
                counts[r['state']] += 1
            return {'mode': self.mode, 'session': self.session.isoformat(),
                    'server_time_ist': now.strftime('%Y-%m-%d %H:%M:%S'),
                    'feed_health': self.feed_health, 'halted': self.halted,
                    'new_signals_stop': self.config['new_signals_stop'],
                    'session_closed': self.mode in ('LIVE', 'SIMULATION') and now >= market_dt(self.session, self.config['new_signals_stop']) + timedelta(minutes=self.config['retest_expiry_minutes']),
                    'monitored': len(rows),
                    'morning_monitored': sum(r['source'] == 'MORNING' for r in rows),
                    'received_ticks': sum(bool(st.last_tick) for st in self.states.values()),
                    'anchors_ready': sum(bool(st.opening) for st in self.states.values()),
                    'baselines_ready': sum(baseline_has_data(self.baselines.get(s), self.rvol_cfg.mode)
                                           for s in self.states),
                    'active_candidates': len(actionable),
                    'counts': dict(counts), 'top5': actionable[:5],
                    'all': sorted(rows, key=lambda r: (-r['score'], r['symbol'])),
                    'events': [asdict(e) for e in sorted(self.events[-150:],
                                                          key=lambda e: e.time, reverse=True)],
                    'notes': self.notes[:10]}
