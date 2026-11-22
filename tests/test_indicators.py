"""Unit tests for radar.indicators (RSI, Fibonacci pivots, nearest_level)."""
import unittest

from radar.indicators import rsi, fib_pivots, nearest_level, ema, ema_series, ema_cross


class EmaTests(unittest.TestCase):
    def test_constant_series_equals_constant(self):
        self.assertEqual(ema([10.0] * 30, 5), 10.0)

    def test_insufficient_data_is_none(self):
        self.assertIsNone(ema([1, 2, 3], 5))
        self.assertEqual(ema_cross([1, 2, 3], 5, 20)['trend'], None)

    def test_series_alignment(self):
        s = ema_series([1, 2, 3, 4, 5], 3)
        self.assertEqual(s[:2], [None, None])     # undefined before the seed
        self.assertAlmostEqual(s[2], 2.0)          # SMA seed of first 3

    def test_rising_is_bullish(self):
        c = ema_cross(list(range(1, 61)), 5, 20)
        self.assertEqual(c['trend'], 'BULLISH')
        self.assertGreater(c['ema_fast'], c['ema_slow'])

    def test_falling_is_bearish(self):
        self.assertEqual(ema_cross(list(range(60, 0, -1)), 5, 20)['trend'], 'BEARISH')

    def test_detects_last_upward_cross(self):
        series = [100 - i for i in range(30)] + [70 + i * 2 for i in range(30)]
        c = ema_cross(series, 5, 20)
        self.assertEqual(c['trend'], 'BULLISH')
        self.assertIsNotNone(c['cross'])
        self.assertEqual(c['cross']['direction'], 'UP')

    def test_offset_reads_back_n_bars(self):
        vals = list(range(1, 61))
        at0 = ema_cross(vals, 5, 20, 0)['ema_fast']
        at5 = ema_cross(vals, 5, 20, 5)['ema_fast']
        # offset 5 reports the EMA 5 bars earlier on a rising series -> a smaller value
        self.assertLess(at5, at0)
        self.assertEqual(ema_cross(vals, 5, 20, 5)['ema_fast'], ema_cross(vals[:-5], 5, 20, 0)['ema_fast'])
        self.assertEqual(ema_cross(vals, 5, 20, 3)['offset'], 3)


class RsiTests(unittest.TestCase):
    def test_all_up_is_100(self):
        closes = [float(x) for x in range(1, 20)]  # strictly increasing -> no losses
        self.assertEqual(rsi(closes, 14), 100.0)

    def test_all_down_is_0(self):
        closes = [float(x) for x in range(20, 1, -1)]  # strictly decreasing -> no gains
        self.assertEqual(rsi(closes, 14), 0.0)

    def test_flat_is_neutral_50(self):
        self.assertEqual(rsi([100.0] * 20, 14), 50.0)

    def test_insufficient_data_returns_none(self):
        self.assertIsNone(rsi([1.0, 2.0, 3.0], 14))   # need period+1
        self.assertIsNone(rsi([], 14))
        self.assertIsNone(rsi(None, 14))

    def test_known_mixed_value(self):
        # Hand-computed with Wilder smoothing, period=2:
        # deltas +1,-1,+1 -> seed avg_gain=.5 avg_loss=.5 -> smooth -> ag=.75 al=.25 -> RS=3 -> RSI=75.
        self.assertEqual(rsi([10.0, 11.0, 10.0, 11.0], 2), 75.0)

    def test_bounds(self):
        closes = [10, 10.5, 10.2, 10.8, 11.0, 10.6, 11.2, 11.5, 11.1, 11.8,
                  12.0, 11.6, 12.3, 12.1, 12.6, 12.9]
        v = rsi([float(x) for x in closes], 14)
        self.assertIsNotNone(v)
        self.assertTrue(0.0 <= v <= 100.0)


class FibPivotTests(unittest.TestCase):
    def test_standard_levels(self):
        p = fib_pivots(110.0, 90.0, 100.0)
        self.assertEqual(p['P'], 100.0)
        self.assertEqual(p['R1'], 107.64)   # 100 + 0.382*20
        self.assertEqual(p['R2'], 112.36)   # 100 + 0.618*20
        self.assertEqual(p['R3'], 120.0)    # 100 + 1.0*20
        self.assertEqual(p['S1'], 92.36)
        self.assertEqual(p['S2'], 87.64)
        self.assertEqual(p['S3'], 80.0)

    def test_resistances_above_supports(self):
        p = fib_pivots(250.0, 240.0, 248.0)
        self.assertTrue(p['S3'] < p['S2'] < p['S1'] < p['P'] < p['R1'] < p['R2'] < p['R3'])

    def test_invalid_inputs_raise(self):
        with self.assertRaises(ValueError):
            fib_pivots(90.0, 110.0, 100.0)   # high < low
        with self.assertRaises(ValueError):
            fib_pivots(0.0, -1.0, 1.0)        # non-positive
        with self.assertRaises(ValueError):
            fib_pivots(None, 90.0, 100.0)     # missing


class NearestLevelTests(unittest.TestCase):
    def test_both_sides(self):
        self.assertEqual(nearest_level(100.0, [95.0, 103.0, 108.0]), 103.0)

    def test_above_only(self):
        self.assertEqual(nearest_level(100.0, [95.0, 103.0, 108.0], above=True), 103.0)

    def test_below_only(self):
        self.assertEqual(nearest_level(100.0, [95.0, 103.0, 108.0], above=False), 95.0)

    def test_no_candidate(self):
        self.assertIsNone(nearest_level(100.0, [101.0, 102.0], above=False))
        self.assertIsNone(nearest_level(100.0, []))
        self.assertIsNone(nearest_level(0.0, [1.0, 2.0]))


if __name__ == '__main__':
    unittest.main()
