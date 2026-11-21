"""Unit tests for radar.confluence (transparent weighted score)."""
import unittest

from radar.confluence import confluence_score, rvol_strength, rsi_strength, _trapezoid


class HelperTests(unittest.TestCase):
    def test_rvol_strength(self):
        self.assertEqual(rvol_strength(1.0), 0.0)
        self.assertEqual(rvol_strength(1.5), 0.5)
        self.assertEqual(rvol_strength(2.0), 1.0)
        self.assertEqual(rvol_strength(3.0), 1.0)   # clamped
        self.assertEqual(rvol_strength(None), 0.0)

    def test_rsi_strength_long(self):
        self.assertEqual(rsi_strength(60, 'LONG'), 1.0)
        self.assertEqual(rsi_strength(40, 'LONG'), 0.0)
        self.assertEqual(rsi_strength(80, 'LONG'), 0.0)
        self.assertAlmostEqual(rsi_strength(50, 'LONG'), 10 / 15)
        self.assertEqual(rsi_strength(None, 'LONG'), 0.5)

    def test_rsi_strength_short_mirror(self):
        self.assertEqual(rsi_strength(40, 'SHORT'), 1.0)
        self.assertEqual(rsi_strength(60, 'SHORT'), 0.0)

    def test_trapezoid(self):
        self.assertEqual(_trapezoid(10, 40, 55, 65, 80), 0.0)
        self.assertEqual(_trapezoid(60, 40, 55, 65, 80), 1.0)


class ScoreTests(unittest.TestCase):
    def test_perfect_long_maxes_out(self):
        s = confluence_score({'side': 'LONG', 'zone_strength': 1, 'ob_strength': 1, 'fvg_strength': 1,
                              'structure': 1, 'rvol': 2.0, 'rsi': 60, 'vp_support': 1})
        self.assertEqual(s['score'], 100.0)
        self.assertEqual(s['components']['zone'], 20.0)
        self.assertEqual(s['components']['structure'], 15.0)

    def test_empty_floor_is_rsi_neutral(self):
        s = confluence_score({})
        self.assertEqual(s['score'], 5.0)   # only neutral RSI (0.5 * 10)

    def test_partial_zone_only(self):
        s = confluence_score({'side': 'LONG', 'zone_strength': 1})
        self.assertEqual(s['components']['zone'], 20.0)
        self.assertEqual(s['score'], 25.0)   # 20 zone + 5 neutral rsi

    def test_structure_against_contributes_zero(self):
        s = confluence_score({'side': 'LONG', 'structure': -1})
        self.assertEqual(s['components']['structure'], 0.0)

    def test_custom_weights(self):
        s = confluence_score({'side': 'LONG', 'zone_strength': 1},
                             weights={'zone': 40})
        self.assertEqual(s['components']['zone'], 40.0)


if __name__ == '__main__':
    unittest.main()
