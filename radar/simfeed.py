"""Accelerated synthetic market — a practice/testing feed that runs through the REAL engine.

A sim session (sim_start..sim_end) is replayed at `speed`x via the sim clock and LOOPS continuously.
Each cycle is freshly randomised: ~35% of stocks don't set up; of those that do, breakouts are LONG or
SHORT and only ~40% follow through to target (the rest hit the stop) — like a real opening-range
strategy, so the equity curve goes up AND down. Entries are staggered through the session and the
follow-through is gradual over several bars, so positions stay open long enough to watch.
No FYERS, no login — pure simulation.
"""
from __future__ import annotations
import os
import random
import threading
import time as _time
from datetime import timedelta

from .engine import RadarEngine
from .models import Candle, Instrument, Tick
from .utils import market_dt, now_ist, signal_bar_minutes

_BASE_SYMBOLS = ['SIMINFY', 'SIMSBIN', 'SIMTCS', 'SIMRELI', 'SIMHDFC', 'SIMICICI', 'SIMAXIS',
                 'SIMLT', 'SIMITC', 'SIMWIPRO', 'SIMTATA', 'SIMBHARTI', 'SIMMARUTI', 'SIMSUN',
                 'SIMBAJAJ', 'SIMKOTAK', 'SIMTRENT', 'SIMMCX', 'SIMADANI', 'SIMHIND']
_FLAT_PROB = 0.35     # fraction of stocks that never break out
_WIN_PROB = 0.48      # of the breakouts that confirm+retest, how many reach target (rest hit stop).
                      # ~40% realised win rate × ~2.2R target : 1R stop => modest positive expectancy.

# Gradual follow-through paths (price as a fraction of base), consumed one per bar after the retest.
# LONG: target = base*1.03, stop ~ base*0.996 (ATR). SHORT: target = base*0.97, stop ~ base*1.004.
# Every path's FIRST step must cross the entry so the order fills (a LONG fills when price ≥ entry≈
# base·1.005, a SHORT when price ≤ entry≈base·0.9955) — THEN it runs to target (win) or reverses to
# the stop (loss). Otherwise a loser never fills and the sim shows a fake 100% win rate.
_PATH = {
    'win':   [1.007, 1.011, 1.016, 1.021, 1.026, 1.030, 1.032],
    'loss':  [1.007, 1.004, 1.001, 0.999, 0.995, 0.992],         # fills, then rolls to stop (~0.996)
    'swin':  [0.993, 0.989, 0.984, 0.979, 0.974, 0.970, 0.968],
    'sloss': [0.9945, 0.997, 1.000, 1.002, 1.005, 1.008],        # fills, then rallies to stop (~1.004)
}


def _or_candles(bars: list, base: float, orh: float, orl: float, volume: int) -> dict:
    """The opening-range window, spread across however many bars cover it.

    On the 5-minute setting that is one candle, exactly as before. On 1-minute it is five, and the
    extremes are placed on the first and last so the merged range still comes out at orh/orl —
    otherwise the sim would never reproduce the range the engine is supposed to find.
    """
    n = len(bars)
    per = max(1, volume // n)
    out = {}
    for i, b in enumerate(bars):
        high = orh if i == 0 else round(base * 1.002, 2)
        low = orl if i == n - 1 else round(base * 0.998, 2)
        out[b] = Candle(b, base, max(high, base), min(low, base), base, per)
    return out


def _flat(sym: str, base: float, bars: list, or_n: int, scale: float, tick_at):
    orh, orl = round(base * 1.004, 2), round(base * 0.996, 2)
    candles = _or_candles(bars[:or_n], base, orh, orl, int(60000 * scale))
    ticks = []
    for i, b in enumerate(bars[or_n:]):
        p = base * (1 + 0.0007 * ((i % 3) - 1))
        vol = int(32000 * scale)
        candles[b] = Candle(b, round(p, 2), round(p * 1.0012, 2), round(p * 0.9988, 2), round(p, 2), vol)
        ticks.append(Tick(sym, round(p, 2), tick_at(b, 2), vol, round(p, 2)))
    return candles, ticks


def _one(sym: str, base: float, eb: int, kind: str, bars: list, or_n: int, scale: float, tick_at):
    """Breakout at bar `eb`, retest at eb+1, then the gradual follow-through for `kind`."""
    r = round
    v = lambda n: int(n * scale)
    orh, orl = r(base * 1.004, 2), r(base * 0.996, 2)
    candles = _or_candles(bars[:or_n], base, orh, orl, v(85000))
    ticks = []
    # pre-breakout bars sit inside the opening range (no signal), so entries can be staggered.
    for i in range(or_n, eb):
        candles[bars[i]] = Candle(bars[i], base, r(base * 1.001, 2), r(base * 0.999, 2), base, v(30000))
    bb, rb = bars[eb], bars[eb + 1]
    rest = bars[eb + 2:]
    long_ = kind in ('win', 'loss')
    if long_:
        ticks.append(Tick(sym, r(base * 1.003, 2), tick_at(bb, 1), v(120000), r(base, 2)))
        ticks.append(Tick(sym, r(base * 1.006, 2), tick_at(bb, 3), v(200000), r(base * 1.002, 2)))
        candles[bb] = Candle(bb, base, r(base * 1.007, 2), r(base * 1.001, 2), r(base * 1.006, 2), v(190000))
        ticks.append(Tick(sym, r(base * 1.0045, 2), tick_at(rb, 1 / 3), v(70000), r(base * 1.003, 2)))
        candles[rb] = Candle(rb, r(base * 1.006, 2), r(base * 1.0065, 2), r(base * 1.0045, 2), r(base * 1.005, 2), v(80000))
    else:  # SHORT
        ticks.append(Tick(sym, r(base * 0.997, 2), tick_at(bb, 1), v(120000), r(base, 2)))
        ticks.append(Tick(sym, r(base * 0.994, 2), tick_at(bb, 3), v(200000), r(base * 0.998, 2)))
        candles[bb] = Candle(bb, base, r(base * 0.999, 2), r(base * 0.993, 2), r(base * 0.994, 2), v(190000))
        ticks.append(Tick(sym, r(base * 0.9955, 2), tick_at(rb, 1 / 3), v(70000), r(base * 0.997, 2)))
        candles[rb] = Candle(rb, r(base * 0.994, 2), r(base * 0.9958, 2), r(base * 0.993, 2), r(base * 0.9955, 2), v(80000))
    path = _PATH[kind]
    for i, b in enumerate(rest):
        f = path[min(i, len(path) - 1)]
        p = r(base * f, 2)
        candles[b] = Candle(b, r(base * (f + (0.001 if long_ else -0.001)), 2),
                            r(base * (f + 0.0015), 2), r(base * (f - 0.0015), 2), p, v(55000))
        ticks.append(Tick(sym, p, tick_at(b, 2), v(55000), r(base * f, 2)))
    return candles, ticks


def _make_scenarios(instruments, bars, rng, or_n: int, scale: float, tick_at):
    """A freshly randomised set of per-symbol scenarios for one replay cycle."""
    scenarios = {}
    # Breakouts can only start once the opening range is complete, and must leave room for the
    # retest bar plus some follow-through before the session ends.
    max_eb = max(or_n, min(or_n + 3, len(bars) - 6))
    for ins in instruments:
        base = ins.previous_close
        if rng.random() < _FLAT_PROB:
            scenarios[ins.symbol] = _flat(ins.symbol, base, bars, or_n, scale, tick_at)
            continue
        eb = rng.randint(or_n, max_eb)
        long_ = rng.random() < 0.5
        win = rng.random() < _WIN_PROB
        kind = ('win' if win else 'loss') if long_ else ('swin' if win else 'sloss')
        scenarios[ins.symbol] = _one(ins.symbol, base, eb, kind, bars, or_n, scale, tick_at)
    return scenarios


def _bars(config: dict, day):
    bar_minutes = signal_bar_minutes(config)
    sim_start = market_dt(day, config['open_range_start'])
    sim_end = market_dt(day, config.get('sim_end', config['new_signals_stop']))
    step = timedelta(minutes=bar_minutes)
    bars, b = [], sim_start
    while b < sim_end:
        bars.append(b)
        b += step
    # Enough bars for the opening range, a setup and its follow-through.
    minimum = max(10, (config.get('open_range_minutes', 5) // bar_minutes) + 9)
    while len(bars) < minimum:
        bars.append(bars[-1] + step)
    return bars


def _instruments():
    out = []
    for i, name in enumerate(_BASE_SYMBOLS):
        base = 300 + i * 37
        out.append(Instrument(symbol=f'NSE:{name}-EQ', industry='Simulation',
            median_turnover_cr=120, daily_atr_pct=1.8, previous_close=base,
            resistance=sorted([round(base * 1.03, 2), round(base * 1.05, 2)]),
            support=sorted([round(base * 0.97, 2), round(base * 0.95, 2)])))
    return out


def run_sim(config: dict, port: int):
    """Serve an accelerated simulated session (same /api/state as live). Plays once start..sim_end
    then holds the final state (one pass); set sim_loop=True to replay forever instead."""
    from .dashboard import serve
    day = now_ist().date()
    bars = _bars(config, day)
    instruments = _instruments()

    def on_signal(sig):
        """Rehearse the live Telegram path without a broker. OPT-IN: an accelerated session fires
        dozens of signals in minutes, so merely switching practice mode on must never flood a
        phone. Every message is stamped as practice so it cannot be mistaken for a real setup."""
        if os.environ.get('RADAR_SIM_TELEGRAM') != '1':
            return
        try:
            from .notify import notify_signal
            notify_signal(sig, config, simulated=True)
        except Exception as e:      # a notifier failure must never break the simulation
            print(f'Sim Telegram notify failed: {type(e).__name__}: {e}')

    engine = RadarEngine(instruments, config, day, mode='SIMULATION', on_signal=on_signal)
    # Baseline scales with the bar, exactly as the synthetic volumes do, so RVOL — and therefore
    # which setups confirm — is identical whichever interval the practice session runs at.
    bl = {b.strftime('%H:%M'): int(50000 * engine.bar_minutes / 5) for b in bars}
    for ins in instruments:
        engine.set_baseline(ins.symbol, bl)
    engine.update_health('SIMULATION — synthetic accelerated feed, not a live market')
    threading.Thread(target=_play, args=(engine, bars, instruments, config), daemon=True).start()
    serve(engine, port=port, mode='SIMULATION')


def _play(engine: RadarEngine, bars, instruments, config):
    """Replay the simulated session (start..sim_end) once at `speed`x, then STOP — the sim ends like a
    real intraday session (play_through, one pass). The server serves the final frozen state; open
    positions are squared off at session end by the order engine. Set sim_loop=True to replay forever
    instead (the old 'always something to watch' behaviour)."""
    from .utils import market_dt, reanchor_sim_clock
    loop = bool(config.get('sim_loop', False))
    speed = max(1.0, float(config.get('sim_speed', 10)))
    grace = config.get('history_confirmation_grace_seconds', 12)
    bar_minutes = engine.bar_minutes
    or_n = engine.or_bar_count
    scale = bar_minutes / 5          # synthetic volume per bar, pro-rated to the bar's length
    # Ticks must land inside the bar that carries them; offsets are written in 5-minute terms, so
    # on a shorter bar they compress by the same ratio instead of spilling into the next one.
    def tick_at(bar_dt, minutes_in_5m):
        return bar_dt + timedelta(seconds=minutes_in_5m * 60 * scale)
    day = now_ist().date()
    sim_start = market_dt(day, config['open_range_start'])
    sim_end = market_dt(day, config.get('sim_end', config['new_signals_stop']))
    cycle_secs = max(60.0, (sim_end - sim_start).total_seconds())
    rng = random.Random()
    while True:
        engine.reset()
        engine.update_health('SIMULATION — synthetic accelerated feed, not a live market')
        scenarios = _make_scenarios(instruments, bars, rng, or_n, scale, tick_at)
        evs = []
        for sym, (candles, ticks) in scenarios.items():
            for t in ticks:
                evs.append(((t.time - sim_start).total_seconds(), 'tick', sym, t))
            for bdt, c in candles.items():
                evs.append(((bdt + timedelta(minutes=bar_minutes, seconds=grace)
                             - sim_start).total_seconds(), 'bar', sym, c))
        evs.sort(key=lambda e: e[0])
        reanchor_sim_clock()
        cycle_start = _time.monotonic()
        for off, kind, sym, payload in evs:
            target = cycle_start + max(0.0, off) / speed
            while _time.monotonic() < target:
                _time.sleep(min(max(target - _time.monotonic(), 0.02), 0.5))
            try:
                if kind == 'tick':
                    engine.update_tick(payload, received_at=now_ist())
                else:
                    engine.ingest_closed_bar(sym, payload, observed_at=now_ist())
            except Exception as e:
                print(f'sim ingest error {sym}: {e}')
        end_real = cycle_start + cycle_secs / speed
        while _time.monotonic() < end_real:
            _time.sleep(0.5)
        if not loop:
            # One pass done: leave the sim clock past sim_end so snapshot.session_closed stays True,
            # and hold the final state. (Re-enabling simulation or Reset starts a fresh session.)
            engine.update_health('SIMULATION — session complete. Toggle simulation off then on, '
                                 'or Reset, to run another session.')
            return
