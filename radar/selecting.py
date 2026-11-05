"""Pre-open NSE NIFTY 500 -> filtered liquid 100 using ONLY prior completed sessions."""
from __future__ import annotations
import csv
import json
import math
import re
import statistics
import time
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from .models import Candle, Instrument
from .fyers import ApiAuthError, ApiPermissionError, ApiProviderError, ApiRateLimitError
from .utils import IST, ROOT, market_dt, now_ist, safe_float


class SelectionError(RuntimeError):
    pass


def normalize_morning_symbol(value: str) -> str:
    """Accept an NSE EQ ticker or FYERS NSE:XXX-EQ; reject ambiguous instruments."""
    value = value.strip().upper()
    if value.startswith('NSE:'):
        value = value[4:]
    if value.endswith(('-FUT', '-CE', '-PE', '-BE', '-BZ')):
        raise SelectionError(f'Only NSE equity EQ tickers are supported: {value!r}')
    if value.endswith('-EQ'):
        value = value[:-3]
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9&._-]{0,29}', value):
        raise SelectionError(f'Invalid NSE equity ticker in morning list: {value!r}')
    return f'NSE:{value}-EQ'


def load_morning_pins(config: dict, path: Path | None = None) -> list[str]:
    """Merge built-in pins and a paste-friendly daily text file, preserving order."""
    path = path or ROOT / 'data' / 'morning_rockstars.txt'
    tokens = list(config.get('morning_pins') or [])
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.split('#', 1)[0].strip()
            if line:
                tokens.extend(re.split(r'[,\s]+', line))
    result = []
    seen = set()
    for token in tokens:
        if not token:
            continue
        canonical = normalize_morning_symbol(token)
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    if len(result) > min(config.get('max_symbols', 100), 100):
        raise SelectionError('Morning watchlist exceeds FYERS Standard 100-symbol limit. '
                             'Remove some picks before running the live scanner.')
    return result


def load_universe(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        raise SelectionError(f'Missing NIFTY 500 constituent CSV: {path}')
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    output = []
    seen = set()
    for row in rows:
        norm = {k.strip().lower().replace(' ', '_'): str(v).strip() for k, v in row.items() if k}
        symbol = norm.get('symbol', '').strip()
        series = norm.get('series', 'EQ')
        if not symbol or series != 'EQ' or symbol in seen:
            continue
        seen.add(symbol)
        industry = norm.get('industry', norm.get('sector', 'Unclassified'))
        output.append((f'NSE:{symbol}-EQ', industry))
    if not 100 <= len(output) <= 550:
        raise SelectionError(f'Constituents CSV contained only {len(output)} EQ symbols; expected 100-550')
    return output


def download_nifty_csv(url: str, dest: Path):
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; personal-research/1.0)',
               'Referer': 'https://www.niftyindices.com/'}
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            content = res.read()
        text = content.decode('utf-8-sig')
        if 'Symbol' not in text[:300] or 'Series' not in text[:300]:
            raise SelectionError('Downloaded response was not a constituent CSV')
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    except Exception as e:
        raise SelectionError('Could not download official NIFTY 500 CSV automatically. '
                             'Download Index Constituent CSV from niftyindices.com and save to '
                             f'{dest}. Details: {type(e).__name__}: {e}') from e
    return load_universe(dest)


def compute_daily_profile(symbol: str, industry: str, candles: list[Candle], cutoff: date,
                          sessions: int = 20) -> Instrument | None:
    # Date filter prevents lookahead when selecting universe for the morning.
    completed = [c for c in candles if c.at.date() < cutoff and c.volume > 0]
    completed = sorted(completed, key=lambda x: x.at)[-max(sessions, 20):]
    if len(completed) < 15:
        return None
    last = completed[-1]
    values = [c.close * c.volume / 1e7 for c in completed[-20:]]
    turnover = statistics.median(values)
    tr = []
    for prev, curr in zip(completed, completed[1:]):
        tr.append(max(curr.high-curr.low, abs(curr.high-prev.close), abs(curr.low-prev.close)))
    atr_pct = (statistics.mean(tr[-14:]) / last.close * 100) if tr else 0
    # Conservative structure levels: prior 20 session highs/lows, not today's hindsight levels.
    above = sorted({round(c.high, 2) for c in completed[-20:] if c.high > 0})
    below = sorted({round(c.low, 2) for c in completed[-20:] if c.low > 0})
    # Liquidity is primary, volatility secondary. Don't call this probability of winning.
    score = math.log1p(turnover) * 20 + min(atr_pct, 4.0) * 3
    return Instrument(symbol=symbol, industry=industry, median_turnover_cr=round(turnover, 2),
                      daily_atr_pct=round(atr_pct, 2), previous_close=last.close,
                      resistance=above, support=below,
                      selection_score=round(score, 2))


def choose_top100(profiles: list[Instrument], config: dict,
                  morning_pins: list[str] | None = None) -> list[Instrument]:
    passed = [p for p in profiles if
              p.previous_close >= config['min_price_inr'] and
              p.median_turnover_cr >= config['min_median_daily_turnover_cr'] and
              config['min_daily_atr_pct'] <= p.daily_atr_pct <= config['max_daily_atr_pct']]
    pins = set(morning_pins if morning_pins is not None else
               [normalize_morning_symbol(p) for p in config.get('morning_pins', [])])
    passed.sort(key=lambda x: (x.symbol not in pins, -x.selection_score))
    chosen, industry_count = [], Counter()
    for p in passed:
        if industry_count[p.industry] >= config['max_industry_members']:
            continue
        p.source = 'MORNING' if p.symbol in pins else 'AUTO'
        chosen.append(p)
        industry_count[p.industry] += 1
        if len(chosen) == min(config['max_symbols'], 100):
            break
    if len(chosen) < min(config['max_symbols'], 100):
        raise SelectionError(f'Only {len(chosen)} stocks passed filters/diversification; '
                              'lower turnover/ATR thresholds or industry cap in config.json.')
    return chosen


def prepare_selection(adapter, config: dict, universe_path: Path, output_path: Path) -> list[Instrument]:
    today = now_ist().date()
    stocks = load_universe(universe_path)
    pins = load_morning_pins(config)
    # Allow nominated NSE EQ stocks outside NIFTY 500, provided FYERS recognizes
    # them and all price, liquidity, ATR and diversification checks still pass.
    present = {sym for sym, _ in stocks}
    for symbol in pins:
        if symbol not in present:
            stocks.append((symbol, 'Morning picks outside NIFTY 500'))
    symbols = [sym for sym, _ in stocks]
    if pins:
        print(f'Morning Rockstar priority list: {len(pins)} requested; '
              f'{len(stocks)} candidate symbols in total. Live cap remains 100.')
    print(f'Found {len(symbols)} symbols. Fetching FYERS price snapshots (<=50/request).')
    # A known-valid single stock checks credentials, permissions and transport
    # before diagnosing a large NIFTY 500 request as having bad symbols.
    try:
        probe = adapter.quotes(['NSE:SBIN-EQ'])
        if 'NSE:SBIN-EQ' not in probe:
            raise SelectionError('FYERS did not return a valid quote for NSE:SBIN-EQ. '
                                 'Run `python launch.py doctor` before full selection.')
    except Exception as e:
        raise SelectionError(f'FYERS single-symbol probe failed ({e}). '
                             'Run `python launch.py doctor`; verify daily token, '
                             'Market Data permission, SDK and network.') from e
    quotes = adapter.quotes(symbols)
    candidate = []
    for sym, industry in stocks:
        q = quotes.get(sym, {})
        lp = safe_float(q.get('lp'))
        prev = safe_float(q.get('prev_close_price'))
        if max(lp, prev) >= config['min_price_inr']:
            candidate.append((sym, industry))
    print(f'{len(candidate)} stocks pass initial price threshold; fetching cached 20-session '
          'daily liquidity histories. This may take several minutes with the free API.')
    cache_path = ROOT / 'data' / f'daily_cache_{today.isoformat()}.json'
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
    profiles = []
    frm = int((market_dt(today - timedelta(days=55), '00:00')).timestamp())
    # midnight at cutoff excluding current day prevents intraday lookahead.
    to = int(market_dt(today, '00:00').timestamp()) - 1
    for i, (sym, industry) in enumerate(candidate, 1):
        # Prior versions could cache [] after a temporary provider ban. Empty
        # entries are NOT successful history reads and must be fetched again
        # once FYERS has explicitly restored access.
        if not cache.get(sym):
            try:
                raw = adapter.history(sym, 'D', frm, to)
                cache[sym] = [[int(c.at.timestamp()), c.open, c.high, c.low, c.close, c.volume]
                              for c in raw]
            except (ApiRateLimitError, ApiAuthError, ApiPermissionError, ApiProviderError):
                # Preserve successful cache entries and STOP. Previously all
                # provider failures were swallowed, causing 400+ more calls.
                cache_path.write_text(json.dumps(cache), encoding='utf-8')
                raise
            except Exception as e:
                print(f'  Skipped {sym}: {type(e).__name__} ({e})')
                cache[sym] = []
            if i % 10 == 0:
                cache_path.write_text(json.dumps(cache), encoding='utf-8')
                print(f'  {i}/{len(candidate)} daily histories completed')
        bars = []
        for row in cache[sym]:
            try:
                bars.append(Candle.from_fyers(row))
            except (ValueError, TypeError):
                continue
        p = compute_daily_profile(sym, industry, bars, today)
        if p:
            profiles.append(p)
    cache_path.write_text(json.dumps(cache), encoding='utf-8')
    chosen = choose_top100(profiles, config, pins)
    selected = {p.symbol for p in chosen}
    if pins:
        missing = [p for p in pins if p not in selected]
        print(f'Morning Rockstar selection: {len(pins)-len(missing)}/{len(pins)} included.')
        if missing:
            print('  WARNING: Not included (invalid/no data, price/liquidity/ATR thresholds, '
                  'or industry cap): ' + ', '.join(missing))
    payload = {'selected_at_ist': now_ist().isoformat(), 'for_session': today.isoformat(),
               'count': len(chosen), 'universe_source': str(universe_path),
               'morning_requested': pins, 'morning_selected': sorted(selected.intersection(pins)),
               'selection_rules': {'min_price': config['min_price_inr'],
                                   'min_median_daily_turnover_cr': config['min_median_daily_turnover_cr']},
               'stocks': [p.__dict__ for p in chosen]}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    print(f'Selected {len(chosen)} stocks. Saved: {output_path}')
    for p in chosen[:10]:
        print(f'  {p.symbol:22} price={p.previous_close:8.2f} median_turnover={p.median_turnover_cr:6.1f}cr '
              f'ATR={p.daily_atr_pct:.1f}%')
    return chosen


def read_selection(path: Path) -> tuple[dict, list[Instrument]]:
    if not path.exists():
        raise SelectionError(f'No selection file {path}; run python launch.py prepare first.')
    p = json.loads(path.read_text(encoding='utf-8'))
    inst = [Instrument(**row) for row in p['stocks']]
    if len(inst) < 1 or len(inst) > 100 or len(set(x.symbol for x in inst)) != len(inst):
        raise SelectionError('Invalid selection: expected up to 100 unique symbols.')
    return p, inst
