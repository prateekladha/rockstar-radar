"""Unit tests for server.exit_engine (pure adaptive-exit decisions)."""
import unittest
from datetime import datetime

from server.exit_engine import favorable, r_distance, reached_r, mins_until, velocity_exit

NOON = datetime(2026, 11, 21, 12, 0)   # tz-agnostic; functions only do replace()/subtract()


class BasicsTests(unittest.TestCase):
    def test_favorable(self):
        self.assertEqual(favorable('LONG', 100, 105), 5)
        self.assertEqual(favorable('SHORT', 100, 95), 5)
        self.assertEqual(favorable('LONG', 100, 98), -2)

    def test_r_distance(self):
        self.assertEqual(r_distance(100, 98), 2)
        self.assertEqual(r_distance(100, None), 0.0)

    def test_reached_r_long(self):
        self.assertTrue(reached_r('LONG', 100, 98, 102, 1.0))    # +2 == 1R
        self.assertFalse(reached_r('LONG', 100, 98, 101, 1.0))   # +1 < 1R
        self.assertTrue(reached_r('LONG', 100, 98, 104, 2.0))    # +4 == 2R

    def test_reached_r_short(self):
        self.assertTrue(reached_r('SHORT', 100, 102, 98, 1.0))
        self.assertFalse(reached_r('SHORT', 100, 102, 99, 1.0))

    def test_reached_r_guards(self):
        self.assertFalse(reached_r('LONG', 100, 100, 110, 1.0))  # zero-width stop
        self.assertFalse(reached_r('LONG', 100, 98, 110, 0))     # r_mult 0


class MinsUntilTests(unittest.TestCase):
    def test_before_and_after(self):
        self.assertEqual(mins_until(datetime(2026, 11, 21, 14, 30), '15:00'), 30)
        self.assertEqual(mins_until(datetime(2026, 11, 21, 14, 30), '14:00'), -30)


class VelocityExitTests(unittest.TestCase):
    def test_not_in_profit_never_exits(self):
        self.assertFalse(velocity_exit('LONG', 100, 99, 120, 30, NOON, '15:00', 1.5))

    def test_target_reached_defers_to_target_fill(self):
        self.assertFalse(velocity_exit('LONG', 100, 121, 120, 30, NOON, '15:00', 1.5))

    def test_past_cutoff_in_profit_books(self):
        late = datetime(2026, 11, 21, 15, 5)
        self.assertTrue(velocity_exit('LONG', 100, 103, 120, 30, late, '15:00', 1.5))

    def test_too_little_history(self):
        self.assertFalse(velocity_exit('LONG', 100, 102, 130, 2, NOON, '15:00', 1.5))

    def test_unreachable_pace_books(self):
        # fill100 px102 (+2) over 10min -> 0.2/min; target130 -> 28 to go in 120min -> need 0.233/min;
        # 1.5*0.2=0.3 ... make target far enough: 130 needs 0.233 < 0.3 -> reachable. Use 160.
        # remaining 58 / 120min = 0.483 needed > 0.3 -> books.
        now = datetime(2026, 11, 21, 13, 0)   # 120 min to 15:00
        self.assertTrue(velocity_exit('LONG', 100, 102, 160, 10, now, '15:00', 1.5))

    def test_reachable_pace_runs(self):
        now = datetime(2026, 11, 21, 13, 0)   # 120 min to 15:00
        # +2 over 10min = 0.2/min; target 110 -> 8 to go / 120 = 0.067 < 0.3 -> let it run
        self.assertFalse(velocity_exit('LONG', 100, 102, 110, 10, now, '15:00', 1.5))

    def test_short_side_unreachable_books(self):
        now = datetime(2026, 11, 21, 13, 0)
        # SHORT fill100 px98 (+2) in 10min=0.2/min; target 60 -> 38 to go /120=0.317 > 0.3 -> books
        self.assertTrue(velocity_exit('SHORT', 100, 98, 60, 10, now, '15:00', 1.5))


if __name__ == '__main__':
    unittest.main()
