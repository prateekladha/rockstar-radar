"""Unit test for radar.confluence_stack.compute_confluence_stack."""
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from radar.models import Candle
from radar.confluence_stack import compute_confluence_stack

IST = timezone(timedelta(hours=5, minutes=30))


def make_state(n_days=2, bars_per_day=40):
    candles, px = [], 1000.0
    for d in range(n_days):
        t = datetime(2026, 11, 17 + d, 9, 15, tzinfo=IST)
        for i in range(bars_per_day):
            px += (1.0 if (i // 5) % 2 == 0 else -0.8)
            candles.append(Candle(at=t, open=px, high=px + 1, low=px - 1, close=px, volume=2000 + i * 10))
            t += timedelta(minutes=5)
    zone = SimpleNamespace(zone_type='DISCOUNT')
    opp = SimpleNamespace(zone=zone, trade={'side': 'LONG', 'in_fresh_ob': True})
    return SimpleNamespace(candles=candles, trend='BULLISH', structures=[], opportunity=opp)


class ConfluenceStackTests(unittest.TestCase):
    def test_full_stack(self):
        st = make_state()
        stack = compute_confluence_stack(st, 'LONG')
        self.assertIsNotNone(stack)
        self.assertIn('score', stack)
        self.assertIsNotNone(stack['rsi'])
        self.assertIsNotNone(stack['pivots'])          # 2 days -> prior session available
        self.assertEqual(set(stack['pivots']), {'P', 'R1', 'R2', 'R3', 'S1', 'S2', 'S3'})
        self.assertIsNotNone(stack['vp'])
        self.assertEqual(set(stack['vp']), {'vah', 'val', 'poc', 'shape'})
        self.assertTrue(0 <= stack['score'] <= 100)
        self.assertIn('components', stack)

    def test_empty_candles(self):
        self.assertIsNone(compute_confluence_stack(SimpleNamespace(candles=[]), 'LONG'))

    def test_single_day_no_pivots(self):
        st = make_state(n_days=1)
        stack = compute_confluence_stack(st, 'LONG')
        self.assertIsNone(stack['pivots'])             # no prior session -> no pivots
        self.assertIsNotNone(stack['rsi'])


if __name__ == '__main__':
    unittest.main()
