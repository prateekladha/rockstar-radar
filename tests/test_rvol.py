"""Tests for radar.rvol — the single product-wide RVOL metric (cumulative + per_bar, day anchor)."""
import unittest
from datetime import datetime, timedelta

from radar.models import Candle
from radar import rvol as R


def _sessions(days, bars=75, vol=1000, last_mult=1.0, start=datetime(2026, 11, 2, 9, 15)):
    out = []
    for d in range(days):
        day = start + timedelta(days=d)
        m = last_mult if d == days - 1 else 1.0
        for b in range(bars):
            out.append(Candle(at=day + timedelta(minutes=5 * b),
                              open=1, high=1, low=1, close=1, volume=int(vol * m)))
    return out


class RvolConfigTests(unittest.TestCase):
    def test_defaults(self):
        c = R.RvolConfig.from_config({})
        self.assertEqual((c.mode, c.length, c.anchor), ('cumulative', 10, 'day'))

    def test_overrides_and_coercion(self):
        self.assertEqual(R.RvolConfig.from_config({'rvol_mode': 'per_bar', 'rvol_length': '25'}).mode, 'per_bar')
        self.assertEqual(R.RvolConfig.from_config({'rvol_mode': 'per_bar', 'rvol_length': '25'}).length, 25)
        # invalid mode falls back to default; length clamped to 1..100
        self.assertEqual(R.RvolConfig.from_config({'rvol_mode': 'median'}).mode, 'cumulative')
        self.assertEqual(R.RvolConfig.from_config({'rvol_length': 500}).length, 100)
        self.assertEqual(R.RvolConfig.from_config({'rvol_length': 'x'}).length, 10)


class BaselineTests(unittest.TestCase):
    def test_build_baseline_shape_and_values(self):
        c = _sessions(11)                       # 11 full sessions
        bl = R.build_baseline(c, c[-1].at.date(), length=10)
        self.assertEqual(bl['v'], R.BASELINE_SCHEMA)
        self.assertEqual(bl['sessions'], 10)    # last 10 prior sessions
        self.assertEqual(bl['bar']['09:20'], 1000)          # median per-bar
        self.assertEqual(round(bl['cum']['09:20']), 2000)   # cumulative through 2nd bar
        self.assertTrue(R.baseline_has_data(bl, 'cumulative'))
        self.assertTrue(R.baseline_has_data(bl, 'per_bar'))
        self.assertTrue(R.is_current_baseline(bl))

    def test_thin_history_has_no_baseline(self):
        bl = R.build_baseline(_sessions(1), datetime(2026, 11, 3).date(), length=10)
        self.assertFalse(R.baseline_has_data(bl, 'cumulative'))
        self.assertFalse(R.baseline_has_data(bl, 'per_bar'))

    def test_is_current_baseline_rejects_legacy_flat(self):
        self.assertFalse(R.is_current_baseline({'09:15': 1000}))
        self.assertFalse(R.is_current_baseline(None))


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.bl = R.build_baseline(_sessions(11), datetime(2026, 11, 2, 9, 15).date()
                                   + timedelta(days=10), length=10)

    def test_per_bar(self):
        cfg = R.RvolConfig(mode='per_bar')
        self.assertEqual(R.rvol_runtime(cfg, self.bl, slot='09:20', bar_volume=2000, today_cum=0), 2.0)

    def test_cumulative(self):
        cfg = R.RvolConfig(mode='cumulative')
        denom = self.bl['cum']['09:20']
        self.assertEqual(R.rvol_runtime(cfg, self.bl, slot='09:20', bar_volume=0, today_cum=denom * 1.5), 1.5)

    def test_missing_slot_is_none(self):
        cfg = R.RvolConfig(mode='cumulative')
        self.assertIsNone(R.rvol_runtime(cfg, self.bl, slot='23:59', bar_volume=1, today_cum=1))

    def test_legacy_flat_baseline_per_bar(self):
        cfg = R.RvolConfig(mode='per_bar')
        flat = {'09:20': 1000}
        self.assertEqual(R.rvol_runtime(cfg, flat, slot='09:20', bar_volume=1500, today_cum=0), 1.5)


class OneShotTests(unittest.TestCase):
    def test_cumulative_and_per_bar_match_for_constant_volume(self):
        c = _sessions(12, last_mult=1.8)
        self.assertAlmostEqual(R.rvol_from_candles(R.RvolConfig(mode='cumulative'), c), 1.8, places=2)
        self.assertAlmostEqual(R.rvol_from_candles(R.RvolConfig(mode='per_bar'), c), 1.8, places=2)

    def test_thin_returns_none(self):
        self.assertIsNone(R.rvol_from_candles(R.RvolConfig(), _sessions(1)))


class SyntheticTests(unittest.TestCase):
    def test_synthetic_cumulative_equals_per_bar(self):
        bl = R.synthetic_baseline({'09:15': 50000, '09:20': 50000, '09:25': 50000})
        self.assertEqual(bl['bar']['09:20'], 50000)
        self.assertEqual(bl['cum']['09:20'], 100000)       # running sum
        # a bar at 2x baseline reads 2.0 in BOTH modes
        pb = R.rvol_runtime(R.RvolConfig(mode='per_bar'), bl, slot='09:20', bar_volume=100000, today_cum=200000)
        cu = R.rvol_runtime(R.RvolConfig(mode='cumulative'), bl, slot='09:20', bar_volume=100000, today_cum=200000)
        self.assertEqual(pb, cu)
        self.assertEqual(pb, 2.0)


class ThresholdTests(unittest.TestCase):
    def test_per_mode_thresholds(self):
        self.assertEqual(R.rvol_thresholds({}, 'per_bar'), {'watch': 1.0, 'ready': 1.25, 'confirm': 1.5})
        self.assertEqual(R.rvol_thresholds({}, 'cumulative'), {'watch': 1.0, 'ready': 1.1, 'confirm': 1.2})

    def test_config_override(self):
        cfg = {'rvol_thresholds': {'cumulative': {'ready': 1.3}}}
        self.assertEqual(R.rvol_thresholds(cfg, 'cumulative')['ready'], 1.3)


if __name__ == '__main__':
    unittest.main()
