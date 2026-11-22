"""Tests for the Debug-tab ORB status replay (radar.debug_analysis._orb_status)."""
import unittest
from datetime import datetime, timedelta

from radar.debug_analysis import _orb_status
from radar.models import Candle
from radar.utils import IST, load_config


def _history(days=12, bars=75, breakout=False):
    out = []
    base = datetime(2026, 11, 2, 9, 15, tzinfo=IST)
    for d in range(days):
        day = base + timedelta(days=d)
        price = 100.0
        for b in range(bars):
            at = day + timedelta(minutes=5 * b)
            if d == days - 1 and breakout and b >= 1:
                price = 100 + b * 0.4
            out.append(Candle(at=at, open=price, high=price + 0.6, low=price - 0.6, close=price,
                              volume=10000 + (800 * b if (d == days - 1 and breakout) else 0)))
    return out


class OrbStatusTests(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()

    def test_runs_and_reports_or_levels(self):
        r = _orb_status('NSE:TEST-EQ', _history(breakout=True), self.cfg)
        self.assertTrue(r['available'])
        self.assertTrue(r['or_formed'])
        self.assertIsNotNone(r['or_high'])
        self.assertIsNotNone(r['or_low'])
        self.assertIn('state', r)

    def test_insufficient_history_unavailable(self):
        r = _orb_status('NSE:TEST-EQ', _history(days=5), self.cfg)
        self.assertFalse(r['available'])
        self.assertIn('session', r.get('reason', '').lower() + 'session')  # reason present

    def test_bad_input_is_handled(self):
        # tz-naive candles would raise inside the engine; _orb_status must swallow it.
        bad = [Candle(at=datetime(2026, 11, 2, 9, 15), open=1, high=1, low=1, close=1, volume=1)]
        r = _orb_status('NSE:TEST-EQ', bad, self.cfg)
        self.assertFalse(r['available'])


if __name__ == '__main__':
    unittest.main()
