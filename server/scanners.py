"""Per-user radar data source.

Feed priority for a user:
  1. Their OWN connected broker (if registered) — their feed/watchlist come from their broker only.
  2. Else the household's shared broker (the admin's) — read-only shared feed + watchlist.
  3. Else need_broker (or the RADAR_DEMO marketing feed).

Each distinct broker runs ONE scanner, keyed by the broker's owner (so the admin's own feed and a
teammate's shared feed reuse the same scanner — never two sessions on one token). SEBI requires a
fresh broker login each trading day; a stale token = need_login.
"""
from __future__ import annotations
import os
import threading
from datetime import timezone

from sqlalchemy.orm import Session

from radar import universe as U
from radar.control import ControlCenter
from radar.utils import IST, now_ist

from . import watchpins
from .crypto import decrypt
from .models import BrokerConnection, User

_demo: ControlCenter | None = None
_scanners: dict[str, ControlCenter] = {}   # key "u<owner_id>" -> ControlCenter
_lock = threading.Lock()
_LIVE_PORT_BASE = 8950


def _demo_cc() -> ControlCenter:
    global _demo
    if _demo is None:
        _demo = ControlCenter(demo=True)
    try:
        if not _demo.scanner_status()['running']:
            _demo.start_scanner()
    except Exception as e:  # never block the UI
        print(f'demo scanner start skipped: {e}')
    return _demo


def _own_broker(db: Session, user: User) -> BrokerConnection | None:
    """The user's OWN registered broker (app_id + secret present)."""
    return (db.query(BrokerConnection)
            .filter(BrokerConnection.user_id == user.id, BrokerConnection.broker == 'fyers',
                    BrokerConnection.app_id.isnot(None), BrokerConnection.secret_enc.isnot(None))
            .first())


def _household_broker(db: Session, household_id: int) -> BrokerConnection | None:
    """The household's shared broker — prefer the admin's, and a freshly-logged-in one."""
    return (db.query(BrokerConnection).join(User, BrokerConnection.user_id == User.id)
            .filter(User.household_id == household_id, BrokerConnection.broker == 'fyers',
                    BrokerConnection.app_id.isnot(None), BrokerConnection.secret_enc.isnot(None))
            .order_by(User.role.asc(), BrokerConnection.token_refreshed_at.desc())
            .first())


def _universe_index(user: User) -> str:
    data = (user.settings.data if user.settings else None) or {}
    idx = data.get('universe_index') or U.DEFAULT
    return idx if U.is_valid(idx) else U.DEFAULT


def _token_is_fresh_today(conn: BrokerConnection) -> bool:
    """True if the access token was minted during today's IST calendar day (SEBI daily login)."""
    ts = conn.token_refreshed_at
    if not ts:
        return False
    if ts.tzinfo is None:  # SQLite returns naive; we store UTC
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(IST).date() == now_ist().date()


def _cc_for(owner_id: int, app_id: str, token: str, idx: str, pins: str = '') -> ControlCenter:
    """One scanner per broker owner (keyed by their user id). ``pins`` are the owner's manual
    watchlist tickers (comma-joined, canonical) — priority-scanned and force-included even if
    outside the chosen universe. They take effect on the owner's next scanner (re)start."""
    key = f'u{owner_id}'
    with _lock:
        cc = _scanners.get(key)
        if cc is None:
            cc = ControlCenter(demo=False, env_extra={
                'FYERS_APP_ID': app_id, 'FYERS_ACCESS_TOKEN': token, 'RADAR_UNIVERSE_INDEX': idx,
                'RADAR_MORNING_PINS': pins})
            cc.scanner_port = _LIVE_PORT_BASE + (owner_id % 60)
            cc.pid_path = cc.root / 'data' / f'.scanner_live_{key}.pid'
            _scanners[key] = cc
        else:
            # Keep the owner's pins current so the next scan session picks up any changes.
            cc.env_extra['RADAR_MORNING_PINS'] = pins
        try:
            if not cc.scanner_status()['running']:
                cc.start_scanner()
        except Exception as e:
            print(f'live scanner start skipped ({key}): {e}')
        return cc


def effective_broker(db: Session, user: User):
    """Return (broker_connection, source) the user's radar should read: their own, else shared."""
    own = _own_broker(db, user)
    if own:
        return own, 'own'
    return _household_broker(db, user.household_id), 'shared'


def connected_brokers(db: Session) -> list[BrokerConnection]:
    """All registered broker connections (for the scheduler to start/refresh)."""
    return (db.query(BrokerConnection)
            .filter(BrokerConnection.broker == 'fyers', BrokerConnection.app_id.isnot(None),
                    BrokerConnection.secret_enc.isnot(None))
            .filter((BrokerConnection.token_enc.isnot(None)) | (BrokerConnection.refresh_enc.isnot(None)))
            .all())


def start_for_broker(db: Session, conn: BrokerConnection) -> bool:
    """Scheduler entry point: start the owner's scanner if today's token is present."""
    if not _token_is_fresh_today(conn) or not conn.token_enc:
        return False
    _cc_for(conn.user_id, conn.app_id, decrypt(conn.token_enc), _universe_index(conn.user),
            watchpins.pins_env(db, conn.user_id))
    return True


# Back-compat alias for the scheduler.
start_for_household = start_for_broker


def radar_state(db: Session, user: User) -> dict:
    """Opportunities from the user's effective broker (own first, else the household's shared one)."""
    idx = _universe_index(user)
    label = U.label_for(idx)
    conn, source = effective_broker(db, user)
    if conn:
        if conn.token_enc and _token_is_fresh_today(conn):
            # Shared feed reuses the owner's scanner + the owner's universe (one scanner per broker).
            use_idx = idx if source == 'own' else _universe_index(conn.user)
            st = _cc_for(conn.user_id, conn.app_id, decrypt(conn.token_enc), use_idx,
                         watchpins.pins_env(db, conn.user_id)).live_state()
            st['data_mode'] = 'live'
            st['source'] = source
            st['shared'] = (source == 'shared')
            st['universe'] = U.label_for(use_idx)
            st['broker'] = conn.broker
            return st
        # Broker registered but no fresh token today (SEBI daily login).
        if source == 'own':
            reason = ('Your broker session has expired. SEBI requires a fresh login each trading '
                      'day — log in to resume your scan.')
        else:
            reason = ('The shared feed will resume once your team admin logs in to the broker today.')
        return {'offline': True, 'need_login': True, 'data_mode': 'none', 'source': source,
                'shared': source == 'shared', 'universe': label, 'broker': conn.broker,
                'reason': reason}
    if os.environ.get('RADAR_DEMO') == '1':
        st = _demo_cc().live_state()
        st['data_mode'] = 'demo'
        st['universe'] = label
        return st
    return {'offline': True, 'need_broker': True, 'data_mode': 'none', 'universe': label,
            'reason': 'Connect your broker to load today\'s opportunities from live market data.'}
