"""Accelerated synthetic market — a practice/testing feed that runs through the REAL engine.

A sim session (sim_start..sim_end) is replayed at `speed`x via the sim clock (utils.install_sim_clock),
so a full day plays in minutes. Each symbol follows a scripted scenario built from the demo's proven
candle shapes (so the engine actually reaches BREAKOUT/RETEST_READY), then evolves to its target or
stop so paper/auto trades fill and exit. No FYERS, no login — pure simulation.
"""
from __future__ import annotations
import threading
import time as _time
from datetime import timedelta

from .engine import RadarEngine
from .models import Candle, Instrument, Tick
from .utils import market_dt, now_ist

# scenario mix (repeats across the symbol list)
#   'win'  -> LONG breakout, retest, follows through to target
#   'loss' -> LONG breakout, retest, then fails to the stop
#   'short'-> SHORT breakdown, retest, follows through down to target
#   'flat' -> stays inside the opening range (no signal)
_MIX = ['win', 'short', 'loss', 'flat', 'win', 'flat', 'short', 'loss', 'win', 'flat']
_BASE_SYMBOLS = ['SIMINFY', 'SIMSBIN', 'SIMTCS', 'SIMRELI', 'SIMHDFC', 'SIMICICI', 'SIMAXIS',
                 'SIMLT', 'SIMITC', 'SIMWIPRO', 'SIMTATA', 'SIMBHARTI', 'SIMMARUTI', 'SIMSUN',
                 'SIMBAJAJ', 'SIMKOTAK', 'SIMTRENT', 'SIMMCX', 'SIMADANI', 'SIMHIND']


def _scenario(sym: str, base: float, kind: str, bars: list):
    """Per-symbol {bar_dt -> Candle} + [Tick]. Tuned to the engine's gates: breakout close within
    max_extension (0.45%) of the OR boundary, retest dips within retest_tolerance (0.16%) and closes
    back across. bars[0] = opening range. After RETEST_READY, ticks walk the price to target (win) or
    stop (loss) so paper/auto trades fill and exit."""
    b0, b1, b2 = bars[0], bars[1], bars[2]
    rest = bars[3:]
    candles, ticks = {}, []
    r = round

    def tk(price, dt, vol, avp):
        ticks.append(Tick(sym, r(price, 2), dt, vol, r(avp, 2)))

    if kind == 'flat':
        orh, orl = r(base * 1.004, 2), r(base * 0.996, 2)
        candles[b0] = Candle(b0, base, orh, orl, base, 60000)
        for i, bb in enumerate(bars[1:]):
            p = base * (1 + 0.0007 * ((i % 3) - 1))   # wanders inside the range
            candles[bb] = Candle(bb, r(p, 2), r(p * 1.0012, 2), r(p * 0.9988, 2), r(p, 2), 35000)
            tk(p, bb + timedelta(minutes=2), 35000, p)
        return candles, ticks

    if kind == 'short':
        orh, orl = r(base * 1.004, 2), r(base * 0.996, 2)
        candles[b0] = Candle(b0, base, orh, orl, base, 85000)
        # breakdown: close just below ORL (within 0.45%), strong volume
        bclose = base * 0.994      # 0.2% below ORL (0.996) -> extension ~0.2%
        tk(base * 0.997, b1 + timedelta(minutes=1), 120000, base)
        tk(bclose, b1 + timedelta(minutes=3), 200000, base * 0.998)
        candles[b1] = Candle(b1, base, r(base * 0.999, 2), r(base * 0.993, 2), r(bclose, 2), 190000)
        # retest: wick back up near ORL, close below it
        tk(base * 0.9955, b2 + timedelta(seconds=20), 70000, base * 0.997)
        candles[b2] = Candle(b2, r(base * 0.994, 2), r(base * 0.9958, 2), r(base * 0.993, 2), r(base * 0.9955, 2), 80000)
        entry = base * 0.9955
        path = [entry, base * 0.988, base * 0.978, base * 0.970, base * 0.965]   # falls to target
        for i, bb in enumerate(rest):
            p = path[min(i, len(path) - 1)]
            candles[bb] = Candle(bb, r(p * 1.002, 2), r(p * 1.003, 2), r(p, 2), r(p, 2), 60000)
            tk(p, bb + timedelta(minutes=2), 60000, p * 1.002)
        return candles, ticks

    # 'win' / 'loss' — LONG breakout + retest (identical through the retest; diverge after)
    orh, orl = r(base * 1.004, 2), r(base * 0.996, 2)
    candles[b0] = Candle(b0, base, orh, orl, base, 85000)
    bclose = base * 1.006          # 0.2% above ORH (1.004) -> extension ~0.2% (< 0.45%)
    tk(base * 1.003, b1 + timedelta(minutes=1), 120000, base)
    tk(bclose, b1 + timedelta(minutes=3), 200000, base * 1.002)
    candles[b1] = Candle(b1, base, r(base * 1.007, 2), r(base * 1.001, 2), r(bclose, 2), 190000)
    # retest: dip back to just above ORH (within 0.16%), close above
    tk(base * 1.0045, b2 + timedelta(seconds=20), 70000, base * 1.003)
    candles[b2] = Candle(b2, r(base * 1.006, 2), r(base * 1.0065, 2), r(base * 1.0045, 2), r(base * 1.005, 2), 80000)
    entry = base * 1.005
    if kind == 'win':
        path = [entry, base * 1.012, base * 1.022, base * 1.032, base * 1.035]   # climbs to target
    else:  # 'loss' — rolls over through the (wider ATR) stop
        path = [entry, base * 1.002, base * 0.998, base * 0.993, base * 0.990]
    for i, bb in enumerate(rest):
        p = path[min(i, len(path) - 1)]
        candles[bb] = Candle(bb, r(p * 0.998, 2), r(p, 2), r(p * 0.997, 2), r(p, 2), 60000)
        tk(p, bb + timedelta(minutes=2), 60000, p * 0.998)
    return candles, ticks


def _build(config: dict, day):
    sim_start = market_dt(day, config['open_range_start'])
    sim_end = market_dt(day, config.get('sim_end', config['new_signals_stop']))
    bars = []
    b = sim_start
    while b < sim_end:
        bars.append(b)
        b += timedelta(minutes=5)
    if len(bars) < 4:
        bars += [bars[-1] + timedelta(minutes=5 * (i + 1)) for i in range(4 - len(bars))]
    instruments, scenarios = [], {}
    for i, name in enumerate(_BASE_SYMBOLS):
        sym = f'NSE:{name}-EQ'
        base = 300 + i * 37
        kind = _MIX[i % len(_MIX)]
        candles, ticks = _scenario(sym, base, kind, bars)
        instruments.append(Instrument(symbol=sym, industry='Simulation',
            median_turnover_cr=120, daily_atr_pct=1.8, previous_close=base,
            resistance=sorted([round(base * 1.03, 2), round(base * 1.05, 2)]),
            support=sorted([round(base * 0.97, 2), round(base * 0.95, 2)])))
        scenarios[sym] = (candles, ticks)
    return bars, instruments, scenarios


def run_sim(config: dict, port: int):
    """Serve an accelerated simulated session on `port` (same dashboard/state API as the live scanner)."""
    from .dashboard import serve
    day = now_ist().date()
    bars, instruments, scenarios = _build(config, day)
    engine = RadarEngine(instruments, config, day, mode='SIMULATION')
    bl = {b.strftime('%H:%M'): 50000 for b in bars}
    for ins in instruments:
        engine.set_baseline(ins.symbol, bl)
    engine.update_health('SIMULATION — synthetic accelerated feed, not a live market')
    threading.Thread(target=_play, args=(engine, bars, scenarios, config), daemon=True).start()
    serve(engine, port=port, mode='SIMULATION')


def _play(engine: RadarEngine, bars, scenarios, config):
    """Replay the synthetic session continuously (loop) so the sim is always active while enabled:
    each cycle resets the engine, re-anchors the sim clock to the session start, and replays the
    scenario at `speed`x. Opportunities therefore keep appearing, cycle after cycle."""
    from .utils import market_dt, reanchor_sim_clock
    speed = max(1.0, float(config.get('sim_speed', 30)))
    grace = config.get('history_confirmation_grace_seconds', 12)
    day = now_ist().date()
    sim_start = market_dt(day, config['open_range_start'])
    sim_end = market_dt(day, config.get('sim_end', config['new_signals_stop']))
    cycle_secs = max(60.0, (sim_end - sim_start).total_seconds())
    # Events as (offset-seconds-from-session-start, kind, symbol, payload).
    evs = []
    for sym, (candles, ticks) in scenarios.items():
        for t in ticks:
            evs.append(((t.time - sim_start).total_seconds(), 'tick', sym, t))
        for bdt, c in candles.items():
            evs.append(((bdt + timedelta(minutes=5, seconds=grace) - sim_start).total_seconds(), 'bar', sym, c))
    evs.sort(key=lambda e: e[0])

    while True:
        engine.reset()
        engine.update_health('SIMULATION — synthetic accelerated feed, not a live market')
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
