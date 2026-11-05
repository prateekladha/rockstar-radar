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
_done: dict[str, str] = {}  # action -> last YYYY-MM-DD it ran


def _hhmm(dt) -> str:
    return dt.strftime('%H:%M')


def _is_trading_day(dt) -> bool:
    return dt.weekday() < 5  # Mon-Fri; NSE holidays are a later refinement


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
        except Exception as e:  # the loop must survive anything
            print(f'[scheduler] tick error: {e}')
        await asyncio.sleep(30)
