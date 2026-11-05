"""Per-household radar data source: real scanner on the connected broker, else demo.

If any member of the household has a connected FYERS broker with a live token, the household
runs the real scanner (that broker's token + the chosen universe). Otherwise the shared demo
feed is used so the product is always explorable. `data_mode` tells the UI which is live.
"""
from __future__ import annotations
import os
import threading
from datetime import timezone

from sqlalchemy.orm import Session

from radar import universe as U
from radar.control import ControlCenter
from radar.utils import IST, now_ist

from .crypto import decrypt
from .models import BrokerConnection, User

_demo: ControlCenter | None = None
_live: dict[int, ControlCenter] = {}
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


def _household_broker(db: Session, household_id: int) -> BrokerConnection | None:
    return (db.query(BrokerConnection).join(User, BrokerConnection.user_id == User.id)
            .filter(User.household_id == household_id, BrokerConnection.broker == 'fyers',
                    BrokerConnection.token_enc.isnot(None), BrokerConnection.app_id.isnot(None))
            .first())


def _universe_index(user: User) -> str:
    data = (user.settings.data if user.settings else None) or {}
    idx = data.get('universe_index') or U.DEFAULT
    return idx if U.is_valid(idx) else U.DEFAULT


def _live_cc(household_id: int, app_id: str, token: str, idx: str) -> ControlCenter:
    with _lock:
        cc = _live.get(household_id)
        if cc is None:
            cc = ControlCenter(demo=False, env_extra={
                'FYERS_APP_ID': app_id, 'FYERS_ACCESS_TOKEN': token,
                'RADAR_UNIVERSE_INDEX': idx})
            cc.scanner_port = _LIVE_PORT_BASE + (household_id % 40)
            cc.pid_path = cc.root / 'data' / f'.scanner_live_{household_id}.pid'
            _live[household_id] = cc
        try:
            if not cc.scanner_status()['running']:
                cc.start_scanner()
        except Exception as e:
            print(f'live scanner start skipped: {e}')
        return cc


def _token_is_fresh_today(conn: BrokerConnection) -> bool:
    """True if the access token was already minted during today's IST calendar day."""
    ts = conn.token_refreshed_at
    if not ts:
        return False
    if ts.tzinfo is None:  # SQLite returns naive; we store UTC
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(IST).date() == now_ist().date()


def ensure_fresh_token(db: Session, conn: BrokerConnection) -> str | None:
    """Return the stored access token. NOTE: SEBI rules disable programmatic token refresh for
    Indian brokers (FYERS, Zerodha, …) — a fresh token requires a manual daily login, so we never
    auto-refresh. Freshness is checked by the caller via `_token_is_fresh_today`."""
    return decrypt(conn.token_enc)


def connected_brokers(db: Session) -> list[BrokerConnection]:
    """All broker connections that can drive a live scanner (have app_id + a token or refresh)."""
    return (db.query(BrokerConnection)
            .filter(BrokerConnection.broker == 'fyers', BrokerConnection.app_id.isnot(None),
                    BrokerConnection.secret_enc.isnot(None))
            .filter((BrokerConnection.token_enc.isnot(None)) | (BrokerConnection.refresh_enc.isnot(None)))
            .all())


def start_for_household(db: Session, conn: BrokerConnection) -> bool:
    """Scheduler entry point: start this household's live scanner — only if today's token is
    present (a SEBI-compliant daily login has happened). Returns False if a daily login is needed."""
    if not _token_is_fresh_today(conn):
        return False
    token = decrypt(conn.token_enc)
    if not token:
        return False
    idx = _universe_index(conn.user)
    _live_cc(conn.user.household_id, conn.app_id, token, idx)
    return True


def radar_state(db: Session, user: User) -> dict:
    """Opportunities from the household's connected broker (today's FYERS data). No fake fallback.
    SEBI requires a fresh broker login each trading day, so a token from a previous day = need_login
    (not an error). RADAR_DEMO=1 force-enables the simulated feed (public marketing demo only)."""
    idx = _universe_index(user)
    conn = _household_broker(db, user.household_id)
    if conn:
        token = decrypt(conn.token_enc)
        if token and _token_is_fresh_today(conn):
            st = _live_cc(user.household_id, conn.app_id, token, idx).live_state()
            st['data_mode'] = 'live'
            st['universe'] = U.label_for(idx)
            st['broker'] = conn.broker
            return st
        if token:  # have a token, but it's from a previous day — SEBI daily login needed
            return {'offline': True, 'need_login': True, 'data_mode': 'none',
                    'universe': U.label_for(idx), 'broker': conn.broker,
                    'reason': 'Your FYERS session has expired. SEBI requires a fresh broker login '
                              'each trading day — reconnect to resume today\'s scan.'}
    if os.environ.get('RADAR_DEMO') == '1':
        st = _demo_cc().live_state()
        st['data_mode'] = 'demo'
        st['universe'] = U.label_for(idx)
        return st
    return {'offline': True, 'need_broker': True, 'data_mode': 'none',
            'universe': U.label_for(idx),
            'reason': 'Connect your broker to load today\'s opportunities from live market data.'}
