from __future__ import annotations
import csv
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from radar.models import Candle, Instrument, Tick
from radar.engine import RadarEngine, same_time_baseline
from radar.selecting import compute_daily_profile, choose_top100, load_universe, SelectionError
from radar.fyers import RateLimiter
from radar.utils import IST, load_config, market_dt
from radar.demo import demo_engine

CFG = load_config()
DAY = date(2026, 11, 4)
SYM = 'NSE:TEST-EQ'


def cd(t, o, h, l, c, v):
    return Candle(market_dt(DAY, t), o, h, l, c, v)


def engine(mode='SIMULATION', highs=None, lows=None, config=None):
    data = Instrument(SYM, 'Test', 120, 1.8, 1000,
                      highs or [1016, 1035], lows or [975, 990])
    e = RadarEngine([data], config or CFG, DAY, mode=mode)
    e.set_baseline(SYM, {'09:15': 10000, '09:20': 10000,
                         '09:25': 10000, '09:30': 10000, '09:35': 10000})
    return e


class RadarTests(unittest.TestCase):
    def test_opening_range_exact_first_five_minutes(self):
        e = engine()
        first = cd('09:15', 1000, 1004, 998, 1002, 20000)
        e.ingest_closed_bar(SYM, first, market_dt(DAY, '09:19') )
        self.assertIsNone(e.states[SYM].opening)
        e.ingest_closed_bar(SYM, first, market_dt(DAY, '09:20'))
        self.assertEqual((e.states[SYM].opening.high, e.states[SYM].opening.low), (1004, 998))

    def test_tick_never_confirms_breakout(self):
        e = engine()
        e.ingest_closed_bar(SYM, cd('09:15', 1000, 1004, 998, 1002, 20000), market_dt(DAY, '09:20'))
        e.update_tick(Tick(SYM, 1005, market_dt(DAY, '09:23'), 25000, 1002),
                      market_dt(DAY, '09:23'))
        self.assertEqual(e.states[SYM].state, 'BREAKOUT_PENDING')
        self.assertIsNone(e.states[SYM].confirmed_at)

    def test_confirm_requires_closed_bar_with_rvol_and_vwap(self):
        e = engine()
        e.ingest_closed_bar(SYM, cd('09:15', 1000, 1004, 998, 1002, 20000), market_dt(DAY, '09:20'))
        five = cd('09:20', 1002, 1007, 1001, 1005, 20000)
        e.ingest_closed_bar(SYM, five, market_dt(DAY, '09:24'))
        self.assertIsNone(e.states[SYM].confirmed_at)
        e.ingest_closed_bar(SYM, five, market_dt(DAY, '09:25'))
        self.assertEqual(e.states[SYM].state, 'CONFIRMED')

    def test_weak_rvol_blocks_confirmation(self):
        e = engine()
        e.ingest_closed_bar(SYM, cd('09:15', 1000, 1004, 998, 1002, 20000), market_dt(DAY, '09:20'))
        e.ingest_closed_bar(SYM, cd('09:20', 1002, 1006, 1001, 1005, 2000), market_dt(DAY, '09:25'))
        self.assertIsNone(e.states[SYM].confirmed_at)

    def test_large_extension_blocks_confirmation(self):
        e = engine()
        e.ingest_closed_bar(SYM, cd('09:15', 1000, 1004, 998, 1002, 20000), market_dt(DAY, '09:20'))
        e.ingest_closed_bar(SYM, cd('09:20', 1002, 1025, 1001, 1020, 30000), market_dt(DAY, '09:25'))
        self.assertIsNone(e.states[SYM].confirmed_at)

    def test_risk_gate_rejects_close_target(self):
        e = engine(highs=[1006])
        e.ingest_closed_bar(SYM, cd('09:15', 1000, 1004, 998, 1002, 20000), market_dt(DAY, '09:20'))
        e.ingest_closed_bar(SYM, cd('09:20', 1002, 1006, 1001, 1005, 30000), market_dt(DAY, '09:25'))
        e.ingest_closed_bar(SYM, cd('09:25', 1005, 1007, 1003.7, 1004.7, 20000), market_dt(DAY, '09:30'))
        self.assertEqual(e.states[SYM].state, 'RISK_FAIL')

    def test_retest_requires_real_target_and_room(self):
        e = engine(highs=[1016])
        e.ingest_closed_bar(SYM, cd('09:15', 1000, 1004, 998, 1002, 20000), market_dt(DAY, '09:20'))
        e.ingest_closed_bar(SYM, cd('09:20', 1002, 1006, 1001, 1005, 30000), market_dt(DAY, '09:25'))
        e.ingest_closed_bar(SYM, cd('09:25', 1005, 1007, 1003.7, 1004.7, 20000), market_dt(DAY, '09:30'))
        self.assertEqual(e.states[SYM].state, 'RETEST_READY')
        self.assertGreater(e.states[SYM].net_rr, 2)

    def test_failed_retest(self):
        e = engine()
        e.ingest_closed_bar(SYM, cd('09:15', 1000, 1004, 998, 1002, 20000), market_dt(DAY, '09:20'))
        e.ingest_closed_bar(SYM, cd('09:20', 1002, 1006, 1001, 1005, 30000), market_dt(DAY, '09:25'))
        e.ingest_closed_bar(SYM, cd('09:25', 1005, 1005.5, 999.5, 1000, 20000), market_dt(DAY, '09:30'))
        self.assertEqual(e.states[SYM].state, 'FAILED')

    def test_stale_feed_fail_closed(self):
        e = engine('LIVE')
        e.ingest_closed_bar(SYM, cd('09:15', 1000, 1004, 998, 1002, 20000), market_dt(DAY, '09:20'))
        old = market_dt(DAY, '09:21')
        e.update_tick(Tick(SYM, 1005, old, 50000, 1002), received_at=market_dt(DAY, '09:24'))
        self.assertIsNone(e.states[SYM].last_tick)
        e.ingest_closed_bar(SYM, cd('09:20', 1002, 1007, 1001, 1005, 30000), market_dt(DAY, '09:25'))
        self.assertIsNone(e.states[SYM].confirmed_at)

    def test_history_no_lookahead_selection(self):
        day0 = date(2026, 10, 1)
        days = [day0 + timedelta(days=i) for i in range(25)]
        data = [Candle(market_dt(d, '09:15'), 1000, 1010, 990, 1000, 1000000)
                for d in days]
        data[-1] = Candle(data[-1].at, 1000, 1500, 1, 1500, 1000000000)
        p = compute_daily_profile(SYM, 'Test', data, days[-1])
        self.assertEqual(p.previous_close, 1000)
        self.assertLess(p.median_turnover_cr, 200)

    def test_baseline_uses_previous_days_only(self):
        past = []
        for i in range(20):
            day = DAY-timedelta(days=i+1)
            past.append(Candle(market_dt(day,'09:20'), 1000, 1004, 997, 1000, 10000))
        past.append(Candle(market_dt(DAY,'09:20'),1000,1004,997,1000,999999))
        b = same_time_baseline(past, DAY)
        self.assertEqual(b['09:20'], 10000)

    def test_selection_limits_and_pin(self):
        cfg=dict(CFG,max_symbols=100,max_industry_members=25,morning_pins=['KEEP'])
        profiles=[Instrument('NSE:KEEP-EQ','Pinned',25,1.4,300,selection_score=1)]
        profiles += [Instrument(f'NSE:T{i}-EQ', f'I{i%10}', 40, 1.7, 400, selection_score=1000-i)
                     for i in range(150)]
        result=choose_top100(profiles,cfg)
        self.assertEqual(len(result),100)
        self.assertEqual(result[0].symbol,'NSE:KEEP-EQ')

    def test_price_filter(self):
        cfg=dict(CFG,max_symbols=2,max_industry_members=10)
        inputs=[Instrument('NSE:A-EQ','A',100,1.6,200,selection_score=100),
                Instrument('NSE:B-EQ','B',100,1.6,199,selection_score=1000),
                Instrument('NSE:C-EQ','C',100,1.6,500,selection_score=80)]
        selected=choose_top100(inputs,cfg)
        self.assertNotIn('NSE:B-EQ',[x.symbol for x in selected])

    def test_demo_100_no_broker_needed(self):
        e=demo_engine(CFG)
        snap=e.snapshot()
        self.assertEqual(snap['monitored'],100)
        self.assertEqual(snap['mode'],'SIMULATION')
        self.assertTrue(any(x['state']=='RETEST_READY' for x in snap['top5']))

    def test_ws_cap_not_exceeded(self):
        self.assertEqual(CFG['max_symbols'],100)

if __name__=='__main__':
    unittest.main()
