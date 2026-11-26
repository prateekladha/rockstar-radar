"""Read-only SMC debug view (SMCEngine.debug_scores) — the explain-why-the-radar-is-empty diagnostic.

Surfaces every symbol's live zone + score WITHOUT the >=35 opportunity filter, so an empty SMC radar
can be explained (how many symbols are warming, in each zone, the top score, near-misses) instead of
just showing nothing. Must never crash on warming/no-tick symbols and must never mutate engine state.
"""
import unittest
from datetime import datetime, timedelta

from radar.models import Candle, Instrument, Tick
from radar.smc_engine import SMCEngine
from radar.utils import IST

BASE = datetime(2026, 11, 24, 9, 15, tzinfo=IST)


def _candles(n):
    # Distinct-time 5m bars with enough high/low spread that trailing_high > trailing_low (so zones
    # are computable). Values are arbitrary — the point is that scoring runs, not a specific score.
    return [Candle(BASE + timedelta(minutes=5 * i), 100 + (i % 7), 101 + (i % 7),
                   99 + (i % 7), 100.5 + (i % 7), 1000) for i in range(n)]


class SmcDebugTest(unittest.TestCase):
    def test_warming_symbols_report_no_score_without_crashing(self):
        smc = SMCEngine([Instrument(symbol='NSE:A-EQ'), Instrument(symbol='NSE:B-EQ')], {})
        smc.load_historical_candles('NSE:A-EQ', _candles(5))   # under 101 -> still warming
        # B has no candles at all.
        d = smc.debug_scores()
        self.assertEqual(d['symbols'], 2)
        self.assertEqual(d['warming'], 2)
        self.assertEqual(d['scored'], 0)
        self.assertIsNone(d['max_score'])
        self.assertEqual(d['opportunity_threshold'], 35)
        rows = {r['symbol']: r for r in d['rows']}
        self.assertIsNone(rows['NSE:A-EQ']['score'])
        self.assertEqual(rows['NSE:A-EQ']['candles'], 5)
        self.assertEqual(rows['NSE:B-EQ']['candles'], 0)

    def test_warmed_symbol_is_scored_with_a_zone(self):
        smc = SMCEngine([Instrument(symbol='NSE:A-EQ')], {})
        smc.load_historical_candles('NSE:A-EQ', _candles(110))  # >=101 -> analysed, trailing set
        smc.states['NSE:A-EQ'].last_tick = Tick('NSE:A-EQ', 103.0, BASE)
        d = smc.debug_scores()
        row = {r['symbol']: r for r in d['rows']}['NSE:A-EQ']
        self.assertEqual(row['candles'], 110)
        self.assertIsNotNone(row['score'])                 # scored (a number, possibly 0)
        self.assertIsInstance(row['score'], (int, float))
        self.assertIn(row['zone'], ('PREMIUM', 'EQUILIBRIUM', 'DISCOUNT', None))
        self.assertEqual(d['scored'], 1)
        self.assertEqual(d['warming'], 0)
        self.assertIsNotNone(d['max_score'])

    def test_debug_does_not_mutate_state(self):
        # The diagnostic must be side-effect free: it must not create/clear opportunities.
        smc = SMCEngine([Instrument(symbol='NSE:A-EQ')], {})
        smc.load_historical_candles('NSE:A-EQ', _candles(110))
        smc.states['NSE:A-EQ'].last_tick = Tick('NSE:A-EQ', 103.0, BASE)
        before = smc.states['NSE:A-EQ'].opportunity
        smc.debug_scores()
        self.assertIs(smc.states['NSE:A-EQ'].opportunity, before)


if __name__ == '__main__':
    unittest.main()
