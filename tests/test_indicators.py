"""Unit tests for radar.indicators (RSI, Fibonacci pivots, nearest_level)."""
import unittest

from radar.indicators import rsi, fib_pivots, nearest_level


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
