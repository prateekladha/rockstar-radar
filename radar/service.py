"""Session controller: FYERS history baseline, WebSocket updates, candle reconciliation."""
from __future__ import annotations
import csv
import json
import os
import threading
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from .aggregator import LiveCandleBuilder
from .engine import RadarEngine, same_time_baseline
from .smc_engine import SMCEngine
from .health import write_health
from .fyers import (ApiAuthError, ApiError, ApiInputError, ApiPermissionError,
                    ApiProviderError, ApiRateLimitError, FyersAdapter)
from .models import Candle, Signal
from .selecting import read_selection
from .utils import IST, ROOT, bar_start, market_dt, now_ist, signal_bar_minutes


class SessionJournal:
    def __init__(self, day: date):
        self.day = day
        self.root = ROOT / 'output'
        self.root.mkdir(exist_ok=True)
        # Per-scanner suffix (e.g. 'u1') so concurrent broker-owners keep separate audit CSVs and a
        # clean restore-on-restart. Empty for the single-user app → unchanged filenames.
        self.suffix = os.environ.get('RADAR_SCANNER_ID', '').strip()
        self.lock = threading.RLock()
        self.bar_ids = set()
        self.anchor_ids = set()

    def _fn(self, kind: str) -> str:
        return f'{kind}_{self.day}{("_" + self.suffix) if self.suffix else ""}.csv'

    @property
    def candles_path(self) -> Path:
        return self.root / self._fn('fy_history_candles')

    @property
    def events_path(self) -> Path:
        return self.root / self._fn('signals')

    def _write(self, filename: str, header: list[str], row: list):
        path = self.root / filename
        with self.lock:
            new = not path.exists() or path.stat().st_size == 0
            with path.open('a', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                if new:
                    writer.writerow(header)
                writer.writerow(row)

    def event(self, sig: Signal):
        self._write(self._fn('signals'),
                    ['time_ist','symbol','side','status','score','last_seen_price','rvol',
                     'orb_level','note','entry','stop','target','estimated_net_rr',
                     'delivered_time_ist','detection_lag_seconds'],
                    [sig.time, sig.symbol, sig.side, sig.state, sig.score,
                     sig.price, sig.rvol, sig.level, sig.note, sig.entry, sig.stop,
                     sig.target, sig.net_rr, sig.delivered_time_ist, sig.detection_lag_seconds])

    def anchor(self, symbol: str, observed: datetime):
        if symbol in self.anchor_ids:
            return
        self.anchor_ids.add(symbol)
        delay = round((observed - market_dt(self.day, '09:20')).total_seconds(), 1)
        self._write(self._fn('or_anchor_delays'),
                    ['symbol','ready_time_ist','delay_from_0920_seconds'],
                    [symbol, observed.isoformat(), delay])

    def candle(self, symbol: str, bar: Candle):
        key = (symbol, bar.at)
        with self.lock:
            if key in self.bar_ids:
                return
            self.bar_ids.add(key)
        self._write(self._fn('fy_history_candles'),
                    ['bar_start_ist','symbol','open','high','low','close','volume'],
                    [bar.at.isoformat(),symbol,bar.open,bar.high,bar.low,bar.close,bar.volume])


def cache_path(day: date, bar_minutes: int = 5):
    """Baselines are per bar width — a 1-minute median is roughly a fifth of a 5-minute one.

    The width is in the filename so flipping `use_one_minute_candles` cannot silently reuse the
    other setting's cache and divide every RVOL by the wrong number.
    """
    return ROOT / 'data' / f'baseline_{day.isoformat()}_{int(bar_minutes)}m.json'


def smc_cache_path(day: date, bar_minutes: int = 5):
    """SMC historical candles cache path (per bar width and session date)."""
    return ROOT / 'data' / f'smc_history_{day.isoformat()}_{int(bar_minutes)}m.json'


def restore_today_from_local_logs(engine: RadarEngine, journal: SessionJournal,
                                  observed_at: datetime | None = None) -> tuple[int, int]:
    """Restore *historical only* candles and events from today's local CSVs.

    There is deliberately no Tick restoration, no live signals, and no replay of
    previous ORB confirmations: stale signals must never be resurrected as trades.
    Never accepts candles from a different day, selected universe or an unfinished bar.
    """
    observed = (observed_at or now_ist()).astimezone(IST)
    candles_path = journal.candles_path
    events_path = journal.events_path
    restored_candles = 0
    restored_events = 0
    bar_delta = timedelta(minutes=engine.bar_minutes)
    or_start = market_dt(journal.day, engine.config['open_range_start'])
    or_end = or_start + timedelta(minutes=engine.or_minutes)
    if candles_path.exists():
        with candles_path.open(newline='', encoding='utf-8') as source:
            for row in csv.DictReader(source):
                try:
                    symbol = row['symbol']
                    if symbol not in engine.states:
                        continue
                    at = datetime.fromisoformat(row['bar_start_ist']).astimezone(IST)
                    if at.date() != journal.day or at + bar_delta > observed:
                        continue
                    candle = Candle(at, float(row['open']), float(row['high']),
                                    float(row['low']), float(row['close']), int(row['volume']))
                    if min(candle.open, candle.high, candle.low, candle.close) <= 0 or candle.volume < 0:
                        continue
                    st = engine.states[symbol]
                    key = int(at.timestamp())
                    if key in st.completed:
                        continue
                    st.completed[key] = candle
                    journal.bar_ids.add((symbol, candle.at))
                    if or_start <= candle.at < or_end:
                        # Rebuild through the engine so a partial window (fewer bars logged than
                        # the range needs) leaves `opening` unset rather than producing a range
                        # that is too narrow and wrong for the rest of the day.
                        st.or_bars[key] = candle
                        opening = engine._build_opening(st)
                        if opening is not None:
                            st.opening = opening
                            st.state = 'RECOVERING'
                            st.reason = ('Opening range restored from local log; '
                                         'awaiting fresh FYERS data')
                            st.score = 0
                            journal.anchor_ids.add(symbol)
                    restored_candles += 1
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue  # A malformed historical line must not crash fresh data collection.

    if events_path.exists():
        def opt_float(v):
            try:
                return float(v) if v not in ('', None) else None
            except (ValueError, TypeError):
                return None
        with events_path.open(newline='', encoding='utf-8') as source:
            for row in csv.DictReader(source):
                try:
                    symbol = row['symbol']
                    when = datetime.fromisoformat(row['time_ist']).replace(tzinfo=IST)
                    if symbol not in engine.states or when.date() != journal.day:
                        continue
                    engine.events.append(Signal(
                        time=row['time_ist'], symbol=symbol, side=row.get('side',''),
                        state=row.get('status',''), score=int(row.get('score') or 0),
                        price=float(row.get('last_seen_price') or 0),
                        rvol=opt_float(row.get('rvol')), note=row.get('note',''),
                        level=float(row.get('orb_level') or 0),
                        entry=opt_float(row.get('entry')), stop=opt_float(row.get('stop')),
                        target=opt_float(row.get('target')),
                        net_rr=opt_float(row.get('estimated_net_rr')),
                        delivered_time_ist=row.get('delivered_time_ist',''),
                        detection_lag_seconds=opt_float(row.get('detection_lag_seconds'))))
                    restored_events += 1
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
    # A stock with a previously confirmed breakout must NOT be confirmed again
    # after restart merely because in-memory confirmed_at was cleared.
    consumed_symbols = {event.symbol for event in engine.events
                        if event.state in ('CONFIRMED', 'RETEST_READY',
                                           'RISK_FAIL', 'FAILED', 'EXPIRED')}
    for symbol in consumed_symbols:
        st = engine.states[symbol]
        st.state = 'SESSION_CONSUMED'
        st.score = 0
        st.reason = ('Earlier completed ORB already recorded today. '
                     'No duplicate trade alerts after restart.')
    engine.events = engine.events[-150:]
    return restored_candles, restored_events


def cache_smc_history(adapter: FyersAdapter, symbols: list[str], day: date,
                      config: dict, force: bool = False) -> dict[str, bool]:
    """Pre-fetch and cache SMC historical candles (for warmup phase).

    Like baselines, this can run before market open to prepare the SMC engine's historical context.
    Caches 5 days of historical candles per symbol for swing detection and structure analysis.

    Returns dict[symbol -> bool] indicating which symbols have cached history.
    """
    bar_minutes = signal_bar_minutes(config)
    resolution = str(bar_minutes)
    path = smc_cache_path(day, bar_minutes)

    # Load existing cache
    if path.exists() and not force:
        stored = json.loads(path.read_text(encoding='utf-8'))
    else:
        stored = {}

    # Fetch last 5 days of candles for SMC analysis
    from_dt = market_dt(day - timedelta(days=5), '09:15')
    to_dt = market_dt(day, '09:15')
    total = len(symbols)

    for i, symbol in enumerate(symbols, 1):
        if symbol in stored and stored[symbol]:
            continue  # Already cached

        try:
            candles = baseline_history(adapter, symbol, resolution, from_dt, to_dt)
            # Only cache symbols that actually returned candles. Persisting an empty
            # list poisons the cache: a later restart loads it as "0 candles" and the
            # SMC engine never reaches its 101-candle minimum, so the radar stays empty
            # for the whole session. Leaving a failed symbol ABSENT lets the next run
            # (or restart) re-fetch it instead.
            if candles:
                stored[symbol] = [
                    {
                        'at': c.at.isoformat(),
                        'open': c.open,
                        'high': c.high,
                        'low': c.low,
                        'close': c.close,
                        'volume': c.volume
                    }
                    for c in candles
                ]
            else:
                print(f'  Warning: {symbol} has no SMC history available')
        except (ApiRateLimitError, ApiAuthError, ApiPermissionError, ApiProviderError):
            path.write_text(json.dumps(stored), encoding='utf-8')
            raise
        except Exception as e:
            print(f'  SMC history unavailable for {symbol}: {type(e).__name__}: {e}')
            # Do NOT store an empty list — leave the symbol absent so it is re-fetched.

        if i % 10 == 0:
            path.write_text(json.dumps(stored), encoding='utf-8')
            print(f'  SMC history cached: {i}/{total}')

    path.write_text(json.dumps(stored), encoding='utf-8')
    return {sym: bool(data) for sym, data in stored.items()}


def load_smc_history(adapter: FyersAdapter, smc_engine: SMCEngine, today: date,
                     config: dict) -> int:
    """Load SMC historical candles into the engine (from cache or fetch).

    First tries to load from cache (created by warmup phase). If cache doesn't exist or is
    incomplete, fetches from broker API. This allows instant loading if warmup was run, or
    graceful fallback if it wasn't.

    Returns number of symbols successfully loaded.
    """
    bar_minutes = signal_bar_minutes(config)
    path = smc_cache_path(today, bar_minutes)
    loaded = 0
    symbols = list(smc_engine.states.keys())

    # Try to load from cache first (instant if warmup was run)
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding='utf-8'))
            print(f'Loading SMC history from cache ({len(stored)} symbols)...')

            for symbol in symbols:
                if symbol not in stored or not stored[symbol]:
                    continue

                # Reconstruct Candle objects from cached data
                candles = [
                    Candle(
                        at=datetime.fromisoformat(c['at']),
                        open=c['open'],
                        high=c['high'],
                        low=c['low'],
                        close=c['close'],
                        volume=c['volume']
                    )
                    for c in stored[symbol]
                ]

                smc_engine.load_historical_candles(symbol, candles)
                loaded += 1

            # Only trust the cache if it yielded history for a healthy share of
            # symbols. A cache written by a failed warmup (broker not yet authed /
            # rate-limited) can list every symbol with an empty candle array; blindly
            # returning here would leave the SMC engine with zero context for the whole
            # session (empty radar). When the cache is insufficient, fall through to the
            # live broker fetch below, which also overwrites the poisoned cache.
            min_ok = max(1, len(symbols) // 2)
            if loaded >= min_ok:
                print(f'SMC engine ready: {loaded}/{len(symbols)} symbols loaded from cache')
                return loaded
            print(f'SMC cache insufficient ({loaded}/{len(symbols)} symbols had candles); '
                  f'falling back to live fetch...')

        except Exception as e:
            print(f'SMC cache load failed: {type(e).__name__}: {e}')
            print('Falling back to live fetch...')

    # Fallback: fetch from broker (if cache doesn't exist or failed)
    print(f'Fetching SMC historical data from broker ({bar_minutes}m candles, last 5 days)...')
    resolution = str(bar_minutes)
    from_dt = market_dt(today - timedelta(days=5), '09:15')
    to_dt = market_dt(today, '09:15')

    # Store fetched data so we can cache it
    fetched_data = {}
    loaded = 0  # reset: a partial/insufficient cache load above is superseded by this fetch

    for i, symbol in enumerate(symbols, 1):
        try:
            candles = baseline_history(adapter, symbol, resolution, from_dt, to_dt)
            if candles:
                smc_engine.load_historical_candles(symbol, candles)
                loaded += 1

                # Store in serializable format for caching
                fetched_data[symbol] = [
                    {
                        'at': c.at.isoformat(),
                        'open': c.open,
                        'high': c.high,
                        'low': c.low,
                        'close': c.close,
                        'volume': c.volume
                    }
                    for c in candles
                ]

            if i % 20 == 0:
                print(f'  SMC history loaded: {i}/{len(symbols)}')
        except (ApiAuthError, ApiPermissionError, ApiRateLimitError) as e:
            # The token is invalid/expired, lacks market-data permission, or the daily
            # REST budget is spent — the SAME failure would hit every remaining symbol.
            # Stop now instead of grinding through ~100 doomed calls (this is the
            # "skip the SMC warmup until a valid token exists" guard). The scanner
            # reloads SMC history on its next start, which recycles once the user logs
            # in with a fresh token. Whatever loaded so far is kept, never empties.
            print(f'  SMC history fetch stopped early ({type(e).__name__}); '
                  f'{loaded}/{len(symbols)} loaded. Will reload on next scanner start.')
            break
        except Exception as e:
            # Non-critical - SMC will work with less data, just less accurate initially.
            # Do NOT cache an empty list — leave the symbol absent so a later restart
            # re-fetches it instead of loading zero candles from a poisoned cache.
            print(f'  SMC history unavailable for {symbol}: {type(e).__name__}')
            continue

    # Save fetched data to cache for future use
    if fetched_data:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(fetched_data), encoding='utf-8')
            print(f'  ✓ Cached SMC history to {path.name} for future restarts')
        except Exception as e:
            print(f'  Warning: Could not cache SMC history: {type(e).__name__}: {e}')

    print(f'SMC engine ready: {loaded}/{len(symbols)} symbols have historical context')
    return loaded


def load_existing_baselines(engine: RadarEngine, today: date) -> int:
    """Read local baselines without contacting FYERS during a closed session."""
    path = cache_path(today, engine.bar_minutes)
    if not path.exists():
        return 0
    try:
        cached = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return 0
    for symbol in engine.states:
        if isinstance(cached.get(symbol), dict) and cached[symbol]:
            engine.set_baseline(symbol, cached[symbol])
    return sum(bool(engine.baselines.get(s)) for s in engine.states)


def baseline_history(adapter: FyersAdapter, symbol: str, resolution: str,
                     from_dt: datetime, to_dt: datetime, max_days: int = 25) -> list[Candle]:
    """Prior-session candles for one symbol, re-requested in windows only if the broker refuses.

    The lookback is ~15,000 candles at 1-minute resolution against ~3,000 at 5-minute, and brokers
    cap how wide an intraday history window may be. The full range is attempted first, so nothing
    changes on accounts that accept it; the split costs one extra request and only where needed.
    Only an input/range rejection is retried — an expired token, a missing permission or a rate
    limit must still stop baseline preparation outright rather than become N more identical calls.
    """
    try:
        return adapter.history(symbol, resolution, int(from_dt.timestamp()), int(to_dt.timestamp()))
    except ApiInputError:
        pass
    out: list[Candle] = []
    cursor = from_dt
    while cursor < to_dt:
        end = min(cursor + timedelta(days=max_days), to_dt)
        out.extend(adapter.history(symbol, resolution, int(cursor.timestamp()), int(end.timestamp())))
        cursor = end + timedelta(seconds=1)      # disjoint windows: no double-counted volume
    return sorted(out, key=lambda c: c.at)


def build_baselines(adapter: FyersAdapter, symbols: list[str], day: date,
                    config: dict, force: bool = False, on_progress=None) -> dict[str, dict[str, float]]:
    """Only previous sessions' candles; cached so market-day startup needs no REST warmup.

    Resolution follows the configured signal bar, because RVOL compares a live bar against the
    median of the same clock slot: a 1-minute bar has to be measured against 1-minute history.
    The request count is unchanged (one per symbol) — only the rows per response grow.
    on_progress(done, total) is called as symbols are processed, so a warming scanner can surface
    'X/N symbols ready' before its dashboard is up."""
    bar_minutes = signal_bar_minutes(config)
    resolution = str(bar_minutes)
    path = cache_path(day, bar_minutes)
    stored = json.loads(path.read_text(encoding='utf-8')) if path.exists() and not force else {}
    from_dt = market_dt(day - timedelta(days=40), '00:00')
    to_dt = market_dt(day, '00:00') - timedelta(seconds=1)
    total = len(symbols)
    if on_progress:
        on_progress(0, total)
    for i, symbol in enumerate(symbols, 1):
        if on_progress and (i % 5 == 0 or i == total):
            on_progress(i, total)
        if symbol in stored and stored[symbol]:
            continue
        try:
            candles = baseline_history(adapter, symbol, resolution, from_dt, to_dt)
            baseline = same_time_baseline(candles, day, config['baseline_sessions'])
            stored[symbol] = baseline
            if not baseline:
                print(f'  Warning: {symbol} lacks >=10 prior sessions of '
                      f'{bar_minutes}m volume history')
        except (ApiRateLimitError, ApiAuthError, ApiPermissionError, ApiProviderError):
            # A provider block must end ALL history preparation, not become
            # 100 more identical requests and 100 empty baselines.
            path.write_text(json.dumps(stored), encoding='utf-8')
            raise
        except Exception as e:
            print(f'  Baseline unavailable for {symbol}: {type(e).__name__}: {e}')
            stored[symbol] = {}
        if i % 10 == 0:
            path.write_text(json.dumps(stored), encoding='utf-8')
            print(f'  FYERS {bar_minutes}m volume baselines: {i}/{len(symbols)}')
    path.write_text(json.dumps(stored), encoding='utf-8')
    return stored


def start_live(config: dict, selection_path: Path, port: int):
    # Selection already succeeded (it made FYERS calls), so the token is valid as the feed launches.
    # The web process reads this to show a real "live" vs a Reconnect CTA.
    _scanner_id = os.environ.get('RADAR_SCANNER_ID', '')
    write_health(_scanner_id, ok=True)
    p, info = read_selection(selection_path)
    today = now_ist().date()
    if p.get('for_session') != today.isoformat():
        raise ValueError('Selection is not for today. Run `python launch.py prepare` each trading morning.')
    from .utils import holiday, is_market_day
    if not is_market_day():
        h = holiday()
        raise ValueError(f'Market closed today ({h or "weekend"} in IST). Live scanning disabled.')
    journal = SessionJournal(today)
    def on_signal(sig):
        journal.event(sig)                 # always persist to CSV
        try:
            from .notify import notify_signal
            notify_signal(sig, config)     # push actionable alerts to Telegram (no-op if unset)
        except Exception as e:             # a notifier failure must never break scanning
            print(f'Telegram notify failed: {type(e).__name__}: {e}')
    engine = RadarEngine(info, config, today, on_signal=on_signal)
    smc_engine = SMCEngine(info, config)  # SMC engine for Smart Money Concepts analysis
    restored_candles, restored_events = restore_today_from_local_logs(engine, journal)
    if restored_candles or restored_events:
        print(f'Restored {restored_candles} prior completed candles and '
              f'{restored_events} historical events from local files. '
              'Historical events are NOT actionable.')

    # After the configured intraday discovery window, open a REVIEW-ONLY
    # dashboard without hitting FYERS or showing stale signals as tradeable.
    # Running at 14:00 with the default 11:30 cutoff must not silently look live.
    if now_ist() >= market_dt(today, config['new_signals_stop']) + timedelta(
            minutes=config['retest_expiry_minutes']):
        load_existing_baselines(engine, today)
        engine.update_health('SESSION CLOSED: new setups stop at '
                             f"{config['new_signals_stop']} IST; historical review only")
        for st in engine.states.values():
            st.state = 'SESSION_CLOSED'
            st.score = 0
            st.reason = ('Past the configured new-signals cutoff. No live scanning; '
                         'all historical alerts are for review only.')
        print('Today\'s discovery window has ended. Serving REVIEW-ONLY dashboard; '
              'no FYERS requests or live trading signals will be made.')
        from .dashboard import serve
        serve(engine, port=port, mode='REVIEW ONLY')
        return

    adapter = FyersAdapter(config)
    print(f'Loading cached prior-session {engine.bar_minutes}m volume baselines '
          '(warm up before 09:15 IST).')

    def _warm(done, total):
        write_health(_scanner_id, ok=True, warmup={'done': done, 'total': total, 'phase': 'baselines'})

    baselines = build_baselines(adapter, list(engine.states), today, config, on_progress=_warm)
    good = 0
    for symbol, values in baselines.items():
        if values:
            engine.set_baseline(symbol, values)
            good += 1
    if good < len(info) * 0.8:
        raise ValueError(f'Only {good}/{len(info)} same-time baselines ready. '
                         'Insufficient history; refusing unreliable scans.')
    print(f'{good}/{len(info)} same-time volume baselines ready.')

    # Load historical candles for SMC analysis (swing detection needs 100+ historical bars)
    print('Loading SMC historical context...')
    try:
        smc_loaded = load_smc_history(adapter, smc_engine, today, config)
        print(f'SMC engine initialized with history for {smc_loaded}/{len(info)} symbols')
    except Exception as e:
        print(f'SMC history loading failed (non-critical): {type(e).__name__}: {e}')
        print('SMC engine will build context from real-time data (slower to start)')

    # Realtime path: aggregate websocket ticks into completed signal-interval candles and feed
    # them as PROVISIONAL bars (confirm ~1s after close). REST history reconciles each one.
    def on_bar_completed(sym, candle):
        engine.ingest_live_bar(sym, candle)   # Feed to ORB radar
        smc_engine.process_candle(sym, candle)  # Feed to SMC engine

    builder = LiveCandleBuilder(
        bar_minutes=engine.bar_minutes,
        on_bar=on_bar_completed)

    def on_tick(t):
        engine.update_tick(t)      # intrabar WATCH/READY/BREAKOUT_PENDING early warning
        smc_engine.process_tick(t.symbol, t)  # Update SMC with current price
        builder.add_tick(t)        # roll completed bars -> provisional confirmation

    # FYERS WebSocket can run in a background SDK-owned thread.
    def run_socket():
        try:
            adapter.subscribe(list(engine.states), on_tick, engine.update_health)
        except Exception as e:
            engine.update_health(f'WebSocket failed: {type(e).__name__}: {e}')
            print(f'WebSocket failed: {type(e).__name__}: {e}')

    def flush_loop():
        # Finalize bars for thin/illiquid symbols that received no new-bar tick yet.
        grace = config.get('history_confirmation_grace_seconds', 12)
        while now_ist().date() == engine.session and not engine.halted:
            try:
                builder.flush_completed(now_ist(), grace_seconds=grace)  # on_bar ingests
            except Exception as e:
                engine.update_health(f'Live bar flush issue: {type(e).__name__}: {e}')
            time.sleep(1)

    write_health(_scanner_id, ok=True, warmup={'done': good, 'total': len(info), 'phase': 'connecting'})
    threading.Thread(target=run_socket, daemon=True, name='fyers-data-socket').start()
    threading.Thread(target=flush_loop, daemon=True, name='live-candle-flush').start()
    threading.Thread(target=reconcile_history, args=(adapter, engine, journal, _scanner_id),
                     daemon=True, name='history-candle-reconciliation').start()
    from .dashboard import serve
    serve(engine, port=port, smc_engine=smc_engine)


def reconcile_history(adapter: FyersAdapter, engine: RadarEngine, journal: SessionJournal,
                      scanner_id: str = ''):
    """REST history verifies OR and full close; never confirms using incomplete websocket ticks."""
    checked = {}  # symbol -> most recent completed candle timestamp queried
    anchor_attempts = {}  # prevent one invalid symbol from starving the other 99
    failures_in_a_row = 0
    last_heartbeat = 0.0
    cfg = engine.config
    bar_minutes = engine.bar_minutes
    bar_delta = timedelta(minutes=bar_minutes)
    resolution = str(bar_minutes)
    start = market_dt(engine.session, '09:15')          # how far back each history call reaches
    # The opening-range window comes from config, not from `start`: on a special session (Muhurat)
    # the range opens in the afternoon while history is still fetched from 09:15.
    or_start = market_dt(engine.session, cfg['open_range_start'])
    or_end = or_start + timedelta(minutes=engine.or_minutes)
    while True:
        now = now_ist()
        mono = time.monotonic()
        if mono - last_heartbeat >= 120:   # visibility: how fast are we spending the daily REST budget
            last_heartbeat = mono
            try:
                print(f'reconcile: FYERS history requests used today = {adapter.limit.daily}/'
                      f'{adapter.limit.per_day}')
            except Exception:
                pass
        if now.date() != engine.session:
            engine.update_health('Session finished; restart with today selection next trading day')
            return
        if now < market_dt(engine.session, '09:20') + timedelta(seconds=12):
            time.sleep(2)
            continue
        if now > market_dt(engine.session, cfg['new_signals_stop']) + timedelta(minutes=25):
            engine.update_health('Scanning completed for the day; audit after close')
            return
        # FYERS intraday history can include partial candles. Filter using completed candle time.
        if now.second < cfg['history_confirmation_grace_seconds'] and now.minute % bar_minutes == 0:
            time.sleep(0.6)
            continue
        latest_completed_start = bar_start(now, bar_minutes) - bar_delta
        target_epoch = int(latest_completed_start.timestamp())
        if target_epoch < int(start.timestamp()):
            time.sleep(1)
            continue
        with engine.lock:
            missing_anchors = [s for s, st in engine.states.items() if not st.opening]
        # Anchor first: all 100 symbols must have an authoritative ORH/ORL, even if no tick yet.
        # For near/pending/confirmed candidates, prioritize recent close checks afterwards.
        missing_anchors = [sym for sym in missing_anchors if
                           sym not in anchor_attempts or
                           (now - anchor_attempts[sym]).total_seconds() >= 80]
        # Default: reconcile only symbols with an actual fired provisional signal (or confirmed,
        # tracking) — not every symbol hovering near its OR boundary. This is what kept the daily
        # FYERS budget from lasting the full session. Set reconcile_signals_only=false to revert to
        # the wider near-boundary net.
        _verify = (engine.pending_reconcile if cfg.get('reconcile_signals_only', True)
                   else engine.needs_verification)
        active = [sym for sym in engine.states
                  if sym not in missing_anchors and _verify(sym)
                  and checked.get(sym, 0) < target_epoch]
        # Unconfirmed ticks crossing/approaching boundary can enter the priority pool.
        queue = (active[:25] if active else []) + missing_anchors
        # Mark no candidate fetch outside the 25 per-cycle cap. This is an intentional free-API tradeoff.
        if not queue:
            time.sleep(1.5)
            continue
        symbol = queue[0]
        try:
            until = int((now - timedelta(seconds=60)).timestamp())
            candles = adapter.history(symbol, resolution, int(start.timestamp()), until)
            # Strictly discard unfinished bars, and avoid displaying late discovered historical
            # alerts as though real time. Only bootstrap OR bars when much later than closure.
            for bar in candles:
                if bar.at + bar_delta + timedelta(
                        seconds=cfg['history_confirmation_grace_seconds']) > now:
                    continue
                bar_ts = int(bar.at.timestamp())
                is_prov = engine.is_provisional(symbol, bar_ts)
                # Bars inside the opening-range window are always ingested, however late: they
                # build the range itself, and on 1m that is five bars rather than just the first.
                if (bar.at + bar_delta < now - timedelta(seconds=105)
                        and not (or_start <= bar.at < or_end) and not is_prov):
                    # Old bar never seen live: save for audit/continuity, but don't trigger
                    # late historical signals. (A provisional bar MUST still be reconciled.)
                    with engine.lock:
                        st = engine.states[symbol]
                        st.completed.setdefault(bar_ts, bar)
                    journal.candle(symbol, bar)
                    continue
                # Authoritative ingest: confirms live candidates and reconciles (validates
                # or retracts) any provisional signal built from this bar.
                engine.ingest_closed_bar(symbol, bar, observed_at=now)
                # On 1m the range is only complete after the last bar of the window, so record the
                # anchor the moment `opening` is actually set rather than on the first bar.
                if (or_start <= bar.at < or_end) and engine.states[symbol].opening:
                    journal.anchor(symbol, now)
                journal.candle(symbol, bar)
            checked[symbol] = target_epoch
            failures_in_a_row = 0
            if symbol in missing_anchors and not engine.states[symbol].opening:
                anchor_attempts[symbol] = now
        except (ApiRateLimitError, ApiAuthError, ApiPermissionError) as e:
            # NON-recoverable by retry — stop cleanly and tell the user what to do. (A restart won't
            # fix any of these: auth needs a fresh login, permission a broker-app change, rate-limit
            # a daily reset.) No CLI/dev hints; technical detail stays in the server log.
            rate_limited = isinstance(e, ApiRateLimitError)
            if isinstance(e, ApiAuthError):
                reason = ('Your broker session has expired. Log in to your broker for today to '
                          'resume the live scan.')
            elif isinstance(e, ApiPermissionError):
                reason = ('Your broker app is missing Market Data (quotes & history) permission. '
                          'Enable it in your broker app, then restart the scan.')
            else:  # rate_limited
                reason = ('Your broker hit its daily API limit (FYERS Standard allows 5,000 '
                          'requests/day). Live scanning pauses and resumes when the limit resets '
                          'next trading day. This is a broker limit, not a Rockstar Radar issue.')
            engine.halt(reason)
            write_health(scanner_id, ok=False, need_login=isinstance(e, ApiAuthError),
                         rate_limited=rate_limited, reason=reason)
            print('FATAL: FYERS data API unavailable; stopping live confirmation. '
                  'Do not trade from cached Radar statuses. ' + str(e)[:160])
            return
        except ApiError as e:
            # TRANSIENT (generic history error, provider outage, bad input): must NOT permanently kill
            # the feed — a brief blip at the open once took the scanner offline all day. Back off and
            # keep retrying; the loop resumes the instant FYERS recovers (failures reset on the next
            # success, above). The RateLimiter + escalating backoff keep this from becoming a request
            # storm (worst case ~1 req / 90s during a sustained outage).
            failures_in_a_row += 1
            backoff = min(5 * failures_in_a_row, 90)
            engine.update_health(f'Live data reconnecting — FYERS history error '
                                 f'(retry {failures_in_a_row}): {str(e)[:110]}')
            print(f'reconcile: history error #{failures_in_a_row}, backing off {backoff}s: {str(e)[:160]}')
            time.sleep(backoff)
        except Exception as e:
            engine.update_health(f'History reconcile issue: {type(e).__name__}: {e}')
            time.sleep(1)
        if time.monotonic() - last_heartbeat > 60:
            last_heartbeat = time.monotonic()
            snap = engine.snapshot()
            print(f'{snap["server_time_ist"]} OR ready={snap["anchors_ready"]}/{snap["monitored"]} '
                  f'candidates={snap["active_candidates"]}, events={len(engine.events)}')
        time.sleep(0.2)
