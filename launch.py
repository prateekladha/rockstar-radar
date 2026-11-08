#!/usr/bin/env python3
"""Read-only FYERS NIFTY ORB pilot. No order APIs or broker write operations."""
from __future__ import annotations
# macOS/Windows/Linux native trust store, retaining full TLS certificate verification.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass  # Fall back to Python's normal CA bundle if truststore is not installed.
import argparse
import fcntl  # macOS/Linux advisory lock; prevents two Radar instances using the FYERS REST quota.
import os
import shutil
import sys
from datetime import timedelta
from pathlib import Path
from radar.utils import ROOT, load_config, market_dt, now_ist, read_env


def main():
    parser = argparse.ArgumentParser(description='Rockstar Radar: NSE 5-minute intraday ORB pilot')
    parser.add_argument('command', choices=['demo', 'download-universe', 'login',
                                            'login-url', 'login-finish',
                                            'prepare', 'warmup', 'live', 'run', 'audit', 'doctor',
                                            'app'])
    parser.add_argument('redirect_url', nargs='?',
                        help='For login-finish: the full redirect URL pasted from the browser')
    parser.add_argument('--config', default=str(ROOT / 'config.json'))
    parser.add_argument('--universe', default=str(ROOT / 'data' / 'nifty500.csv'))
    parser.add_argument('--selection', default=str(ROOT / 'data' / 'today100.json'))
    # Per-account API lock. Different FYERS accounts have separate REST quotas, so in the
    # multi-tenant server each broker-owner's scanner gets its own lock (the server passes this)
    # — a global lock would wrongly block the 2nd owner. Defaults to the single shared lock.
    parser.add_argument('--lock', default=str(ROOT / 'data' / '.fyers_api_process.lock'))
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--force', action='store_true', help='Refresh baseline cache (warmup)')
    parser.add_argument('--day', help='YYYY-MM-DD for audit, defaults to local trading day')
    args = parser.parse_args()
    read_env()
    cfg = load_config(args.config)
    api_lock = None
    try:
        # 'app' (Control Center) must NOT hold the API lock: it spawns the scanner
        # subprocess which takes the lock itself. 'demo' makes no API calls.
        if args.command not in ('demo', 'app'):
            lock_path = Path(args.lock)
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            api_lock = lock_path.open('a+')
            try:
                fcntl.flock(api_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as e:
                raise RuntimeError('Another Rockstar Radar process is already running FYERS '
                                   'commands from this folder. Stop it before running a '
                                   'second login, prepare, doctor, run, or audit.') from e
        if args.command == 'demo':
            from radar.demo import demo_engine
            from radar.dashboard import serve
            print('SIMULATION ONLY. Fabricated candles. No FYERS API connected.')
            serve(demo_engine(cfg), args.port, mode='SIMULATION')
        elif args.command == 'download-universe':
            from radar.selecting import download_nifty_csv
            rows = download_nifty_csv(cfg['universe_url'], Path(args.universe))
            print(f'Downloaded {len(rows)} NSE EQ index constituents to {args.universe}')
        elif args.command == 'login':
            from radar.fyers import login_interactive
            login_interactive()
        elif args.command == 'login-url':
            from radar.fyers import login_url
            login_url()
        elif args.command == 'login-finish':
            from radar.fyers import login_finish
            login_finish(args.redirect_url)
        elif args.command == 'doctor':
            from radar.fyers import FyersAdapter
            FyersAdapter(cfg).doctor(Path(args.universe))
        elif args.command == 'app':
            import uvicorn
            # Local default binds to localhost; cloud (Cloud Run) sets HOST=0.0.0.0 and PORT.
            host = os.environ.get('HOST', '127.0.0.1')
            port = int(os.environ.get('PORT', args.port))
            where = 'the cloud' if host == '0.0.0.0' else 'this computer only'
            print(f'Rockstar Radar Control Center on {host}:{port} ({where})')
            uvicorn.run('radar.api:app', host=host, port=port, log_level='warning')
        elif args.command in ('prepare', 'run'):
            from radar.fyers import FyersAdapter
            from radar.selecting import download_nifty_csv, prepare_selection, read_selection, load_morning_pins
            # At/after the configured scan window, don't launch hundreds of
            # selection REST requests just to open a review-only dashboard.
            # A previously saved same-day selection is mandatory for review.
            closed_at = market_dt(now_ist().date(), cfg['new_signals_stop']) + timedelta(
                minutes=cfg['retest_expiry_minutes'])
            if args.command == 'run' and now_ist() >= closed_at:
                if not Path(args.selection).exists():
                    raise ValueError('Today\'s scan window has ended and no same-day '
                                     'selection is saved. No FYERS requests were made.')
                payload, _ = read_selection(Path(args.selection))
                if payload.get('for_session') != now_ist().date().isoformat():
                    raise ValueError('Today\'s scan window has ended; last selection is '
                                     'from a different day. No FYERS requests were made.')
                from radar.service import start_live
                start_live(cfg, Path(args.selection), args.port)
                return
            # Universe = the configured/overridden index (any index / cap), cached per index.
            from radar import universe as U
            idx = os.environ.get('RADAR_UNIVERSE_INDEX') or cfg.get('universe_index') or U.DEFAULT
            if not U.is_valid(idx):
                idx = U.DEFAULT
            path = ROOT / 'data' / f'universe_{idx}.csv'
            if not path.exists():
                download_nifty_csv(U.url_for(idx), path)
            print(f'Universe: {U.label_for(idx)}')
            adapter = FyersAdapter(cfg)
            if args.command == 'prepare' or not Path(args.selection).exists():
                prepare_selection(adapter, cfg, path, Path(args.selection))
            else:
                payload, _ = read_selection(Path(args.selection))
                if (payload.get('for_session') != now_ist().date().isoformat() or
                    payload.get('morning_requested', []) != load_morning_pins(cfg)):
                    prepare_selection(adapter, cfg, path, Path(args.selection))
            if args.command == 'run':
                from radar.service import start_live
                start_live(cfg, Path(args.selection), args.port)
        elif args.command == 'warmup':
            from radar.fyers import FyersAdapter
            from radar.selecting import read_selection
            from radar.service import build_baselines
            payload, infos = read_selection(Path(args.selection))
            day = now_ist().date()
            if payload.get('for_session') != day.isoformat():
                raise ValueError('Selection must be prepared for today before warmup.')
            adapter = FyersAdapter(cfg)
            result = build_baselines(adapter, [s.symbol for s in infos], day, cfg, force=args.force)
            print('Volume baseline ready:', sum(bool(x) for x in result.values()), '/', len(infos))
        elif args.command == 'live':
            from radar.service import start_live
            start_live(cfg, Path(args.selection), args.port)
        elif args.command == 'audit':
            from datetime import date
            from radar.fyers import FyersAdapter
            from radar.audit import audit_day
            day = date.fromisoformat(args.day) if args.day else now_ist().date()
            if now_ist() < now_ist().replace(hour=15,minute=35,second=0,microsecond=0) and day == now_ist().date():
                raise ValueError('Run audit after 15:35 IST for full-session completed data.')
            audit_day(FyersAdapter(cfg), cfg, day)
    except (ValueError, OSError, RuntimeError) as e:
        # Record a health signal the web process can read: an auth/token failure during selection or
        # live run means this broker needs a fresh login (Reconnect CTA + shared-feed fallback).
        if args.command in ('run', 'prepare', 'live', 'warmup'):
            from radar.health import write_health
            msg = str(e).lower()
            is_auth = any(k in msg for k in ('token expired', 'token expired/invalid', 'valid token',
                                             '(-15)', '(-16)', 'auth'))
            is_rl = any(k in msg for k in ('rate limit', '-360', '5,000', 'requests/day'))
            if is_auth:
                reason = ('Your broker session has expired. Log in to your broker for today to '
                          'resume the live scan.')
            elif is_rl:
                reason = ('Your broker hit its daily API limit (FYERS Standard allows 5,000 '
                          'requests/day). Live scanning pauses and resumes when the limit resets '
                          'next trading day. This is a broker limit, not a Rockstar Radar issue.')
            else:
                reason = 'Live broker data is temporarily unavailable.'
            write_health(os.environ.get('RADAR_SCANNER_ID', ''),
                         ok=False, need_login=is_auth, rate_limited=is_rl, reason=reason)
        print(f'ERROR: {e}', file=sys.stderr)
        sys.exit(2)
    finally:
        if api_lock is not None:
            fcntl.flock(api_lock.fileno(), fcntl.LOCK_UN)
            api_lock.close()


if __name__ == '__main__':
    main()
