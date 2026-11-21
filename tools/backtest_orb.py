#!/usr/bin/env python3
"""Backtest the ORB strategy over cached historical candles, via the REAL RadarEngine.

Per session it builds the prior-day support/resistance + daily ATR% profile and the same-slot RVOL
baseline from the data, replays the day's 5m candles through RadarEngine (mode SIM), and opens a
trade when a symbol reaches the chosen signal state (RETEST_READY by default, or CONFIRMED). Exits are
static stop/target + 15:15 square-off (the let-winners-run baseline the SMC study validated). Reports
P&L per day/week so ORB can be compared head-to-head with SMC.

Usage:  python3 tools/backtest_orb.py <history.json> [--trigger RETEST_READY|CONFIRMED]
"""
import json
import os
import sys
from collections import defaultdict
from math import floor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from radar.models import Instrument                  # noqa: E402
from radar.engine import RadarEngine, same_time_baseline  # noqa: E402
import backtest as bt                                 # noqa: E402

MAX_RISK = 1960


def to_daily(candles):
    byday = defaultdict(list)
    for c in candles:
        byday[c.at.date()].append(c)
    out = {}
    for d, cs in byday.items():
        cs = sorted(cs, key=lambda x: x.at)
        out[d] = (cs[0].open, max(x.high for x in cs), min(x.low for x in cs), cs[-1].close)
    return out  # date -> (o,h,l,c)


def atr_pct(daily_list, n=14):
    if len(daily_list) < 2:
        return 0.0
    trs = []
    for i in range(1, len(daily_list)):
        h, l, pc = daily_list[i][1], daily_list[i][2], daily_list[i - 1][3]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs[-n:]) / min(n, len(trs))
    lc = daily_list[-1][3]
    return (atr / lc * 100) if lc else 0.0


def run_orb(history, cfg, trigger='RETEST_READY'):
    trades = []
    for sym, candles in history.items():
        byday = defaultdict(list)
        for c in candles:
            byday[c.at.date()].append(c)
        alldays = sorted(byday)
        daily = to_daily(candles)
        for di, day in enumerate(alldays):
            prior = alldays[:di]
            if len(prior) < 10:
                continue
            pd = [daily[d] for d in prior[-20:]]
            inst = Instrument(symbol=sym, daily_atr_pct=atr_pct([daily[d] for d in prior]),
                              previous_close=daily[prior[-1]][3],
                              resistance=sorted(x[1] for x in pd), support=sorted(x[2] for x in pd))
            eng = RadarEngine([inst], cfg, session=day, mode='SIM')
            eng.set_baseline(sym, same_time_baseline(candles, cutoff=day, lookback_sessions=20))
            st = eng.states[sym]
            pos, prev = None, None
            bars = sorted(byday[day], key=lambda x: x.at)
            for bar in bars:
                if pos is not None:
                    res = bt._manage(pos, bar, cfg, use_exit_engine=False)
                    if res is not None:
                        ex, reason = res
                        trades.append({'symbol': sym, 'side': pos.side, 'day': day.isoformat(),
                                       'pnl': bt._close_pnl(pos, ex), 'reason': reason,
                                       'score': pos.score, 'conf': 0, 'sig': None, 'qty': pos.qty})
                        pos = None
                eng.ingest_closed_bar(sym, bar)
                if (pos is None and st.state == trigger and prev != trigger
                        and st.entry and st.stop and st.target and st.side in ('LONG', 'SHORT')):
                    rps = abs(st.entry - st.stop)
                    qty = int(floor(MAX_RISK / rps)) if rps else 0
                    if qty >= 1:
                        pos = bt.Pos(st.side, st.entry, st.stop, st.target, qty, bar.at, st.score, 0)
                prev = st.state
            if pos is not None:
                last = bars[-1]
                trades.append({'symbol': sym, 'side': pos.side, 'day': day.isoformat(),
                               'pnl': bt._close_pnl(pos, last.close), 'reason': 'eod',
                               'score': pos.score, 'conf': 0, 'sig': None, 'qty': pos.qty})
    return trades


def main():
    path = sys.argv[1]
    trig = sys.argv[sys.argv.index('--trigger') + 1] if '--trigger' in sys.argv else 'RETEST_READY'
    cfg = json.loads(open(os.path.join(os.path.dirname(__file__), '..', 'config.json')).read())
    hist = bt.load_history(path)
    print(f'ORB backtest: {len(hist)} symbols, trigger={trig}')
    for trig in ([trig] if '--trigger' in sys.argv else ['RETEST_READY', 'CONFIRMED']):
        tr = run_orb(hist, cfg, trig)
        from datetime import date
        byw = defaultdict(float)
        for t in tr:
            iso = date.fromisoformat(t['day']).isocalendar()
            byw[f'W{iso[1]:02d}'] += t['pnl']
        n = len(tr); w = sum(1 for t in tr if t['pnl'] > 0); tot = sum(t['pnl'] for t in tr)
        wk = ' '.join(f'{k}:{byw[k]/1000:+.0f}k' for k in sorted(byw))
        print(f'  {trig:13} trades={n:4d} win%={100*w//max(n,1):3d} TOTAL=₹{tot:>9,.0f} '
              f'avg₹{tot/max(n,1):>5,.0f} [{wk}]')


if __name__ == '__main__':
    main()
