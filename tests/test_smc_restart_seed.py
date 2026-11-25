"""Root fix for restart-fragile SMC RVOL (radar.service.seed_smc_with_restored_today).

A mid-session scanner restart used to leave the SMC engine's candle buffer with only post-restart bars,
so its cumulative RVOL (rvol_from_candles over state.candles) read ~0 for the rest of the day. The ORB
engine avoids this by restoring today's completed bars from the local-log CSVs; this helper folds those
same restored bars into the SMC buffer so SMC RVOL reflects the full session too.
"""
import unittest
from datetime import datetime
from types import SimpleNamespace

from radar.models import Candle, Instrument
from radar.smc_engine import SMCEngine
from radar.service import seed_smc_with_restored_today
from radar.utils import IST


def _candle(y, mo, d, hh, mm, vol=1000):
    return Candle(datetime(y, mo, d, hh, mm, tzinfo=IST), 100.0, 101.0, 99.0, 100.5, vol)


class SeedSmcRestoredTodayTest(unittest.TestCase):
    SYM = 'NSE:X-EQ'

    def _smc_with_prior(self):
        smc = SMCEngine([Instrument(symbol=self.SYM)], {})
        prior = [_candle(2026, 11, 24, 9, 15 + 5 * i) for i in range(6)]   # yesterday's session
        smc.load_historical_candles(self.SYM, prior)
        return smc, prior

    def _orb_engine_with_today(self, bars):
        completed = {int(c.at.timestamp()): c for c in bars}
        return SimpleNamespace(states={self.SYM: SimpleNamespace(completed=completed)})

    def test_merges_todays_bars_and_keeps_prior(self):
        smc, prior = self._smc_with_prior()
        today = [_candle(2026, 11, 25, 9, 15 + 5 * i, vol=5000) for i in range(6)]   # today's morning
        eng = self._orb_engine_with_today(today)

        n = seed_smc_with_restored_today(eng, smc)

        self.assertEqual(n, 1)
        ats = {c.at for c in smc.states[self.SYM].candles}
        for c in today:
            self.assertIn(c.at, ats, 'today\'s restored bars must be in the SMC buffer')
        for c in prior:
            self.assertIn(c.at, ats, 'prior-session history must be preserved')

    def test_no_restored_bars_is_noop(self):
        smc, _ = self._smc_with_prior()
        before = list(smc.states[self.SYM].candles)
        eng = SimpleNamespace(states={self.SYM: SimpleNamespace(completed={})})
        self.assertEqual(seed_smc_with_restored_today(eng, smc), 0)
        self.assertEqual([c.at for c in smc.states[self.SYM].candles], [c.at for c in before])

    def test_symbol_missing_from_smc_is_skipped(self):
        smc, _ = self._smc_with_prior()
        eng = SimpleNamespace(states={'NSE:OTHER-EQ': SimpleNamespace(
            completed={int(_candle(2026, 11, 25, 9, 15).at.timestamp()): _candle(2026, 11, 25, 9, 15)})})
        self.assertEqual(seed_smc_with_restored_today(eng, smc), 0)


if __name__ == '__main__':
    unittest.main()
