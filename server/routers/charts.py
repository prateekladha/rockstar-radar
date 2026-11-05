"""Candlestick data for the in-app chart. Demo generates a deterministic series centred on
the signal's price so overlays line up; live mode will source real candles from the broker."""
from __future__ import annotations
from datetime import timedelta

from fastapi import APIRouter, Depends, Query

from radar.utils import market_dt, now_ist

from ..auth import require_user
from ..models import User

router = APIRouter(tags=['charts'])

TF = {'1m': (375, 1), '5m': (75, 5), '15m': (25, 15), '1d': (60, 1440)}


def _seed(symbol: str) -> int:
    h = 0
    for ch in symbol:
        h = (h * 131 + ord(ch)) & 0xFFFFFFFF
    return h or 1


def _series(symbol: str, base: float, bars: int, step_min: int):
    s = _seed(symbol + str(step_min))
    def nxt():
        nonlocal s
        s = (1103515245 * s + 12345) & 0x7FFFFFFF
        return s / 0x7FFFFFFF
    price = base
    day = now_ist().date()
    if step_min >= 1440:
        start = market_dt(day, '09:15') - timedelta(days=bars)
    else:
        start = market_dt(day, '09:15')
    out = []
    vol_scale = base * 0.0025
    for i in range(bars):
        o = price
        c = max(0.1, o + (nxt() - 0.48) * vol_scale * 2)
        hi = max(o, c) + nxt() * vol_scale
        lo = min(o, c) - nxt() * vol_scale
        t = start + timedelta(minutes=step_min * i)
        out.append({'time': int(t.timestamp()), 'open': round(o, 2), 'high': round(hi, 2),
                    'low': round(lo, 2), 'close': round(c, 2), 'volume': int(10000 + nxt() * 50000)})
        price = c
    return out


@router.get('/api/chart/{symbol}')
def chart(symbol: str, user: User = Depends(require_user),
          tf: str = Query('5m'), base: float = Query(0)):
    bars, step = TF.get(tf, TF['5m'])
    centre = base if base and base > 0 else 200 + (_seed(symbol) % 2000)
    candles = _series(symbol, centre, bars, step)
    first = candles[0]
    return {'symbol': symbol, 'tf': tf, 'candles': candles,
            'or_high': first['high'], 'or_low': first['low']}
