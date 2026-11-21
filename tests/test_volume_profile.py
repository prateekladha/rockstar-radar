"""Unit tests for radar.volume_profile (POC / VAH / VAL / P-b-B-D shape)."""
import unittest
from types import SimpleNamespace

from radar.volume_profile import volume_profile, build_histogram


def c(price_or_low, high=None, volume=0.0):
    """A candle; single price => a tight bar, else (low, high)."""
    lo = price_or_low
    hi = high if high is not None else price_or_low
    return SimpleNamespace(low=lo, high=hi, volume=volume)


class HistogramGuards(unittest.TestCase):
    def test_empty(self):
        self.assertIsNone(build_histogram([], 20))

    def test_zero_volume(self):
        self.assertIsNone(volume_profile([c(100, volume=0), c(110, volume=0)]))

    def test_zero_range(self):
        self.assertIsNone(volume_profile([c(100, volume=5), c(100, volume=7)]))


class ShapeTests(unittest.TestCase):
    def test_D_balanced(self):
        p = volume_profile([c(100, volume=5), c(110, volume=100), c(120, volume=5)], bins=20)
        self.assertEqual(p['shape'], 'D')
        self.assertAlmostEqual(p['poc'], 110.5, delta=1.0)
        self.assertLessEqual(p['val'], p['poc'])
        self.assertGreaterEqual(p['vah'], p['poc'])

    def test_P_bullish_high_poc(self):
        p = volume_profile([c(100, volume=5), c(110, volume=10), c(119, volume=100)], bins=20)
        self.assertEqual(p['shape'], 'P')
        self.assertGreater(p['poc'], 115)

    def test_b_bearish_low_poc(self):
        p = volume_profile([c(100, volume=100), c(110, volume=10), c(120, volume=5)], bins=20)
        self.assertEqual(p['shape'], 'b')
        self.assertLess(p['poc'], 105)

    def test_B_bimodal(self):
        p = volume_profile([c(100, volume=1), c(102, volume=100), c(110, volume=5),
                            c(118, volume=90), c(120, volume=1)], bins=20)
        self.assertEqual(p['shape'], 'B')


class ValueAreaTests(unittest.TestCase):
    def test_value_area_contains_poc_and_is_bounded(self):
        candles = [c(100 + i, volume=(10 if i in (8, 9, 10, 11, 12) else 1)) for i in range(21)]
        p = volume_profile(candles, bins=21, value_area_pct=0.70)
        self.assertTrue(p['lo'] <= p['val'] <= p['poc'] <= p['vah'] <= p['hi'] + 0.5)


if __name__ == '__main__':
    unittest.main()
