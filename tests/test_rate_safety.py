"""Offline safety tests: provider-side block must NEVER fan out API requests."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from radar.engine import RadarEngine
from radar.fyers import ApiRateLimitError, ApiProviderError, RateLimiter
from radar.models import Candle, Instrument, Tick
from radar.selecting import prepare_selection
from radar.service import build_baselines
from radar.utils import load_config, market_dt


class BlockingAdapter:
    def __init__(self):
        self.history_calls = 0
        self.quote_calls = 0

    def quotes(self, symbols):
        self.quote_calls += 1
        return {s: {'lp': 300, 'prev_close_price': 298} for s in symbols}

    def history(self, *args):
        self.history_calls += 1
        raise ApiRateLimitError('Error 1015: temporarily banned')


class SafetyTests(unittest.TestCase):
    def test_conservative_limiter_floor_cannot_be_disabled_by_old_config(self):
        limiter = RateLimiter(1.3, 50, 5000)
        self.assertGreaterEqual(limiter.spacing, 2.5)
        self.assertLessEqual(limiter.per_minute, 24)
        self.assertLessEqual(limiter.per_day, 4500)

    def test_universe_prep_stops_on_first_provider_ban_and_saves_cache(self):
        cfg = load_config()
        adapter = BlockingAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            symbols = [(f'NSE:S{i}-EQ', 'Test') for i in range(110)]
            with patch('radar.selecting.ROOT', root), \
                 patch('radar.selecting.load_universe', return_value=symbols), \
                 patch('radar.selecting.load_morning_pins', return_value=[]):
                with self.assertRaises(ApiRateLimitError):
                    prepare_selection(adapter, cfg, root/'unused.csv', root/'today100.json')
                self.assertEqual(adapter.history_calls, 1)
                self.assertTrue(list((root/'data').glob('daily_cache_*.json')))
                self.assertFalse((root/'today100.json').exists())

    def test_baseline_preparation_stops_on_first_provider_ban(self):
        cfg = load_config()
        adapter = BlockingAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)/'baseline.json'
            with patch('radar.service.cache_path', return_value=cache):
                with self.assertRaises(ApiRateLimitError):
                    build_baselines(adapter, [f'NSE:S{i}-EQ' for i in range(100)],
                                    date(2026, 11, 4), cfg)
                self.assertEqual(adapter.history_calls, 1)
                self.assertEqual(json.loads(cache.read_text()), {})

    def test_halt_removes_actionable_candidates_and_suppresses_new_ticks(self):
        cfg = load_config()
        today = date(2026, 11, 4)
        sym = 'NSE:SBIN-EQ'
        engine = RadarEngine([Instrument(sym, 'Banking')], cfg, today, mode='LIVE')
        engine.states[sym].state = 'RETEST_READY'
        engine.states[sym].score = 95
        engine.states[sym].last_tick = Tick(sym, 310, market_dt(today, '09:25'))
        engine.halt('FYERS rate limited')
        engine.update_health('CONNECTED')
        engine.update_tick(Tick(sym, 311, market_dt(today, '09:26')),
                           received_at=market_dt(today, '09:26'))
        snapshot = engine.snapshot(reference_time=market_dt(today, '09:26'))
        self.assertEqual(engine.states[sym].state, 'HALTED')
        self.assertEqual(snapshot['top5'], [])
        self.assertIn('HALTED', snapshot['feed_health'])
        self.assertEqual(engine.states[sym].last_tick.price, 310)


if __name__ == '__main__':
    unittest.main()
