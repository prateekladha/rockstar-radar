"""Midday restart must not promote historical trades as real-time opportunities."""
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from radar.engine import RadarEngine
from radar.models import Candle, Instrument, Signal, Tick
from radar.service import (SessionJournal, restore_today_from_local_logs,
                           start_live)
from radar.utils import load_config, market_dt

DAY = date(2026, 11, 4)
SYM = 'NSE:BHARTIARTL-EQ'


class MiddayRestartTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()
        self.instrument = Instrument(SYM, 'Telecom', 100, 1.5, 1500)

    def test_local_restore_preserves_OR_and_past_events_but_never_live_signal(self):
        with tempfile.TemporaryDirectory() as tmp, patch('radar.service.ROOT', Path(tmp)):
            journal = SessionJournal(DAY)
            op = Candle(market_dt(DAY, '09:15'), 1500, 1505, 1492, 1501, 23000)
            journal.candle(SYM, op)
            journal.candle(SYM, Candle(market_dt(DAY, '09:20'), 1501, 1507, 1500, 1505, 45000))
            journal.event(Signal('2026-11-04 09:25:00', SYM, 'LONG', 'CONFIRMED',
                                 78, 1505, 2.1, 'Earlier confirmed event', 1505))
            engine = RadarEngine([self.instrument], self.cfg, DAY, mode='LIVE')
            counts = restore_today_from_local_logs(engine, journal, market_dt(DAY, '10:12'))
            self.assertEqual(counts, (2, 1))
            self.assertEqual(engine.states[SYM].opening.high, 1505)
            self.assertEqual(len(engine.events), 1)
            self.assertEqual(engine.states[SYM].state, 'SESSION_CONSUMED')
            self.assertFalse(engine.states[SYM].last_tick)
            self.assertEqual(engine.snapshot(market_dt(DAY, '10:12'))['top5'], [])
            journal.candle(SYM, op)
            self.assertEqual(len((journal.root / f'fy_history_candles_{DAY}.csv').read_text().splitlines()), 3)

    def test_recovered_confirmed_symbol_cannot_signal_second_breakout(self):
        with tempfile.TemporaryDirectory() as tmp, patch('radar.service.ROOT', Path(tmp)):
            journal = SessionJournal(DAY)
            journal.candle(SYM, Candle(market_dt(DAY, '09:15'), 1500, 1505, 1492, 1501, 23000))
            journal.event(Signal('2026-11-04 09:25:00', SYM, 'LONG', 'CONFIRMED',
                                 82, 1505, 2.1, 'Already confirmed', 1505))
            cfg = dict(self.cfg, new_signals_stop='15:00')
            e = RadarEngine([self.instrument], cfg, DAY, mode='LIVE')
            restore_today_from_local_logs(e, journal, market_dt(DAY, '14:00'))
            self.assertEqual(e.states[SYM].state, 'SESSION_CONSUMED')
            e.set_baseline(SYM, {'13:55': 10000})
            e.states[SYM].completed[int(market_dt(DAY, '13:55').timestamp())] = Candle(
                market_dt(DAY,'13:55'), 1502, 1505, 1499, 1504, 18000)
            e.update_tick(Tick(SYM, 1505, market_dt(DAY, '14:00'), 1_000_000, 1500),
                          received_at=market_dt(DAY, '14:00'))
            self.assertEqual(e.states[SYM].state, 'SESSION_CONSUMED')
            self.assertFalse(e.needs_verification(SYM))
            self.assertEqual(len(e.events), 1)

    def test_stale_five_minute_history_will_not_generate_watch_after_sleep(self):
        cfg = dict(self.cfg, new_signals_stop='15:00')
        engine = RadarEngine([self.instrument], cfg, DAY, mode='LIVE')
        opening = Candle(market_dt(DAY, '09:15'), 1500, 1505, 1492, 1501, 23000)
        engine.ingest_closed_bar(SYM, opening, market_dt(DAY, '09:20'))
        engine.set_baseline(SYM, {'09:15': 10000})
        tick = Tick(SYM, 1504.50, market_dt(DAY, '14:01'), 100000, 1500)
        engine.update_tick(tick, received_at=market_dt(DAY, '14:01'))
        self.assertEqual(engine.states[SYM].state, 'RECOVERING')
        self.assertEqual(engine.snapshot(market_dt(DAY, '14:01'))['top5'], [])
        self.assertEqual(engine.events, [])

    def test_closed_window_displays_review_only_without_broker_requests(self):
        with tempfile.TemporaryDirectory() as tmp, patch('radar.service.ROOT', Path(tmp)):
            journal = SessionJournal(DAY)
            opening = Candle(market_dt(DAY, '09:15'), 1500, 1505, 1492, 1501, 23000)
            journal.candle(SYM, opening)
            payload = {'for_session': DAY.isoformat()}
            # Review-only begins at new_signals_stop (15:00) + retest_expiry (20m) = 15:20 IST.
            with patch('radar.service.now_ist', return_value=market_dt(DAY, '15:30')), \
                 patch('radar.service.read_selection', return_value=(payload, [self.instrument])), \
                 patch('radar.service.FyersAdapter', side_effect=AssertionError('REST should not start')), \
                 patch('radar.dashboard.serve') as mock_serve:
                start_live(self.cfg, Path(tmp)/'today100.json', 8765)
                mock_serve.assert_called_once()
                engine = mock_serve.call_args.args[0]
                snap = engine.snapshot(market_dt(DAY, '15:30'))
                self.assertEqual(snap['anchors_ready'], 1)
                self.assertEqual(snap['top5'], [])
                self.assertTrue(snap['session_closed'])
                self.assertIn('SESSION CLOSED', snap['feed_health'])
                self.assertEqual(snap['all'][0]['state'], 'SESSION_CLOSED')

    def test_replay_ignores_future_candle_and_unselected_symbols(self):
        with tempfile.TemporaryDirectory() as tmp, patch('radar.service.ROOT', Path(tmp)):
            journal = SessionJournal(DAY)
            journal.candle(SYM, Candle(market_dt(DAY, '14:00'), 1500, 1505, 1492, 1501, 23000))
            journal.candle('NSE:UNKNOWN-EQ', Candle(market_dt(DAY, '09:15'), 100, 110, 90, 101, 300))
            engine = RadarEngine([self.instrument], self.cfg, DAY, mode='LIVE')
            counts = restore_today_from_local_logs(engine, journal, market_dt(DAY, '13:59'))
            self.assertEqual(counts[0], 0)
            self.assertEqual(engine.states[SYM].completed, {})

    def test_live_snapshot_disables_actives_after_stop_even_with_fresh_tick(self):
        e = RadarEngine([self.instrument], self.cfg, DAY, mode='LIVE')
        st = e.states[SYM]
        st.state = 'RETEST_READY'
        st.score = 99
        # Fresh tick at 15:30 (past 15:00 stop + 20m expiry) must still be disabled.
        st.last_tick = Tick(SYM, 1505, market_dt(DAY, '15:30'))
        snap = e.snapshot(market_dt(DAY, '15:30'))
        self.assertEqual(snap['top5'], [])
        self.assertTrue(snap['session_closed'])

    def test_simulation_mode_still_works_after_cutoff(self):
        e = RadarEngine([self.instrument], self.cfg, DAY, mode='SIMULATION')
        st = e.states[SYM]
        st.state = 'RETEST_READY'
        st.score = 99
        st.last_tick = Tick(SYM, 1505, market_dt(DAY, '09:30'))
        snap = e.snapshot(market_dt(DAY, '14:00'))
        self.assertEqual(len(snap['top5']), 1)
        self.assertFalse(snap['session_closed'])


if __name__ == '__main__':
    unittest.main()
