"""The 1-minute signal candle (`use_one_minute_candles`).

The opening range stays 09:15-09:20 whichever setting is active; only the candle the state
machine watches afterwards changes. These cover the parts that genuinely differ: assembling the
range from five bars instead of one, stepping the state machine a minute at a time, and the
per-bar thresholds that have to be re-scaled so a shorter bar isn't filtered out for being short.
"""
from __future__ import annotations
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from radar.aggregator import LiveCandleBuilder
from radar.control import ControlError, validate_config_patch
from radar.engine import RadarEngine
from radar.fyers import ApiAuthError, ApiInputError
from radar.models import Candle, Instrument, Tick
from radar.service import baseline_history, cache_path
from radar.utils import IST, bar_start, load_config, market_dt, signal_bar_minutes

DAY = date(2026, 11, 4)
SYM = 'NSE:TEST-EQ'

ONE_MIN = dict(load_config(), use_one_minute_candles=True)
FIVE_MIN = dict(load_config(), use_one_minute_candles=False)

# 09:15-09:19 inclusive: five 1-minute bars spanning the 5-minute opening range. The high (1004)
# and low (998) sit on different bars, so a merged range can only be right if all five are used.
OR_BARS = [
    ('09:15', 1000, 1004, 999.0, 1002, 4000),
    ('09:16', 1002, 1003, 998.0, 1000, 4000),
    ('09:17', 1000, 1002, 999.5, 1001, 4000),
    ('09:18', 1001, 1003, 1000.0, 1002, 4000),
    ('09:19', 1002, 1003, 1001.0, 1002, 4000),
]


def cd(hhmm, o, h, l, c, v):
    return Candle(market_dt(DAY, hhmm), o, h, l, c, v)


def engine(config=ONE_MIN, mode='SIMULATION', atr=0.8, resistance=None, baseline=2000):
    inst = Instrument(SYM, 'Test', median_turnover_cr=120, daily_atr_pct=atr,
                      previous_close=1000, resistance=resistance or [1020.0, 1035.0],
                      support=[975.0, 990.0])
    e = RadarEngine([inst], config, DAY, mode=mode)
    slots = {}
    for hh in (9, 10):
        for mm in range(0, 60):
            slots[f'{hh:02d}:{mm:02d}'] = baseline
    e.set_baseline(SYM, slots)
    return e


def feed_opening(e, bars=OR_BARS):
    """Deliver the opening-range bars as authoritative history, one bar after each closes."""
    for hhmm, o, h, l, c, v in bars:
        bar = cd(hhmm, o, h, l, c, v)
        e.ingest_closed_bar(SYM, bar, observed_at=bar.at + timedelta(minutes=e.bar_minutes))


def feed(e, hhmm, o, h, l, c, v, provisional=False):
    bar = cd(hhmm, o, h, l, c, v)
    e.ingest_closed_bar(SYM, bar, observed_at=bar.at + timedelta(minutes=e.bar_minutes),
                        provisional=provisional)
    return bar


class OpeningRangeTests(unittest.TestCase):
    def test_range_merges_all_five_one_minute_bars(self):
        e = engine()
        feed_opening(e)
        op = e.states[SYM].opening
        self.assertIsNotNone(op)
        self.assertEqual(op.at, market_dt(DAY, '09:15'))   # range is stamped at the window start
        self.assertEqual(op.high, 1004)                    # from the 09:15 bar
        self.assertEqual(op.low, 998)                      # from the 09:16 bar
        self.assertEqual(op.open, 1000)                    # first bar's open
        self.assertEqual(op.close, 1002)                   # last bar's close
        self.assertEqual(op.volume, 20000)                 # summed, not averaged

    def test_incomplete_range_yields_no_opening_and_no_signals(self):
        """A range missing a minute could understate the high or low, so it must not be used."""
        e = engine()
        feed_opening(e, OR_BARS[:4])
        st = e.states[SYM]
        self.assertIsNone(st.opening)
        self.assertEqual(st.state, 'WAIT_OR')
        self.assertIn('4/5', st.reason)
        # A breakout-shaped bar afterwards is ignored outright: no range, no reference to break.
        feed(e, '09:21', 1003, 1006, 1002.8, 1005, 6000)
        self.assertIsNone(st.opening)
        self.assertEqual(len(e.events), 0)

    def test_opening_range_is_never_built_from_provisional_bars(self):
        e = engine()
        for hhmm, o, h, l, c, v in OR_BARS:
            bar = cd(hhmm, o, h, l, c, v)
            e.ingest_live_bar(SYM, bar, observed_at=bar.at + timedelta(minutes=1))
        self.assertIsNone(e.states[SYM].opening)

    def test_five_minute_setting_still_anchors_from_one_bar(self):
        e = engine(config=FIVE_MIN)
        self.assertEqual(e.or_bar_count, 1)
        bar = cd('09:15', 1000, 1004, 998, 1002, 20000)
        e.ingest_closed_bar(SYM, bar, observed_at=market_dt(DAY, '09:20'))
        op = e.states[SYM].opening
        self.assertIsNotNone(op)
        self.assertEqual((op.high, op.low), (1004, 998))


class StateMachineTests(unittest.TestCase):
    """Same rules as the 5-minute path, stepped a minute at a time."""

    def _confirmed(self, e):
        feed_opening(e)                                            # ORH 1004, ORL 998
        feed(e, '09:20', 1002, 1003.5, 1001.5, 1003, 2500)         # prev bar, still inside
        feed(e, '09:21', 1003, 1006, 1002.8, 1005, 6000)           # closes beyond ORH
        return e.states[SYM]

    def test_breakout_confirms_on_a_one_minute_close(self):
        e = engine()
        st = self._confirmed(e)
        self.assertEqual(st.state, 'CONFIRMED')
        self.assertEqual(st.confirmed_side, 'LONG')
        # Confirmation is stamped at the bar's CLOSE, which is one minute on, not five.
        self.assertEqual(st.confirmed_at, market_dt(DAY, '09:22'))
        self.assertIn('1m close beyond OR', st.reason)

    def test_breakout_needs_the_immediately_preceding_minute(self):
        """`prev` is looked up one bar back; on 1m that is 60s, not 300s."""
        e = engine()
        feed_opening(e)
        # Jump straight to 09:25 with no 09:24 bar: the feed is discontinuous, so no confirmation.
        feed(e, '09:25', 1003, 1006, 1002.8, 1005, 6000)
        st = e.states[SYM]
        self.assertNotEqual(st.state, 'CONFIRMED')
        self.assertIn('Missing previous 1-minute candle', st.reason)

    def test_retest_reaches_retest_ready(self):
        e = engine()
        self._confirmed(e)
        feed(e, '09:22', 1005, 1006, 1004.2, 1004.8, 3000)   # dips to the level and holds above
        st = e.states[SYM]
        self.assertEqual(st.state, 'RETEST_READY')
        self.assertEqual(st.entry, 1004.8)
        self.assertGreaterEqual(st.net_rr, 2.0)
        self.assertTrue(any(ev.state == 'RETEST_READY' for ev in e.events))

    def test_retest_failure_is_reported_on_the_one_minute_bar(self):
        e = engine()
        self._confirmed(e)
        feed(e, '09:22', 1005, 1005.2, 1000, 1000.5, 3000)   # closes back inside the range
        self.assertEqual(e.states[SYM].state, 'FAILED')

    def test_retest_expiry_is_measured_in_minutes_not_bars(self):
        """20 minutes stays 20 minutes: on 1m that is 20 bars, not 20 five-minute bars."""
        e = engine()
        self._confirmed(e)                                    # confirmed_at 09:22
        feed(e, '09:45', 1005, 1006, 1004.2, 1004.8, 3000)    # 23 minutes later
        self.assertEqual(e.states[SYM].state, 'EXPIRED')


class ScaledThresholdTests(unittest.TestCase):
    def test_turnover_floor_scales_with_bar_length(self):
        self.assertAlmostEqual(engine(config=FIVE_MIN)._min_bar_turnover_cr(), 0.3)
        self.assertAlmostEqual(engine(config=ONE_MIN)._min_bar_turnover_cr(), 0.06)

    def test_a_real_one_minute_breakout_is_not_rejected_for_being_short(self):
        """~0.1 Cr in a minute clears the raw 5-minute floor of 0.3 only because it is pro-rated."""
        e = engine(baseline=500)
        feed_opening(e)
        feed(e, '09:20', 1002, 1003.5, 1001.5, 1003, 600)
        bar = feed(e, '09:21', 1003, 1006, 1002.8, 1005, 1000)
        turnover_cr = bar.close * bar.volume / 1e7
        self.assertLess(turnover_cr, FIVE_MIN['min_bar_turnover_cr'])   # would fail the raw floor
        self.assertEqual(e.states[SYM].state, 'CONFIRMED')


class PlumbingTests(unittest.TestCase):
    def test_signal_bar_minutes_reads_the_flag_and_defaults_to_one(self):
        self.assertEqual(signal_bar_minutes({}), 1)                      # default when absent
        self.assertEqual(signal_bar_minutes(ONE_MIN), 1)
        self.assertEqual(signal_bar_minutes(FIVE_MIN), 5)

    def test_bar_start_floors_onto_the_requested_grid(self):
        t = market_dt(DAY, '09:23') + timedelta(seconds=47)
        self.assertEqual(bar_start(t, 1), market_dt(DAY, '09:23'))
        self.assertEqual(bar_start(t, 5), market_dt(DAY, '09:20'))
        self.assertEqual(bar_start(t), market_dt(DAY, '09:20'))          # unchanged default

    def test_aggregator_rolls_bars_on_the_one_minute_grid(self):
        rolled = []
        b = LiveCandleBuilder(bar_minutes=1, on_bar=lambda s, c: rolled.append(c))
        b.add_tick(Tick(SYM, 100.0, market_dt(DAY, '09:20') + timedelta(seconds=5), 1000))
        b.add_tick(Tick(SYM, 101.0, market_dt(DAY, '09:20') + timedelta(seconds=55), 1200))
        self.assertEqual(rolled, [])                                     # still inside 09:20
        b.add_tick(Tick(SYM, 102.0, market_dt(DAY, '09:21') + timedelta(seconds=5), 1300))
        self.assertEqual(len(rolled), 1)                                 # 09:20 closed at 09:21
        self.assertEqual(rolled[0].at, market_dt(DAY, '09:20'))
        self.assertEqual((rolled[0].open, rolled[0].high, rolled[0].close), (100.0, 101.0, 101.0))
        self.assertEqual(rolled[0].volume, 200)                          # 1200 - 1000

    def test_baseline_cache_is_separate_per_interval(self):
        """A 1-minute median is ~a fifth of a 5-minute one; sharing a file would skew every RVOL."""
        self.assertNotEqual(cache_path(DAY, 1), cache_path(DAY, 5))
        self.assertIn('_1m', cache_path(DAY, 1).name)

    def test_flag_is_editable_and_validated(self):
        self.assertEqual(validate_config_patch({'use_one_minute_candles': False}),
                         {'use_one_minute_candles': False})
        self.assertEqual(validate_config_patch({'use_one_minute_candles': 'true'}),
                         {'use_one_minute_candles': True})
        with self.assertRaises(ControlError):
            validate_config_patch({'use_one_minute_candles': 'sometimes'})

    def test_replay_reports_the_interval_it_actually_used(self):
        e = engine()
        feed_opening(e)
        self.assertEqual(e.replay(SYM)['bar_minutes'], 1)
        self.assertEqual(e.replay(SYM)['opening']['minutes'], 5)   # range width is unchanged


class RestartRestoreTests(unittest.TestCase):
    """A midday restart rebuilds today's range from the local candle log, not from the broker."""

    def _restore(self, logged_bars):
        from radar.service import SessionJournal, restore_today_from_local_logs
        with tempfile.TemporaryDirectory() as tmp, patch('radar.service.ROOT', Path(tmp)):
            journal = SessionJournal(DAY)
            for hhmm, o, h, l, c, v in logged_bars:
                journal.candle(SYM, cd(hhmm, o, h, l, c, v))
            e = engine()
            restore_today_from_local_logs(e, journal, observed_at=market_dt(DAY, '10:00'))
            return e.states[SYM]

    def test_range_is_rebuilt_from_all_logged_opening_bars(self):
        st = self._restore(OR_BARS)
        self.assertIsNotNone(st.opening)
        self.assertEqual((st.opening.high, st.opening.low), (1004, 998))
        self.assertEqual(st.state, 'RECOVERING')

    def test_partial_log_restores_no_range_rather_than_a_wrong_one(self):
        """Losing the bar that held the high must not leave a range that is too narrow."""
        st = self._restore(OR_BARS[:3])
        self.assertIsNone(st.opening)
        self.assertNotEqual(st.state, 'RECOVERING')


class _Adapter:
    """Records history calls; optionally rejects any window wider than `max_days`."""

    def __init__(self, max_days=None, fail_with=None):
        self.max_days, self.fail_with, self.calls = max_days, fail_with, []

    def history(self, symbol, resolution, frm, to):
        self.calls.append((frm, to))
        if self.fail_with:
            raise self.fail_with
        if self.max_days and (to - frm) > self.max_days * 86400:
            raise ApiInputError('FYERS history rejected request input (-50): invalid date range')
        at = Candle(datetime.fromtimestamp(frm, IST), 100, 101, 99, 100, 5000)
        return [at]


class BaselineWindowTests(unittest.TestCase):
    """A 1-minute lookback is ~15,000 candles; brokers cap how wide an intraday window may be."""

    def _range(self):
        return market_dt(DAY, '00:00') - timedelta(days=40), market_dt(DAY, '00:00')

    def test_single_request_when_the_broker_accepts_the_full_range(self):
        a = _Adapter()
        frm, to = self._range()
        self.assertEqual(len(baseline_history(a, SYM, '1', frm, to)), 1)
        self.assertEqual(len(a.calls), 1)        # unchanged for accounts that accept it

    def test_splits_into_windows_when_the_range_is_refused(self):
        a = _Adapter(max_days=25)
        frm, to = self._range()
        out = baseline_history(a, SYM, '1', frm, to, max_days=25)
        self.assertEqual(len(a.calls), 3)        # the refused attempt, then two windows
        self.assertEqual(len(out), 2)
        windows = a.calls[1:]
        self.assertLess(windows[0][1], windows[1][0])          # disjoint: no double-counted volume
        self.assertEqual(windows[0][0], int(frm.timestamp()))  # covers the whole lookback
        self.assertEqual(windows[-1][1], int(to.timestamp()))

    def test_auth_failure_is_never_retried_as_windows(self):
        """An expired token must stop baseline prep, not become N more identical calls."""
        a = _Adapter(fail_with=ApiAuthError('token expired'))
        frm, to = self._range()
        with self.assertRaises(ApiAuthError):
            baseline_history(a, SYM, '1', frm, to)
        self.assertEqual(len(a.calls), 1)


if __name__ == '__main__':
    unittest.main()
