#!/usr/bin/env python3
"""Backtest the SMC auto-trade strategy over cached historical candles.

Replays the REAL strategy bar-by-bar — SMCEngine (zones/OBs/FVG/structure) -> score gate ->
derive_smc_trade_plan -> the Phase-0 adaptive exit engine (breakeven@1R, partial book-half, velocity
time-decay to 15:00) — and reports P&L per day and per week. Also runs a STATIC-exit baseline (plain
stop/target, no exit engine) so the exit engine's impact is visible.

Stdlib-only; runs with system python3. Data = the SMC history cache
(data/smc_history_<date>_<bar>m.json): {symbol: [{at,open,high,low,close,volume}, ...]}.

Usage:  python3 tools/backtest.py <history.json> [--min-score 80] [--capital 196000] [--risk 1.0]
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from math import floor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from radar.models import Candle, Tick, Instrument            # noqa: E402
from radar.smc_engine import SMCEngine                        # noqa: E402
from radar import confluence, indicators                      # noqa: E402
from server import exit_engine                                # noqa: E402

WARMUP = 101            # candles the SMC engine needs before it emits opportunities
MIN_RR = 2.0           # net reward:risk gate (mirrors config min_net_reward_risk)


# ----------------------------------------------------------------------------- data
def load_history(path: str) -> dict:
    raw = json.loads(open(path, encoding='utf-8').read())
    out = {}
    for sym, arr in raw.items():
        cs = []
        for c in (arr or []):
            if not c:
                continue
            try:
                cs.append(Candle(at=datetime.fromisoformat(c['at']), open=c['open'], high=c['high'],
                                 low=c['low'], close=c['close'], volume=c['volume']))
            except Exception:
                continue
        if len(cs) > WARMUP:
            out[sym] = sorted(cs, key=lambda x: x.at)
    return out


# ----------------------------------------------------------------------------- sim position
class Pos:
    __slots__ = ('side', 'entry', 'stop', 'target', 'init_stop', 'qty', 'opened_at',
                 'be_moved', 'booked_qty', 'booked_pnl', 'score', 'conf')

    def __init__(self, side, entry, stop, target, qty, opened_at, score, conf):
        self.side, self.entry, self.stop, self.target = side, entry, stop, target
        self.init_stop, self.qty, self.opened_at = stop, qty, opened_at
        self.be_moved, self.booked_qty, self.booked_pnl = 0, 0, 0.0
        self.score, self.conf = score, conf


def _close_pnl(p: Pos, exit_price: float) -> float:
    direction = 1 if p.side == 'LONG' else -1
    runner_qty = p.qty - p.booked_qty
    return round((exit_price - p.entry) * runner_qty * direction + p.booked_pnl, 2)


def _manage(p: Pos, bar: Candle, cfg: dict, use_exit_engine: bool):
    """Step an open position against one bar. Returns (exit_price, reason) or None.
    OHLC approximation: breakeven/partial use the bar's favourable excursion, then stop/target are
    checked against the adverse/favourable extremes (stop assumed first if both hit)."""
    fav_px = bar.high if p.side == 'LONG' else bar.low        # best-case excursion this bar
    adv_px = bar.low if p.side == 'LONG' else bar.high        # worst-case excursion this bar
    hhmm = bar.at.strftime('%H:%M')

    if use_exit_engine:
        be_r = float(cfg.get('exit_breakeven_at_r', 1.0) or 0)
        part_frac = float(cfg.get('exit_partial_frac', 0.5) or 0)
        part_r = float(cfg.get('exit_partial_at_r', 1.0) or 0)
        # partial book-half at +part_r (book at the +part_r price), move stop to breakeven
        if (part_frac > 0 and part_r > 0 and not p.booked_qty
                and exit_engine.reached_r(p.side, p.entry, p.init_stop, fav_px, part_r)):
            bq = int(floor(p.qty * part_frac))
            if bq >= 1:
                rd = exit_engine.r_distance(p.entry, p.init_stop)
                book_px = p.entry + (part_r * rd if p.side == 'LONG' else -part_r * rd)
                p.booked_qty = bq
                p.booked_pnl = round((book_px - p.entry) * bq * (1 if p.side == 'LONG' else -1), 2)
                p.stop = p.entry
                p.be_moved = 1
        if be_r > 0 and not p.be_moved and exit_engine.reached_r(p.side, p.entry, p.init_stop, fav_px, be_r):
            p.stop = p.entry
            p.be_moved = 1
        # velocity governor (book remaining at close)
        elapsed_min = (bar.at - p.opened_at).total_seconds() / 60.0
        if bool(cfg.get('exit_velocity_governor', True)) and exit_engine.velocity_exit(
                p.side, p.entry, bar.close, p.target, elapsed_min, bar.at,
                str(cfg.get('exit_mgmt_cutoff', '15:00')), float(cfg.get('exit_velocity_slack', 1.5) or 1.5)):
            return bar.close, 'velocity'

    # stop / target (stop may now be breakeven)
    if p.side == 'LONG':
        if adv_px <= p.stop:
            return p.stop, 'stop'
        if fav_px >= p.target:
            return p.target, 'target'
    else:
        if adv_px >= p.stop:
            return p.stop, 'stop'
        if fav_px <= p.target:
            return p.target, 'target'
    # intraday square-off
    if hhmm >= '15:15':
        return bar.close, 'squareoff'
    return None


def _confluence_for(state, side) -> float:
    """A demonstrative confluence score from readily-available state (RSI + zone/OB/FVG/structure)."""
    opp = state.opportunity
    closes = [c.close for c in state.candles]
    rsi = indicators.rsi(closes, 14)
    sig = {
        'side': side,
        'zone_strength': 0.8 if opp and opp.zone in ('DISCOUNT', 'PREMIUM') else 0.3,
        'ob_strength': 0.8 if (opp and opp.trade and opp.trade.get('in_fresh_ob')) else 0.0,
        'fvg_strength': 0.0,
        'structure': 1 if (state.structures and state.structures[-1].bias ==
                           ('BULLISH' if side == 'LONG' else 'BEARISH')) else 0,
        'rvol': None,
        'rsi': rsi,
        'vp_support': 0.5,
    }
    return confluence.confluence_score(sig)['score']


# ----------------------------------------------------------------------------- backtest
def run(history: dict, cfg: dict, min_score: int, max_risk: float, use_exit_engine: bool) -> list[dict]:
    """Returns a list of closed-trade dicts."""
    trades = []
    max_tps = int(cfg.get('max_trades_per_symbol', 4) or 4)
    for sym, candles in history.items():
        eng = SMCEngine([Instrument(symbol=sym)], cfg)
        eng.load_historical_candles(sym, candles[:WARMUP])
        state = eng.states[sym]
        pos = None
        trades_today = defaultdict(int)
        for bar in candles[WARMUP:]:
            day = bar.at.date().isoformat()
            # 1) manage an open position against this bar
            if pos is not None:
                res = _manage(pos, bar, cfg, use_exit_engine)
                if res is not None:
                    exit_px, reason = res
                    trades.append({'symbol': sym, 'side': pos.side, 'day': day,
                                   'at': bar.at, 'pnl': _close_pnl(pos, exit_px), 'reason': reason,
                                   'score': pos.score, 'conf': pos.conf, 'qty': pos.qty})
                    pos = None
            # 2) advance the engine with this bar, update the opportunity
            eng.process_candle(sym, bar)
            eng.process_tick(sym, Tick(symbol=sym, price=bar.close, time=bar.at))
            # 3) consider a new entry (flat, in window, under cap)
            if pos is None and bar.at.strftime('%H:%M') < '15:00' and trades_today[day] < max_tps:
                opp = state.opportunity
                if opp and (opp.score or 0) >= min_score and opp.trade:
                    pl = opp.trade
                    side, e, s, t, rr = (pl.get('side'), pl.get('entry'), pl.get('stop'),
                                         pl.get('target'), pl.get('rr'))
                    if side in ('LONG', 'SHORT') and e and s and t and rr is not None and rr >= MIN_RR:
                        rps = abs(e - s)
                        qty = int(floor(max_risk / rps)) if rps else 0
                        if qty >= 1:
                            pos = Pos(side, e, s, t, qty, bar.at, opp.score,
                                      _confluence_for(state, side))
                            trades_today[day] += 1
        # square off any position left open at dataset end
        if pos is not None:
            last = candles[-1]
            trades.append({'symbol': sym, 'side': pos.side, 'day': last.at.date().isoformat(),
                           'at': last.at, 'pnl': _close_pnl(pos, last.close), 'reason': 'eod',
                           'score': pos.score, 'conf': pos.conf, 'qty': pos.qty})
    return trades


def report(trades: list[dict], label: str):
    by_day = defaultdict(float)
    by_week = defaultdict(float)
    wins = sum(1 for t in trades if t['pnl'] > 0)
    total = round(sum(t['pnl'] for t in trades), 2)
    for t in trades:
        by_day[t['day']] += t['pnl']
        iso = datetime.fromisoformat(t['day']).isocalendar()
        by_week[f'{iso[0]}-W{iso[1]:02d}'] += t['pnl']
    print(f'\n===== {label} =====')
    print(f'trades={len(trades)}  wins={wins}  win%={(100*wins/len(trades) if trades else 0):.0f}  '
          f'TOTAL P&L=₹{total:,.0f}')
    print('-- per day --')
    for d in sorted(by_day):
        print(f'  {d}:  ₹{by_day[d]:>12,.0f}')
    print('-- per week --')
    for w in sorted(by_week):
        print(f'  {w}:  ₹{by_week[w]:>12,.0f}')
    return total


def main():
    args = sys.argv[1:]
    if not args:
        print('usage: backtest.py <history.json> [--min-score N] [--capital N] [--risk PCT]')
        sys.exit(1)
    path = args[0]
    def opt(name, default):
        return float(args[args.index(name) + 1]) if name in args else default
    min_score = int(opt('--min-score', 80))
    capital = opt('--capital', 196000)
    risk_pct = opt('--risk', 1.0)
    max_risk = capital * risk_pct / 100.0
    cfg = json.loads(open(os.path.join(os.path.dirname(__file__), '..', 'config.json')).read())

    history = load_history(path)
    print(f'Loaded {len(history)} symbols with >{WARMUP} candles from {path}')
    print(f'min_score={min_score}  capital=₹{capital:,.0f}  risk={risk_pct}%  '
          f'(₹{max_risk:,.0f}/trade)  MIN_RR={MIN_RR}')

    adaptive = run(history, cfg, min_score, max_risk, use_exit_engine=True)
    static = run(history, cfg, min_score, max_risk, use_exit_engine=False)
    a = report(adaptive, 'ADAPTIVE EXITS (breakeven + partial + velocity)')
    s = report(static, 'STATIC EXITS (plain stop/target) — baseline')
    print(f'\n>>> exit engine impact: ₹{a - s:,.0f}  (adaptive ₹{a:,.0f} vs static ₹{s:,.0f})')


if __name__ == '__main__':
    main()
