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
from .utils import IST, bar_start, market_dt, now_ist


SIGNAL_STATES = {'WATCH', 'READY', 'BREAKOUT_PENDING', 'CONFIRMED',
                 'RETEST_CANDIDATE', 'RETEST_READY', 'RISK_FAIL', 'FAILED',
                 'EXPIRED', 'RETRACTED'}
PERSISTENT_STATES = {'CONFIRMED', 'RETEST_CANDIDATE', 'RETEST_READY',
                     'RISK_FAIL', 'FAILED', 'EXPIRED', 'RETRACTED', 'SESSION_CONSUMED'}


def same_time_baseline(history: list[Candle], cutoff: date, lookback_sessions: int = 20):
    """Median volume of the corresponding 5-minute interval from previous sessions."""
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
        self.lock = threading.RLock()
        self.states = {info.symbol: SymbolState(info) for info in instruments}
        self.baselines: dict[str, dict[str, float]] = {}
        self.events: list[Signal] = []
        self.on_signal = on_signal
        self.feed_health = 'DISCONNECTED' if mode == 'LIVE' else 'SIMULATED'
        self.halted = False
        self.notes: list[str] = []

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
            # After laptop sleep/restart a historical 5m bar may be hours old.
            # Suppress WATCH/READY until a recent authoritative completed bar exists.
            # An unfinished websocket tick is not a substitute for volume history.
            last = max(st.completed.values(), key=lambda x: x.at)
            if (self.mode == 'LIVE' and
                (current_time - (last.at + timedelta(minutes=5))).total_seconds() > 600):
                st.state, st.reason, st.score = (
                    'RECOVERING', 'Waiting for recent completed 5-minute candle after restart', 0)
                return
            st.rvol = self._rvol(t.symbol, last)
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
            if not options or st.rvol < self.config['min_watch_rvol']:
                st.state, st.reason, st.score = 'NONE', 'No active qualifying approach', 0
                return
            side, distance, level, _ = min(options, key=lambda x: abs(x[1]))
            st.side, st.distance_pct = side, round(distance, 3)
            st.score = self._score(st, distance)
            if distance < 0:
                next_state = 'BREAKOUT_PENDING'
                st.reason = 'Intrabar breach; wait for complete 5-minute close'
            elif distance <= self.config['ready_boundary_pct'] and st.rvol >= 1.25:
                next_state = 'READY'
                st.reason = 'Near OR boundary; VWAP aligned and volume improving'
            else:
                next_state = 'WATCH'
                st.reason = 'Approaching OR boundary; breakout not yet confirmed'
            if next_state != st.state:
                st.state = next_state
                self._event(st, next_state, t.time, st.reason, level)

    def _rvol(self, symbol: str, candle: Candle):
        baseline = self.baselines.get(symbol, {}).get(candle.at.strftime('%H:%M'))
        if not baseline or baseline <= 0:
            return None
        return candle.volume / baseline

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
        volume = min(30, 14 * min(st.rvol or 0, 3.0) / 1.5)
        liquidity = min(20, st.info.median_turnover_cr / 100 * 20)
        momentum = 12 if (st.last_tick and st.vwap and
                          ((st.last_tick.price >= st.vwap) == (st.side == 'LONG'))) else 0
        width = (8 if st.opening and 0.25 <=
                 (st.opening.high - st.opening.low) / st.opening.open * 100 <= 1.8 else 2)
        return int(min(100, round(proximity + volume + liquidity + momentum + width)))

    def _recent_opening(self, candle: Candle) -> bool:
        return candle.at == market_dt(self.session, self.config['open_range_start'])

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
            return None, None, None, False, 'Missing previous 5-minute candle; cannot confirm breakout'
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
            if not st.rvol or st.rvol < self.config['min_confirm_rvol']:
                return side, level, extension, False, 'Breakout closed with insufficient same-time historical RVOL'
            if candle.close * candle.volume / 1e7 < self.config['min_bar_turnover_cr']:
                return side, level, extension, False, 'Insufficient 5-minute traded value'
            if st.vwap is None or ((side == 'LONG') != (candle.close > st.vwap)):
                return side, level, extension, False, 'Breakout not aligned with 5-minute OHLC-derived VWAP proxy'
            return side, level, extension, True, 'Completed 5m close beyond OR + RVOL + VWAP; waiting for retest'
        return None, None, None, False, 'No completed close beyond opening range'

    def _apply_confirmation(self, st: SymbolState, side: str, level: float,
                            candle: Candle, ts: int, provisional: bool):
        st.state, st.confirmed_side = 'CONFIRMED', side
        st.confirmed_at = candle.at + timedelta(minutes=5)
        st.confirmed_low, st.confirmed_high = candle.low, candle.high
        st.confirm_bar_ts = ts
        st.confirm_provisional = provisional
        st.score = max(st.score, 65)
        st.reason = (('PROVISIONAL (live) — ' if provisional else '') +
                     'Completed 5m close beyond OR + RVOL + VWAP; waiting for retest')
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
        self._event(st, 'RETRACTED', candle.at + timedelta(minutes=5), reason, level or 0)

    def _reconcile(self, st: SymbolState, candle: Candle, ts: int, prev, wall: datetime):
        """Authoritative candle replacing a provisional bar: validate or retract."""
        st.rvol = self._rvol(st.info.symbol, candle)
        st.vwap = self._candle_vwap(st)
        if ts == st.confirm_bar_ts and st.confirm_provisional:
            side, level, extension, ok, reason = self._confirm_test(st, prev, candle)
            if ok and side == st.confirmed_side:
                st.confirm_provisional = False
                st.reason = 'Breakout validated by authoritative FYERS 5m candle; waiting for retest'
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
            if candle.at + timedelta(minutes=5) > wall:
                # Explicit guard against future/partially completed candles.
                return
            if not (market_dt(self.session, '09:15') <= candle.at < market_dt(self.session, '15:30')):
                return
            ts = int(candle.at.timestamp())
            is_or = self._recent_opening(candle)
            if is_or and provisional:
                return  # opening range must be authoritative; wait for REST history
            existing = ts in st.completed
            if existing and not (ts in st.provisional_ts and not provisional):
                # Already stored, and this is not an authoritative reconciliation.
                return
            # If bar feed is discontinuous, don't silently confirm a transition.
            prev = st.completed.get(ts - 300)
            st.completed[ts] = candle
            if provisional:
                st.provisional_ts.add(ts)
            else:
                st.provisional_ts.discard(ts)
            if is_or:
                st.opening = candle
                st.state = 'NO_SETUP'
                st.reason = 'Opening range finalized from FYERS historical 5m candle'
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
            st.rvol = self._rvol(symbol, candle)
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
                st.reason = 'Missing previous 5-minute candle; cannot confirm breakout'
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
        age = (c.at + timedelta(minutes=5) - st.confirmed_at).total_seconds() / 60
        if age > self.config['retest_expiry_minutes']:
            st.state, st.reason = 'EXPIRED', 'No clean retest in allowed window'
            self._event(st, 'EXPIRED', c.at + timedelta(minutes=5), st.reason,
                        op.high if st.confirmed_side == 'LONG' else op.low,
                        provisional=provisional)
            return
        tol = self.config['retest_tolerance_pct'] / 100
        if st.confirmed_side == 'LONG':
            if c.close < op.high * (1 - tol):
                st.state, st.reason = 'FAILED', 'Retest candle closed below ORH support'
                self._event(st, 'FAILED', c.at + timedelta(minutes=5), st.reason, op.high,
                            provisional=provisional)
                return
            retest_ok = c.low <= op.high * (1 + tol) and c.close >= op.high
        else:
            if c.close > op.low * (1 + tol):
                st.state, st.reason = 'FAILED', 'Retest candle closed above ORL resistance'
                self._event(st, 'FAILED', c.at + timedelta(minutes=5), st.reason, op.low,
                            provisional=provisional)
                return
            retest_ok = c.high >= op.low * (1 - tol) and c.close <= op.low
        if not retest_ok:
            return
        entry = c.close
        # Stop beyond both OR level and retest wick; avoid arbitrary tiny risk.
        if st.confirmed_side == 'LONG':
            stop = min(op.high * (1 - 0.001), c.low * (1 - 0.0005))
            targets = sorted(x for x in st.info.resistance if x > entry * 1.001)
        else:
            stop = max(op.low * (1 + 0.001), c.high * (1 + 0.0005))
            targets = sorted((x for x in st.info.support if x < entry * 0.999), reverse=True)
        target = targets[0] if targets else None
        rr = None
        if target:
            cost = entry * self.config['estimated_roundtrip_cost_pct'] / 100
            directional_reward = ((target - entry) if st.confirmed_side == 'LONG'
                                  else (entry - target)) - cost
            directional_risk = (abs(entry - stop) + cost)
            if directional_risk > 0:
                rr = directional_reward / directional_risk
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
        self._event(st, st.state, c.at + timedelta(minutes=5), st.reason,
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

    def _ticket_size(self, st: SymbolState) -> dict:
        """Suggested qty + rupee risk for the full ticket (manual trade; no auto-orders)."""
        if not st.entry or not st.stop:
            return {'qty': None, 'risk_budget': None, 'risk_amount': None}
        s = position_size(st.entry, st.stop, self.config.get('capital_inr', 0),
                          self.config.get('risk_pct', 0))
        return {'qty': s['qty'] or None, 'risk_budget': s['risk_budget'],
                'risk_amount': s['actual_risk']}

    def snapshot(self, reference_time: datetime | None = None):
        with self.lock:
            now = (reference_time or now_ist()).astimezone(IST)
            rows = []
            for st in self.states.values():
                t = st.last_tick
                stale = (t is None or
                         (self.mode == 'LIVE' and
                          (now - t.time).total_seconds() > self.config['market_feed_stale_seconds']))
                if self.halted:
                    visible = 'HALTED'
                elif st.state == 'SESSION_CLOSED':
                    visible = 'SESSION_CLOSED'
                elif stale and self.mode == 'LIVE':
                    visible = 'STALE' if st.opening else st.state
                elif (self.mode == 'LIVE' and st.state == 'RETEST_READY' and
                      st.last_signal_time is not None and
                      (now - st.last_signal_time).total_seconds() > 300):
                    visible = 'SIGNAL_AGED'  # 5-min old retest isn't a fresh entry
                else:
                    visible = st.state
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
                    'baselines_ready': sum(bool(self.baselines.get(s)) for s in self.states),
                    'active_candidates': len(actionable),
                    'counts': dict(counts), 'top5': actionable[:5],
                    'all': sorted(rows, key=lambda r: (-r['score'], r['symbol'])),
                    'events': [asdict(e) for e in sorted(self.events[-150:],
                                                          key=lambda e: e.time, reverse=True)],
                    'notes': self.notes[:10]}
