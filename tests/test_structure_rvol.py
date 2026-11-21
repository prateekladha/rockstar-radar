"""Tests for radar.structure (BOS/CHoCH) and radar.rvol_cum (cumulative RVOL-at-time)."""
import unittest

from radar.structure import label_swings, market_trend, break_event
from radar.rvol_cum import cumulative, rvol_cumulative

UP = [('L', 90), ('H', 100), ('L', 95), ('H', 110)]     # HL + HH -> bullish
DOWN = [('H', 110), ('L', 100), ('H', 105), ('L', 95)]  # LH + LL -> bearish


class StructureTests(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(label_swings(UP), ['L', 'H', 'HL', 'HH'])
        self.assertEqual(label_swings(DOWN), ['H', 'L', 'LH', 'LL'])

    def test_trend(self):
        self.assertEqual(market_trend(UP), 'BULLISH')
        self.assertEqual(market_trend(DOWN), 'BEARISH')
        self.assertEqual(market_trend([('H', 100), ('L', 95)]), 'NEUTRAL')

    def test_bos_continuation_up(self):
        e = break_event(UP, 111)                  # breaks last high 110 in a bullish trend
        self.assertEqual((e['type'], e['dir']), ('BOS', 'BULLISH'))

    def test_choch_reversal_down_in_uptrend(self):
        e = break_event(UP, 94)                    # breaks last low 95 against the bullish trend
        self.assertEqual((e['type'], e['dir']), ('CHOCH', 'BEARISH'))

    def test_bos_continuation_down(self):
        e = break_event(DOWN, 94)                  # breaks last low 95 in a bearish trend
        self.assertEqual((e['type'], e['dir']), ('BOS', 'BEARISH'))

    def test_choch_reversal_up_in_downtrend(self):
        e = break_event(DOWN, 106)                 # breaks last high 105 against the bearish trend
        self.assertEqual((e['type'], e['dir']), ('CHOCH', 'BULLISH'))

    def test_no_break(self):
        self.assertIsNone(break_event(UP, 105))    # between last low 95 and last high 110


class RvolCumTests(unittest.TestCase):
    def test_cumulative(self):
        self.assertEqual(cumulative([2, 3, 5]), [2, 5, 10])

    def test_rvol_above_one(self):
        today = [10, 10, 10]                        # cum 30 at last bar
        prior = [[5, 5, 5]] * 6                     # each prior cum 15
        self.assertEqual(rvol_cumulative(today, prior), 2.0)

    def test_insufficient_days_returns_none(self):
        self.assertIsNone(rvol_cumulative([10, 10], [[5, 5]] * 3, min_days=5))

    def test_idx_mid_session(self):
        today = [10, 10, 10]
        prior = [[5, 5, 5]] * 5
        self.assertEqual(rvol_cumulative(today, prior, idx=0), 2.0)   # 10 / mean(5)

    def test_zero_baseline_none(self):
        self.assertIsNone(rvol_cumulative([10], [[0]] * 5))


if __name__ == '__main__':
    unittest.main()
