#!/usr/bin/env python3
"""Fetch NSE 5-minute history from Yahoo Finance for backtesting (public tickers only, no account).

Maps our universe symbols (NSE:XXX-EQ) to Yahoo (XXX.NS), pulls ~1 month of 5m candles, and writes
them in the SMC-history cache format {symbol: [{at,open,high,low,close,volume}, ...]} with IST
timestamps, filtered to the 09:15-15:30 session. For backtest data only — not a live feed.

Usage:  python3 tools/fetch_yahoo.py <symbols_from.json> <out.json> [--range 1mo]
        (<symbols_from.json> provides the universe via its keys; e.g. an existing history file.)
"""
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
UA = {'User-Agent': 'Mozilla/5.0 (backtest-data-fetch)'}


def to_yahoo(sym: str) -> str:
    s = sym.split(':', 1)[1] if ':' in sym else sym      # drop NSE:
    if s.endswith('-EQ'):
        s = s[:-3]
    return s.replace('&', '-') + '.NS'


def fetch(ysym: str, rng: str) -> list:
    url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{ysym}'
           f'?interval=5m&range={rng}')
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        d = json.loads(r.read().decode())
    res = (d.get('chart', {}).get('result') or [None])[0]
    if not res or 'timestamp' not in res:
        return []
    ts = res['timestamp']
    q = res['indicators']['quote'][0]
    out = []
    for i, t in enumerate(ts):
        o, h, l, c, v = q['open'][i], q['high'][i], q['low'][i], q['close'][i], q['volume'][i]
        if None in (o, h, l, c) or v is None:
            continue
        at = datetime.fromtimestamp(t, IST)
        if not ('09:15' <= at.strftime('%H:%M') <= '15:30'):
            continue
        if min(o, h, l, c) <= 0:
            continue
        out.append({'at': at.isoformat(), 'open': round(float(o), 2), 'high': round(float(h), 2),
                    'low': round(float(l), 2), 'close': round(float(c), 2), 'volume': int(v)})
    return out


def main():
    if len(sys.argv) < 3:
        print('usage: fetch_yahoo.py <symbols_from.json> <out.json> [--range 1mo]')
        sys.exit(1)
    src, out_path = sys.argv[1], sys.argv[2]
    rng = sys.argv[sys.argv.index('--range') + 1] if '--range' in sys.argv else '1mo'
    symbols = list(json.loads(open(src, encoding='utf-8').read()).keys())
    print(f'Fetching {len(symbols)} symbols from Yahoo (interval=5m range={rng})...')
    out, ok, fail = {}, 0, 0
    for i, sym in enumerate(symbols, 1):
        ysym = to_yahoo(sym)
        try:
            candles = fetch(ysym, rng)
            if candles:
                out[sym] = candles
                ok += 1
            else:
                fail += 1
        except Exception as e:
            fail += 1
            if fail <= 5:
                print(f'  {sym} -> {ysym}: {type(e).__name__}')
        if i % 20 == 0:
            print(f'  {i}/{len(symbols)}  (ok={ok} fail={fail})')
        time.sleep(0.3)
    json.dump(out, open(out_path, 'w'))
    lens = [len(v) for v in out.values()]
    print(f'wrote {ok} symbols to {out_path}  (fail={fail})')
    if lens:
        days = sorted({c['at'][:10] for v in out.values() for c in v})
        print(f'bars/symbol: min {min(lens)} max {max(lens)}  | {len(days)} trading days: '
              f'{days[0]}..{days[-1]}')


if __name__ == '__main__':
    main()
