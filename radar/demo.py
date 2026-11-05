"""Entirely fabricated NSE-shaped data. Demonstrates UI and signal transitions only."""
from __future__ import annotations
from datetime import date, timedelta
from .engine import RadarEngine
from .models import Candle, Instrument, Tick
from .utils import IST, market_dt, now_ist


def demo_engine(config: dict) -> RadarEngine:
    day = now_ist().date()
    examples = ['NSE:BHARTIARTL-EQ', 'NSE:HINDALCO-EQ',
                'NSE:SBIN-EQ', 'NSE:ICICIBANK-EQ', 'NSE:INFY-EQ']
    symbols = examples + [f'NSE:DEMO{i:03}-EQ' for i in range(1, 96)]
    instruments = []
    for i, sym in enumerate(symbols):
        price = 1000 if i == 0 else (560 if i == 1 else 450 + i * 5)
        instruments.append(Instrument(symbol=sym, industry='Simulation',
            median_turnover_cr=150 if i < 10 else 24, daily_atr_pct=1.7,
            previous_close=price,
            resistance=sorted([price * 1.015, price * 1.035, price * 1.055]),
            support=sorted([price * .97, price * .98])))
    engine = RadarEngine(instruments, config, day, mode='SIMULATION')
    for s in symbols:
        engine.set_baseline(s, {'09:15': 50000, '09:20': 50000,
                                '09:25': 50000, '09:30': 50000})
    engine.update_health('SIMULATED: fabricated candles, NO LIVE FYERS CONNECTION')
    t15 = market_dt(day, '09:15')
    t20 = market_dt(day, '09:20')
    t25 = market_dt(day, '09:25')
    t30 = market_dt(day, '09:30')
    for i, sym in enumerate(symbols):
        price = instruments[i].previous_close
        if i == 0:
            first = Candle(t15, 1000, 1004, 998, 1002, 100000)
            breakout = Candle(t20, 1002, 1006, 1001, 1005, 150000)
            retest = Candle(t25, 1005, 1007, 1003.7, 1004.7, 90000)
            tick = Tick(sym, 1003.6, t20 + timedelta(minutes=2), 150000, 1002.0)
            breach = Tick(sym, 1005, t20 + timedelta(minutes=4), 200000, 1003.0)
            tail = Tick(sym, 1004.7, t30 + timedelta(seconds=3), 350000, 1003.0)
        elif i == 1:
            first = Candle(t15, 560, 563, 557, 560, 120000)
            breakout = Candle(t20, 560, 561, 554, 555, 130000)
            retest = Candle(t25, 555, 557.4, 554.5, 556, 100000)
            tick = Tick(sym, 557.6, t20 + timedelta(minutes=2), 125000, 559.2)
            breach = Tick(sym, 556, t20 + timedelta(minutes=4), 220000, 558)
            tail = Tick(sym, 556, t30 + timedelta(seconds=3), 340000, 558)
        elif i == 2:
            first = Candle(t15, price, price * 1.003, price * .996, price, 85000)
            breakout = Candle(t20, price, price * 1.025, price *.998, price * 1.018, 180000)
            retest = Candle(t25, price * 1.018, price * 1.022, price * 1.014,
                            price * 1.021, 80000)
            tick = Tick(sym, price*1.002, t20+timedelta(minutes=2), 100000, price*1.001)
            breach = Tick(sym, price*1.018, t20+timedelta(minutes=4), 150000, price*1.005)
            tail = Tick(sym, price*1.021, t30+timedelta(seconds=3), 200000, price*1.006)
        elif i == 3:
            first = Candle(t15, price, price * 1.004, price * .997, price, 100000)
            breakout = Candle(t20, price, price * 1.005, price * .998,
                              price * 1.0045, 15000)  # insufficient RVOL
            retest = Candle(t25, price*1.0045, price*1.006, price*1.003,
                            price*1.004, 10000)
            tick = Tick(sym, price*1.003, t20+timedelta(minutes=2), 120000, price*.999)
            breach = Tick(sym, price*1.0045, t20+timedelta(minutes=4), 130000, price*.999)
            tail = Tick(sym, price*1.004, t30+timedelta(seconds=3), 145000, price)
        else:
            first = Candle(t15, price, price * 1.004, price * .997, price*1.002, 70000)
            breakout = Candle(t20, price*1.002, price*1.003, price*.999,
                              price*1.001, 45000)
            retest = Candle(t25, price*1.001, price*1.003, price*.9985,
                            price*1.002, 45000)
            tick = Tick(sym, price*.9993, t20+timedelta(minutes=2), 90000, price*.999)
            breach = Tick(sym, price*1.0001, t20+timedelta(minutes=4), 120000, price)
            tail = Tick(sym, price*1.002, t30+timedelta(seconds=3), 160000, price)
        engine.ingest_closed_bar(sym, first, observed_at=t20+timedelta(seconds=12))
        engine.update_tick(tick, received_at=tick.time)
        engine.update_tick(breach, received_at=breach.time)
        engine.ingest_closed_bar(sym, breakout, observed_at=t25+timedelta(seconds=12))
        engine.update_tick(tail, received_at=tail.time)
        engine.ingest_closed_bar(sym, retest, observed_at=t30+timedelta(seconds=12))
    return engine
