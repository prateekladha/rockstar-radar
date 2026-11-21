#!/usr/bin/env python3
"""Backtest the SMC auto-trade strategy over cached historical candles.

Replays the REAL strategy bar-by-bar — SMCEngine (zones/OBs/FVG/structure) -> score gate ->
derive_smc_trade_plan -> exits — and reports P&L per day/week. Supports:
  - exit style: adaptive (exit engine) vs static (plain stop/target);
  - entry mode: 'raw' (SMC score gate only) vs 'confluence' (also require the Phase-2 weighted
    confluence score >= a threshold, computed from RSI + cumulative RVOL + volume profile + zone/OB/
    structure) — i.e. does the confluence layer improve entry quality?

Stdlib-only. Data = SMC history cache: {symbol: [{at,open,high,low,close,volume}, ...]}.

Usage:  python3 tools/backtest.py <history.json> [--min-score 80] [--capital N] [--risk PCT]
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
from radar import confluence, indicators, volume_profile, rvol_cum  # noqa: E402
from server import exit_engine                                # noqa: E402

WARMUP = 101
MIN_RR = 2.0
RVOL_MIN_DAYS = 2        # limited history window -> allow rvol with few prior sessions


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


def _day_slots(candles: list[Candle]):
    """Per-bar day string + slot-within-day index, plus {day: [volumes...]} for cumulative RVOL."""
    days, slots = [], []
    by_day_vol = defaultdict(list)
    counter = defaultdict(int)
    for c in candles:
        d = c.at.date().isoformat()
        days.append(d)
        slots.append(counter[d])
        by_day_vol[d].append(c.volume)
        counter[d] += 1
    return days, slots, by_day_vol


# ----------------------------------------------------------------------------- signals
def compute_signals(state, side, candles, i, days, slots, by_day_vol) -> dict:
    """Confluence inputs for a candidate entry at bar i (from engine state + data)."""
    opp = state.opportunity
    closes = [c.close for c in state.candles]
    rsi = indicators.rsi(closes, 14)

    # cumulative RVOL-at-time: today's cum vs prior days' cum at the same slot
    d, slot = days[i], slots[i]
    today_vols = by_day_vol[d][:slot + 1]
    prior = [v for dd, v in by_day_vol.items() if dd < d]
    rvol = rvol_cum.rvol_cumulative(today_vols, prior, idx=slot, min_days=RVOL_MIN_DAYS)

    # volume profile over today's candles so far
    day_start = i - slot
    vp = volume_profile.volume_profile(candles[day_start:i + 1], bins=20)
    price = candles[i].close
    vp_support = 0.5
    if vp:
        if side == 'LONG':
            vp_support = 1.0 if price <= vp['val'] else (0.6 if price <= vp['poc'] else 0.2)
        else:
            vp_support = 1.0 if price >= vp['vah'] else (0.6 if price >= vp['poc'] else 0.2)

    trend = getattr(state, 'trend', 'NEUTRAL')
    return {
        'side': side,
        'zone_strength': 0.8 if (opp and opp.zone in ('DISCOUNT', 'PREMIUM')) else 0.3,
        'ob_strength': 0.8 if (opp and opp.trade and opp.trade.get('in_fresh_ob')) else 0.0,
        'fvg_strength': 0.0,
        'structure': 1 if trend == ('BULLISH' if side == 'LONG' else 'BEARISH') else 0,
        'rvol': rvol,
        'rsi': rsi,
        'vp_support': vp_support,
    }


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
    fav_px = bar.high if p.side == 'LONG' else bar.low
    adv_px = bar.low if p.side == 'LONG' else bar.high
    if use_exit_engine:
        be_r = float(cfg.get('exit_breakeven_at_r', 0) or 0)
        part_frac = float(cfg.get('exit_partial_frac', 0) or 0)
        part_r = float(cfg.get('exit_partial_at_r', 1.0) or 0)
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
        elapsed_min = (bar.at - p.opened_at).total_seconds() / 60.0
        if bool(cfg.get('exit_velocity_governor', False)) and exit_engine.velocity_exit(
                p.side, p.entry, bar.close, p.target, elapsed_min, bar.at,
                str(cfg.get('exit_mgmt_cutoff', '15:00')), float(cfg.get('exit_velocity_slack', 1.5) or 1.5)):
            return bar.close, 'velocity'
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
    if bar.at.strftime('%H:%M') >= '15:15':
        return bar.close, 'squareoff'
    return None


# ----------------------------------------------------------------------------- backtest
def run(history, cfg, min_score, max_risk, use_exit_engine=True, entry_mode='raw', conf_min=0) -> list:
    trades = []
    max_tps = int(cfg.get('max_trades_per_symbol', 4) or 4)
    for sym, candles in history.items():
        days, slots, by_day_vol = _day_slots(candles)
        eng = SMCEngine([Instrument(symbol=sym)], cfg)
        eng.load_historical_candles(sym, candles[:WARMUP])
        state = eng.states[sym]
        pos, trades_today = None, defaultdict(int)
        for i in range(WARMUP, len(candles)):
            bar = candles[i]
            day = days[i]
            if pos is not None:
                res = _manage(pos, bar, cfg, use_exit_engine)
                if res is not None:
                    ex, reason = res
                    trades.append({'symbol': sym, 'side': pos.side, 'day': day, 'at': bar.at,
                                   'pnl': _close_pnl(pos, ex), 'reason': reason,
                                   'score': pos.score, 'conf': pos.conf, 'qty': pos.qty})
                    pos = None
            eng.process_candle(sym, bar)
            eng.process_tick(sym, Tick(symbol=sym, price=bar.close, time=bar.at))
            if pos is None and bar.at.strftime('%H:%M') < '15:00' and trades_today[day] < max_tps:
                opp = state.opportunity
                if opp and (opp.score or 0) >= min_score and opp.trade:
                    pl = opp.trade
                    side, e, s, t, rr = (pl.get('side'), pl.get('entry'), pl.get('stop'),
                                         pl.get('target'), pl.get('rr'))
                    if side in ('LONG', 'SHORT') and e and s and t and rr is not None and rr >= MIN_RR:
                        conf = confluence.confluence_score(
                            compute_signals(state, side, candles, i, days, slots, by_day_vol))['score']
                        if entry_mode == 'confluence' and conf < conf_min:
                            continue
                        rps = abs(e - s)
                        qty = int(floor(max_risk / rps)) if rps else 0
                        if qty >= 1:
                            pos = Pos(side, e, s, t, qty, bar.at, opp.score, conf)
                            trades_today[day] += 1
        if pos is not None:
            last = candles[-1]
            trades.append({'symbol': sym, 'side': pos.side, 'day': last.at.date().isoformat(),
                           'at': last.at, 'pnl': _close_pnl(pos, last.close), 'reason': 'eod',
                           'score': pos.score, 'conf': pos.conf, 'qty': pos.qty})
    return trades


def summary(trades):
    wins = sum(1 for t in trades if t['pnl'] > 0)
    total = round(sum(t['pnl'] for t in trades), 0)
    by_day = defaultdict(float)
    for t in trades:
        by_day[t['day']] += t['pnl']
    return len(trades), wins, total, dict(by_day)


def main():
    args = sys.argv[1:]
    if not args:
        print('usage: backtest.py <history.json> [--min-score N] [--capital N] [--risk PCT]')
        sys.exit(1)
    path = args[0]
    def opt(n, d):
        return float(args[args.index(n) + 1]) if n in args else d
    min_score = int(opt('--min-score', 80))
    capital, risk = opt('--capital', 196000), opt('--risk', 1.0)
    max_risk = capital * risk / 100.0
    cfg = json.loads(open(os.path.join(os.path.dirname(__file__), '..', 'config.json')).read())
    history = load_history(path)
    print(f'Loaded {len(history)} symbols from {path}  |  score>={min_score}  ₹{max_risk:.0f}/trade\n')

    experiments = [
        ('STATIC raw entry',              dict(use_exit_engine=False, entry_mode='raw')),
        ('STATIC + confluence>=60 entry', dict(use_exit_engine=False, entry_mode='confluence', conf_min=60)),
        ('STATIC + confluence>=70 entry', dict(use_exit_engine=False, entry_mode='confluence', conf_min=70)),
        ('ADAPTIVE raw entry',            dict(use_exit_engine=True, entry_mode='raw')),
    ]
    print(f'{"experiment":34} {"trades":>7} {"win%":>5} {"P&L":>12}')
    for label, kw in experiments:
        n, w, tot, _ = summary(run(history, cfg, min_score, max_risk, **kw))
        print(f'{label:34} {n:>7} {(100*w//max(n,1)):>4}% ₹{tot:>11,.0f}')


if __name__ == '__main__':
    main()
