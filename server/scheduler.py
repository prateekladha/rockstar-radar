"""Market-open scheduler — starts each household's scanner on trading mornings.

SEBI requires a manual broker login every trading day (programmatic token refresh is disabled for
FYERS/Zerodha/etc.), so the scanner can only run once the user has logged in that day. On trading
days (Mon–Fri IST) this:
  * ~08:30 — reminds households that still need today's login (so they log in before the open), and
  * ~09:08 — starts the live scanner for every household that HAS logged in today.

Runs as a single background asyncio task inside the FastAPI app. Best-effort and idempotent: a
per-day guard keeps each action to once, and per-household errors never stop the others. The lazy
path in scanners.radar_state also starts the scanner on demand when the user opens the app.

Env knobs (optional): RADAR_SCHED_REMIND_HHMM (default 08:30), RADAR_SCHED_START_HHMM (09:08),
RADAR_SCHED=0 to disable.
"""
from __future__ import annotations
import asyncio
import os

from radar.utils import now_ist

from . import scanners
from .db import SessionLocal

_REMIND_AT = os.environ.get('RADAR_SCHED_REMIND_HHMM', '08:30')
_START_AT = os.environ.get('RADAR_SCHED_START_HHMM', '09:08')
_SUPERVISE_UNTIL = os.environ.get('RADAR_SCHED_SUPERVISE_UNTIL_HHMM', '15:35')
_SUPERVISE_EVERY_MIN = int(os.environ.get('RADAR_SCHED_SUPERVISE_EVERY_MIN', '2'))
_done: dict[str, str] = {}  # action -> last YYYY-MM-DD it ran
_last_supervise_min: int | None = None


def _hhmm(dt) -> str:
    return dt.strftime('%H:%M')


def _is_trading_day(dt) -> bool:
    from radar.utils import is_market_day
    return is_market_day(dt.date())  # Mon-Fri OR a special session (e.g. Diwali Muhurat)


def _run_once(action: str, today: str) -> bool:
    if _done.get(action) == today:
        return False
    _done[action] = today
    return True


def _remind_logins() -> None:
    """Nudge households that still need today's SEBI-mandated broker login before the open."""
    db = SessionLocal()
    try:
        conns = scanners.connected_brokers(db)
        need = [c for c in conns if not scanners._token_is_fresh_today(c)]
        for c in need:
            # TODO: send via the household's Telegram if configured (AlertConfig). For now, log.
            print(f'[scheduler] reminder: household {c.user.household_id} needs today\'s FYERS login')
        print(f'[scheduler] login reminder: {len(need)}/{len(conns)} households need to log in today')
    finally:
        db.close()


def _start_all_scanners() -> None:
    db = SessionLocal()
    try:
        conns = scanners.connected_brokers(db)
        ok = skipped = 0
        for c in conns:
            try:
                if scanners.start_for_household(db, c):
                    ok += 1
                else:
                    skipped += 1   # no fresh token yet — awaiting today's login
            except Exception as e:
                print(f'[scheduler] scanner start failed (conn {c.id}): {e}')
        print(f'[scheduler] market-open: {ok} scanning, {skipped} awaiting today\'s login')
    finally:
        db.close()


def _supervise_scanners() -> None:
    """Auto-restart any scanner that should be running but isn't (crashed/OOM) — but never one that
    runtime-failed auth (start_for_broker skips those until the user re-logs in). Quiet unless it acts."""
    db = SessionLocal()
    try:
        restarted = 0
        for c in scanners.connected_brokers(db):
            try:
                cc = scanners._scanners.get(f'u{c.user_id}')
                was_running = bool(cc and cc.scanner_status()['running'])
                if not was_running and scanners.start_for_broker(db, c):
                    restarted += 1
            except Exception as e:
                print(f'[scheduler] supervise failed (conn {c.id}): {e}')
        if restarted:
            print(f'[scheduler] supervisor restarted {restarted} scanner(s)')
    finally:
        db.close()


async def run_scheduler() -> None:
    print(f'[scheduler] on — login reminder {_REMIND_AT} IST, scanner start {_START_AT} IST (trading days)')
    while True:
        try:
            now = now_ist()
            today = now.date().isoformat()
            if _is_trading_day(now):
                hhmm = _hhmm(now)
                if hhmm >= _REMIND_AT and _run_once('remind', today):
                    await asyncio.to_thread(_remind_logins)
                if hhmm >= _START_AT and _run_once('start', today):
                    await asyncio.to_thread(_start_all_scanners)
                # Supervisor: during market hours, keep scanners up (restart crashes) every few min.
                global _last_supervise_min
                if _START_AT <= hhmm <= _SUPERVISE_UNTIL:
                    cur_min = now.hour * 60 + now.minute
                    if _last_supervise_min is None or cur_min - _last_supervise_min >= _SUPERVISE_EVERY_MIN:
                        _last_supervise_min = cur_min
                        await asyncio.to_thread(_supervise_scanners)
        except Exception as e:  # the loop must survive anything
            print(f'[scheduler] tick error: {e}')
        await asyncio.sleep(30)
