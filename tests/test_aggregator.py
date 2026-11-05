"""Realtime tick -> 5-minute candle aggregation (Phase 1 realtime engine)."""
import unittest
from datetime import date, timedelta

from radar.aggregator import LiveCandleBuilder
from radar.models import Tick
from radar.utils import market_dt

DAY = date(2026, 11, 5)
SYM = 'NSE:BHARTIARTL-EQ'


def tick(hhmm, secs, price, cum_vol, symbol=SYM):
    return Tick(symbol, price, market_dt(DAY, hhmm) + timedelta(seconds=secs),
                daily_volume=cum_vol)


class AggregatorTests(unittest.TestCase):
    def test_never_emits_in_progress_bar(self):
        b = LiveCandleBuilder()
        self.assertIsNone(b.add_tick(tick('09:20', 1, 100, 1000)))
        self.assertIsNone(b.add_tick(tick('09:22', 0, 102, 1100)))
        self.assertIsNone(b.add_tick(tick('09:24', 59, 101, 1200)))  # still bar 09:20

    def test_rollover_emits_completed_ohlc(self):
        b = LiveCandleBuilder()
        b.add_tick(tick('09:20', 1, 100, 1000))
        b.add_tick(tick('09:22', 0, 103, 1100))   # high
        b.add_tick(tick('09:23', 0, 99, 1150))    # low
        b.add_tick(tick('09:24', 0, 101, 1180))   # close of 09:20 bar
        done = b.add_tick(tick('09:25', 2, 101.5, 1300))  # rolls over
        self.assertIsNotNone(done)
        self.assertEqual(done.at, market_dt(DAY, '09:20'))
        self.assertEqual((done.open, done.high, done.low, done.close), (100, 103, 99, 101))

    def test_volume_is_cumulative_delta_between_bar_ends(self):
        b = LiveCandleBuilder()
        b.seed_prev_cumulative(SYM, 1000)      # authoritative baseline
        b.add_tick(tick('09:20', 1, 100, 1100))
        b.add_tick(tick('09:22', 0, 102, 1150))  # bar 09:20 ends at cum 1150
        first = b.add_tick(tick('09:25', 30, 101, 1300))  # roll: vol = 1150-1000
        self.assertEqual(first.volume, 150)
        second = b.add_tick(tick('09:30', 10, 104, 1500))  # roll: vol = 1300-1150
        self.assertEqual(second.volume, 150)

    def test_first_bar_without_seed_undercounts_but_never_negative(self):
        b = LiveCandleBuilder()
        b.add_tick(tick('09:20', 1, 100, 5000))   # baseline defaults to 5000
        b.add_tick(tick('09:22', 0, 101, 5090))
        done = b.add_tick(tick('09:25', 1, 102, 5200))
        self.assertEqual(done.volume, 90)         # 5090 - 5000, intra-bar delta
        self.assertGreaterEqual(done.volume, 0)

    def test_out_of_order_tick_ignored(self):
        b = LiveCandleBuilder()
        b.add_tick(tick('09:25', 1, 100, 1000))
        self.assertIsNone(b.add_tick(tick('09:20', 5, 999, 999)))  # backdated
        done = b.add_tick(tick('09:30', 1, 100, 1100))
        self.assertEqual(done.at, market_dt(DAY, '09:25'))
        self.assertEqual(done.high, 100)          # the 999 backdated price was ignored

    def test_flush_finalizes_stale_bar_only_after_window(self):
        b = LiveCandleBuilder()
        b.add_tick(tick('09:20', 1, 100, 1000))
        self.assertEqual(b.flush_completed(market_dt(DAY, '09:24')), [])  # window open
        out = b.flush_completed(market_dt(DAY, '09:25') + timedelta(seconds=5))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], SYM)
        self.assertEqual(out[0][1].at, market_dt(DAY, '09:20'))
        self.assertEqual(b.flush_completed(market_dt(DAY, '09:40')), [])  # nothing left

    def test_flush_does_not_fabricate_bars_for_silent_symbols(self):
        b = LiveCandleBuilder()  # no ticks at all
        self.assertEqual(b.flush_completed(market_dt(DAY, '10:00')), [])

    def test_on_bar_callback_fires_once_per_completed_bar(self):
        seen = []
        b = LiveCandleBuilder(on_bar=lambda s, c: seen.append((s, c.at)))
        b.add_tick(tick('09:20', 1, 100, 1000))
        b.add_tick(tick('09:25', 1, 101, 1100))   # emits 09:20
        b.add_tick(tick('09:30', 1, 102, 1200))   # emits 09:25
        self.assertEqual([t for _, t in seen],
                         [market_dt(DAY, '09:20'), market_dt(DAY, '09:25')])

    def test_two_symbols_are_independent(self):
        b = LiveCandleBuilder()
        other = 'NSE:SBIN-EQ'
        b.add_tick(tick('09:20', 1, 100, 1000))
        b.add_tick(tick('09:20', 1, 500, 2000, symbol=other))
        d1 = b.add_tick(tick('09:25', 1, 101, 1100))
        d2 = b.add_tick(tick('09:25', 1, 505, 2200, symbol=other))
        self.assertEqual(d1.open, 100)
        self.assertEqual(d2.open, 500)


if __name__ == '__main__':
    unittest.main()
