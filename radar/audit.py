"""End-of-day hypothetical follow-through: not fills and not trading profits."""
from __future__ import annotations
import csv
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from .models import Candle
from .utils import IST, ROOT, market_dt, now_ist


def eval_after_signal(side: str, entry: float, stop: float, target: float,
                      from_time: datetime, candles: list[Candle], cost_pct: float,
                      end_time: datetime) -> tuple[str, float | None, float | None]:
    """Simulate an immediate close-price fill AFTER retest completion.

    If stop and target touch in same OHLC interval, assign stop first.
    If no further bars, outcome INCOMPLETE; do not invent a return.
    """
    if not (entry > 0 and stop > 0 and target > 0) or side not in ('LONG','SHORT'):
        return 'INVALID', None, None
    active = [c for c in sorted(candles, key=lambda x: x.at)
              if c.at >= from_time and c.at < end_time and
              c.at + timedelta(minutes=5) <= end_time]
    if not active:
        return 'INCOMPLETE', None, None
    ex_price = None
    result = 'EOD_MARK'
    for c in active:
        stop_hit = (c.low <= stop) if side == 'LONG' else (c.high >= stop)
        target_hit = (c.high >= target) if side == 'LONG' else (c.low <= target)
        if stop_hit:
            result, ex_price = 'STOP_FIRST', stop
            break
        if target_hit:
            result, ex_price = 'TARGET_FIRST', target
            break
    if ex_price is None:
        ex_price = active[-1].close
    cost = entry * cost_pct / 100
    raw = (ex_price - entry) if side == 'LONG' else (entry - ex_price)
    net_risk = abs(entry - stop) + cost
    if net_risk <= 0:
        return 'INVALID', None, None
    r = (raw - cost) / net_risk
    return result, round(ex_price, 2), round(r, 3)


def audit_day(adapter, cfg: dict, day, input_file: Path | None = None,
              output_file: Path | None = None):
    input_file = input_file or ROOT / 'output' / f'signals_{day}.csv'
    output_file = output_file or ROOT / 'output' / f'paper_audit_{day}.csv'
    if not input_file.exists():
        raise ValueError(f'No live signal journal found: {input_file}')
    with input_file.open(newline='',encoding='utf-8') as f:
        events = [r for r in csv.DictReader(f) if r.get('status') == 'RETEST_READY']
    if not events:
        print('No RETEST_READY candidates were logged that day; no paper outcomes to audit.')
        return []
    cutoff = market_dt(day, '15:15')
    outcomes = []
    for e in events:
        try:
            dt = datetime.strptime(e['time_ist'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=IST)
            if dt >= cutoff:
                continue
            from_ep = int((dt - timedelta(minutes=1)).timestamp())
            through_ep = int((market_dt(day, '15:30') - timedelta(seconds=60)).timestamp())
            candles = adapter.history(e['symbol'], '5', from_ep, through_ep)
            status, price, r = eval_after_signal(e['side'], float(e['entry']),
                float(e['stop']), float(e['target']), dt, candles,
                cfg['estimated_roundtrip_cost_pct'], cutoff)
            outcomes.append({'time_ist':e['time_ist'], 'symbol':e['symbol'],
                'side':e['side'], 'entry_est':e['entry'], 'stop_est':e['stop'],
                'target_est':e['target'], 'outcome':status,
                'exit_est':price, 'net_R_est':r})
        except (ValueError, TypeError, KeyError) as ex:
            print(f"Skipped incomplete event {e.get('symbol')}: {ex}")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if outcomes:
        with output_file.open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=list(outcomes[0]))
            writer.writeheader()
            writer.writerows(outcomes)
    valid=[x for x in outcomes if x['net_R_est'] is not None]
    print(f'AUDIT ONLY (unfilled hypothetical close fills, friction={cfg["estimated_roundtrip_cost_pct"]}%):')
    print(f'  Setups: {len(events)} | Evaluated: {len(valid)} | Target-first: '
          f'{sum(x["outcome"] == "TARGET_FIRST" for x in valid)} | '
          f'Stop-first: {sum(x["outcome"] == "STOP_FIRST" for x in valid)}')
    if valid:
        print('  Mean net R (ESTIMATE, NOT P&L):', round(statistics.mean(x['net_R_est'] for x in valid),3))
    print('  File:',output_file)
    print('  WARNING: Historical OHLC lacks intrabar fill sequence. Stop-first is conservative '
          'when both levels touch; actual fills/slippage and delayed alerts may differ.')
    return outcomes
