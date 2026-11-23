"""Regression for the ORB/SMC stop-clamp (server.order_engine._exit_capped_at_stop).

A paper position carrying a stop must never realise WORSE than that stop: a resting stop-loss fills
at the stop, not at a far-away later print. The 2026-11-23 live run force-closed MARUTI at the 15:15
price (~5R) because the intraday stop pass is skipped whenever the feed isn't `live` (the price map
is empty). The clamp caps a skipped stop at ~1R. It must only ever improve the fill, never worsen it.
"""
import unittest
from types import SimpleNamespace

from server.order_engine import _exit_capped_at_stop


def order(side, stop):
    return SimpleNamespace(side=side, stop=stop)


class StopClampTests(unittest.TestCase):
    def test_long_price_below_stop_is_clamped_to_stop(self):
        px, capped = _exit_capped_at_stop(order('LONG', 95.0), 80.0)
        self.assertEqual(px, 95.0)
        self.assertTrue(capped)

    def test_short_price_above_stop_is_clamped_to_stop(self):
        px, capped = _exit_capped_at_stop(order('SHORT', 105.0), 130.0)
        self.assertEqual(px, 105.0)
        self.assertTrue(capped)

    def test_long_price_above_stop_is_untouched(self):
        # Target/square-off in profit — never pulled down to the stop.
        px, capped = _exit_capped_at_stop(order('LONG', 95.0), 112.0)
        self.assertEqual(px, 112.0)
        self.assertFalse(capped)

    def test_short_price_below_stop_is_untouched(self):
        px, capped = _exit_capped_at_stop(order('SHORT', 105.0), 92.0)
        self.assertEqual(px, 92.0)
        self.assertFalse(capped)

    def test_no_stop_is_passthrough(self):
        px, capped = _exit_capped_at_stop(order('LONG', None), 80.0)
        self.assertEqual(px, 80.0)
        self.assertFalse(capped)

    def test_none_price_is_passthrough(self):
        px, capped = _exit_capped_at_stop(order('LONG', 95.0), None)
        self.assertIsNone(px)
        self.assertFalse(capped)

    def test_exactly_at_stop_is_not_clamped(self):
        px, capped = _exit_capped_at_stop(order('LONG', 95.0), 95.0)
        self.assertEqual(px, 95.0)
        self.assertFalse(capped)


if __name__ == '__main__':
    unittest.main()
