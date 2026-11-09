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
from .health import write_health
from .fyers import (ApiAuthError, ApiError, ApiPermissionError,
                    ApiProviderError, ApiRateLimitError, FyersAdapter)
from .models import Candle, Signal
from .selecting import read_selection
from .utils import IST, ROOT, bar_start, market_dt, now_ist


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


def cache_path(day: date):
    return ROOT / 'data' / f'baseline_{day.isoformat()}.json'


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
    if candles_path.exists():
        with candles_path.open(newline='', encoding='utf-8') as source:
            for row in csv.DictReader(source):
                try:
                    symbol = row['symbol']
                    if symbol not in engine.states:
                        continue
                    at = datetime.fromisoformat(row['bar_start_ist']).astimezone(IST)
                    if at.date() != journal.day or at + timedelta(minutes=5) > observed:
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
                    if candle.at == market_dt(journal.day, engine.config['open_range_start']):
                        st.opening = candle
                        st.state = 'RECOVERING'
                        st.reason = 'Opening range restored from local log; awaiting fresh FYERS data'
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


def load_existing_baselines(engine: RadarEngine, today: date) -> int:
    """Read local baselines without contacting FYERS during a closed session."""
    path = cache_path(today)
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


def build_baselines(adapter: FyersAdapter, symbols: list[str], day: date,
                    config: dict, force: bool = False, on_progress=None) -> dict[str, dict[str, float]]:
    """Only previous sessions' 5m candles; cached so market-day startup needs no REST warmup.
    on_progress(done, total) is called as symbols are processed, so a warming scanner can surface
    'X/N symbols ready' before its dashboard is up."""
    path = cache_path(day)
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
            candles = adapter.history(symbol, '5', int(from_dt.timestamp()), int(to_dt.timestamp()))
            baseline = same_time_baseline(candles, day, config['baseline_sessions'])
            stored[symbol] = baseline
            if not baseline:
                print(f'  Warning: {symbol} lacks >=10 prior sessions of 5m volume history')
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
            print(f'  FYERS 5m volume baselines: {i}/{len(symbols)}')
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
    from .utils import is_special_session
    if now_ist().weekday() >= 5 and not is_special_session():
        raise ValueError('It is a weekend in IST. Live alerts disabled; use demo mode.')
    journal = SessionJournal(today)
    def on_signal(sig):
        journal.event(sig)                 # always persist to CSV
        try:
            from .notify import notify_signal
            notify_signal(sig, config)     # push actionable alerts to Telegram (no-op if unset)
        except Exception as e:             # a notifier failure must never break scanning
            print(f'Telegram notify failed: {type(e).__name__}: {e}')
    engine = RadarEngine(info, config, today, on_signal=on_signal)
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
    print('Loading cached prior-session 5m volume baselines (warm up before 09:15 IST).')

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
    # Realtime path: aggregate websocket ticks into completed 5m candles and feed them
    # as PROVISIONAL bars (confirm ~1s after close). REST history reconciles each one.
    builder = LiveCandleBuilder(
        bar_minutes=config.get('open_range_minutes', 5),
        on_bar=lambda sym, candle: engine.ingest_live_bar(sym, candle))

    def on_tick(t):
        engine.update_tick(t)      # intrabar WATCH/READY/BREAKOUT_PENDING early warning
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
    serve(engine, port=port)


def reconcile_history(adapter: FyersAdapter, engine: RadarEngine, journal: SessionJournal,
                      scanner_id: str = ''):
    """REST history verifies OR and full close; never confirms using incomplete websocket ticks."""
    checked = {}  # symbol -> most recent completed candle timestamp queried
    anchor_attempts = {}  # prevent one invalid symbol from starving the other 99
    failures_in_a_row = 0
    last_heartbeat = 0.0
    cfg = engine.config
    start = market_dt(engine.session, '09:15')
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
        if now.second < cfg['history_confirmation_grace_seconds'] and now.minute % 5 == 0:
            time.sleep(0.6)
            continue
        latest_completed_start = bar_start(now) - timedelta(minutes=5)
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
            candles = adapter.history(symbol, '5', int(start.timestamp()), until)
            # Strictly discard unfinished bars, and avoid displaying late discovered historical
            # alerts as though real time. Only bootstrap OR bars when much later than closure.
            for bar in candles:
                if bar.at + timedelta(minutes=5, seconds=cfg['history_confirmation_grace_seconds']) > now:
                    continue
                bar_ts = int(bar.at.timestamp())
                is_prov = engine.is_provisional(symbol, bar_ts)
                if (bar.at + timedelta(minutes=5) < now - timedelta(seconds=105)
                        and bar.at != start and not is_prov):
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
                if bar.at == start and engine.states[symbol].opening:
                    journal.anchor(symbol, now)
                journal.candle(symbol, bar)
            checked[symbol] = target_epoch
            failures_in_a_row = 0
            if symbol in missing_anchors and not engine.states[symbol].opening:
                anchor_attempts[symbol] = now
        except (ApiRateLimitError, ApiAuthError, ApiPermissionError, ApiProviderError) as e:
            # User-facing halt reason — no CLI/dev hints. Technical detail stays in the server log.
            rate_limited = isinstance(e, ApiRateLimitError)
            if isinstance(e, ApiAuthError):
                reason = ('Your broker session has expired. Log in to your broker for today to '
                          'resume the live scan.')
            elif isinstance(e, ApiPermissionError):
                reason = ('Your broker app is missing Market Data (quotes & history) permission. '
                          'Enable it in your broker app, then restart the scan.')
            elif rate_limited:
                reason = ('Your broker hit its daily API limit (FYERS Standard allows 5,000 '
                          'requests/day). Live scanning pauses and resumes when the limit resets '
                          'next trading day. This is a broker limit, not a Rockstar Radar issue.')
            else:
                reason = 'Live broker data is temporarily unavailable. Please try again shortly.'
            engine.halt(reason)
            # Signal the web process: auth -> Reconnect CTA; rate-limit -> a clear banner.
            write_health(scanner_id, ok=False, need_login=isinstance(e, ApiAuthError),
                         rate_limited=rate_limited, reason=reason)
            print('FATAL: FYERS data API unavailable; stopping live confirmation. '
                  'Do not trade from cached Radar statuses. ' + str(e)[:160])
            return
        except ApiError as e:
            failures_in_a_row += 1
            if failures_in_a_row >= 3:
                engine.halt('Repeated FYERS historical data failures; scanning stopped')
                print('FATAL: Repeated FYERS history errors. Scanner halted to prevent retry storm.')
                return
            engine.update_health(f'History sync error ({failures_in_a_row}/3): {str(e)[:120]}')
            time.sleep(1)
        except Exception as e:
            engine.update_health(f'History reconcile issue: {type(e).__name__}: {e}')
            time.sleep(1)
        if time.monotonic() - last_heartbeat > 60:
            last_heartbeat = time.monotonic()
            snap = engine.snapshot()
            print(f'{snap["server_time_ist"]} OR ready={snap["anchors_ready"]}/{snap["monitored"]} '
                  f'candidates={snap["active_candidates"]}, events={len(engine.events)}')
        time.sleep(0.2)
