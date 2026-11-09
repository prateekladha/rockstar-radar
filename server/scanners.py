"""Per-user radar data source.

Feed priority for a user:
  1. Their OWN connected broker, when its feed is actually healthy — their own live feed.
  2. Else the household's shared broker (prefer the admin's) — read-only shared feed + watchlist.
     This is the FALLBACK when a user's own broker is down (expired/auth-failed/rate-limited), so a
     teammate still sees the market via the owner's already-running scanner (no extra FYERS load).
  3. Else need_login (reconnect CTA) / need_broker (or the RADAR_DEMO marketing feed).

Trading always requires the user's OWN broker (see routers/trading.py) — the shared fallback is for
read-only market data only.

Each distinct broker runs ONE scanner, keyed by the broker's owner. SEBI requires a fresh broker
login each trading day; a stale OR runtime-rejected token = need_login. Feed health comes from the
scanner's own status signal (radar.health), not just DB token freshness.
"""
from __future__ import annotations
import os
import socket
import threading
from datetime import timezone

from sqlalchemy.orm import Session

from radar import health
from radar import universe as U
from radar.control import ControlCenter
from radar.utils import IST, now_ist

from . import watchpins
from .crypto import decrypt
from .models import BrokerConnection, User

_demo: ControlCenter | None = None
_scanners: dict[str, ControlCenter] = {}   # key "u<owner_id>" -> ControlCenter
_sim_ccs: dict[int, ControlCenter] = {}    # user_id -> their accelerated sim ControlCenter
_lock = threading.Lock()


def _free_port() -> int:
    """An OS-assigned free localhost port. Replaces the old `base + owner_id % 60` scheme, which
    collided whenever two owner ids were congruent mod 60 and hard-capped concurrent scanners at 60."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]
    finally:
        s.close()


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


def _sim_speed(user: User) -> str:
    data = (user.settings.data if user.settings else None) or {}
    try:
        return str(int(float(data.get('sim_speed', 10) or 30)))
    except (TypeError, ValueError):
        return '30'


def _sim_cc_for(user: User) -> ControlCenter:
    """The user's accelerated simulation scanner (no FYERS, no login)."""
    key = f'sim{user.id}'
    start, end = (user.sim_start or '09:15'), (user.sim_end or '15:30')
    with _lock:
        cc = _sim_ccs.get(user.id)
        env = {'RADAR_SIM_START': start, 'RADAR_SIM_END': end,
               'RADAR_SIM_SPEED': _sim_speed(user), 'RADAR_SCANNER_ID': key}
        if cc is None:
            cc = ControlCenter(demo=False, sim=True, env_extra=env)
            cc.pid_path = cc.root / 'data' / f'.sim_{key}.pid'
            cc.scanner_out_path = cc.root / 'data' / f'sim_{key}.out'
            _sim_ccs[user.id] = cc
        else:
            cc.env_extra.update(env)
        try:
            if not cc.scanner_status()['running']:
                cc.scanner_port = _free_port()
                cc.start_scanner()
        except Exception as e:
            print(f'sim scanner start skipped ({key}): {e}')
        return cc


def stop_sim(user_id: int) -> None:
    """Stop a user's sim scanner (on disabling sim, or to restart with fresh settings)."""
    with _lock:
        cc = _sim_ccs.get(user_id)
    if cc:
        try:
            cc.stop_scanner()
        except Exception as e:
            print(f'sim stop skipped (u{user_id}): {e}')


def any_sim_active(db: Session) -> bool:
    return db.query(User).filter(User.sim_enabled == 1).count() > 0


def _own_broker(db: Session, user: User) -> BrokerConnection | None:
    """The user's OWN registered broker (app_id + secret present)."""
    return (db.query(BrokerConnection)
            .filter(BrokerConnection.user_id == user.id, BrokerConnection.broker == 'fyers',
                    BrokerConnection.app_id.isnot(None), BrokerConnection.secret_enc.isnot(None))
            .first())


def _household_broker(db: Session, household_id: int,
                      exclude_user_id: int | None = None) -> BrokerConnection | None:
    """The household's shared broker — prefer an admin's, freshly-logged-in one. ``exclude_user_id``
    skips the caller's own broker so the shared feed is a genuine fallback to someone else's."""
    q = (db.query(BrokerConnection).join(User, BrokerConnection.user_id == User.id)
         .filter(User.household_id == household_id, BrokerConnection.broker == 'fyers',
                 BrokerConnection.app_id.isnot(None), BrokerConnection.secret_enc.isnot(None)))
    if exclude_user_id is not None:
        q = q.filter(BrokerConnection.user_id != exclude_user_id)
    return q.order_by(User.role.asc(), BrokerConnection.token_refreshed_at.desc()).first()


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
                'RADAR_MORNING_PINS': pins, 'RADAR_SCANNER_ID': key})
            # Per-owner working files so concurrent brokers never collide (separate FYERS API lock —
            # each account has its own REST quota — plus separate selection, pid and log).
            cc.pid_path = cc.root / 'data' / f'.scanner_live_{key}.pid'
            cc.selection_path = cc.root / 'data' / f'today100_{key}.json'
            cc.lock_path = cc.root / 'data' / f'.fyers_api_{key}.lock'
            cc.scanner_out_path = cc.root / 'data' / f'scanner_{key}.out'
            _scanners[key] = cc
        else:
            # A fresh daily login mints a NEW access token. A long-running scanner subprocess keeps
            # the token it was spawned with, so without this it would keep hitting the broker with a
            # stale/expired token (WS -300 "Please provide valid token", history -16) and the feed
            # never resumes. Detect a credential change and recycle the scanner so it picks up the
            # new token. (Universe changes likewise need a fresh selection.)
            cur = cc.env_extra
            changed = (cur.get('FYERS_ACCESS_TOKEN') != token
                       or cur.get('FYERS_APP_ID') != app_id
                       or cur.get('RADAR_UNIVERSE_INDEX') != idx)
            cur['FYERS_ACCESS_TOKEN'] = token
            cur['FYERS_APP_ID'] = app_id
            cur['RADAR_UNIVERSE_INDEX'] = idx
            cur['RADAR_MORNING_PINS'] = pins
            if changed:
                health.clear_health(key)   # fresh creds get a clean slate; re-reports on (re)start
                try:
                    if cc.scanner_status()['running']:
                        cc.stop_scanner()
                except Exception as e:
                    print(f'scanner stop before token refresh skipped ({key}): {e}')
        try:
            if not cc.scanner_status()['running']:
                cc.scanner_port = _free_port()   # a fresh free port on every (re)start
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


def _auth_failed_health(conn: BrokerConnection) -> dict | None:
    """The scanner's last runtime health IF it says 'needs re-login' and the user hasn't logged in
    again since (a login newer than the failure clears it). None otherwise."""
    h = health.read_health(f'u{conn.user_id}')
    if not h or not h.get('need_login'):
        return None
    h_at = health.health_at(h)
    tok = conn.token_refreshed_at
    if tok is not None:
        tok = tok if tok.tzinfo else tok.replace(tzinfo=timezone.utc)
        if h_at and tok > h_at:
            return None   # logged in after the failure — give the new token a chance
    return h


def _rate_limited_health(conn: BrokerConnection) -> dict | None:
    """The scanner's last health IF it says the broker API was rate-limited today."""
    h = health.read_health(f'u{conn.user_id}')
    if not h or not h.get('rate_limited'):
        return None
    h_at = health.health_at(h)
    if h_at and h_at.astimezone(IST).date() != now_ist().date():
        return None   # a prior day's limit; today is fresh
    return h


def start_for_broker(db: Session, conn: BrokerConnection) -> bool:
    """Scheduler/supervisor entry point: start the owner's scanner if today's token is present and it
    hasn't already runtime-failed auth (don't restart into the same -15/-16 until they re-login)."""
    if not _token_is_fresh_today(conn) or not conn.token_enc:
        return False
    # Don't restart into a known auth failure or a hit rate limit — restarting only burns more of the
    # broker's daily API quota and re-triggers the same error.
    if _auth_failed_health(conn) or _rate_limited_health(conn):
        return False
    _cc_for(conn.user_id, conn.app_id, decrypt(conn.token_enc), _universe_index(conn.user),
            watchpins.pins_env(db, conn.user_id))
    return True


# Back-compat alias for the scheduler.
start_for_household = start_for_broker


def _need_login_state(conn, source, label, reason=None) -> dict:
    if not reason:
        reason = (('Your broker session has expired. SEBI requires a fresh login each trading day — '
                   'log in to resume your scan.') if source == 'own' else
                  'The shared feed will resume once your team admin logs in to the broker today.')
    return {'offline': True, 'need_login': True, 'data_mode': 'none', 'source': source,
            'shared': source == 'shared', 'universe': label, 'broker': conn.broker, 'reason': reason}


def _feed_for(db, conn, user, source, idx) -> tuple[str, dict]:
    """Try one broker's feed. Returns (status, state) where status is:
       'live'/'starting' → usable (return as-is); 'need_login' → prompt reconnect; 'down' → feed
       unavailable (e.g. rate-limited) — caller may fall back to another broker."""
    label = U.label_for(idx)
    if not (conn.token_enc and _token_is_fresh_today(conn)):
        return 'need_login', _need_login_state(conn, source, label)
    h = _auth_failed_health(conn)
    if h:
        return 'need_login', _need_login_state(conn, source, label, h.get('reason'))
    rl = _rate_limited_health(conn)
    if rl:
        return 'down', {'offline': True, 'data_mode': 'none', 'source': source,
                        'shared': source == 'shared', 'universe': label, 'broker': conn.broker,
                        'rate_limited': True, 'reason': rl.get('reason')}

    cc = _cc_for(conn.user_id, conn.app_id, decrypt(conn.token_enc), idx,
                 watchpins.pins_env(db, conn.user_id))
    st = cc.live_state()

    def _is_rl(text):
        return any(k in (text or '').lower() for k in ('daily api limit', 'rate limit', '5,000',
                                                       'requests/day'))

    if st.get('offline'):
        # Process running but dashboard not up yet = warming up (selection in progress). Not a
        # failure — show "starting". A truly dead scanner falls through to 'down'.
        if 'starting' in (st.get('reason') or '').lower():
            st.update({'data_mode': 'live', 'source': source, 'shared': source == 'shared',
                       'universe': label, 'broker': conn.broker, 'warming': True})
            # Surface real warm-up progress (baselines/feed-connect) from the scanner's health file,
            # so the UI shows "Warming up — X/N symbols ready" instead of a vague "starting…". Only
            # trust FRESH progress (within 120s) so a stale value from a prior run isn't shown.
            hfull = health.read_health(f'u{conn.user_id}') or {}
            at = health.health_at(hfull)
            fresh = at is not None and (now_ist() - at).total_seconds() < 120
            wu = hfull.get('warmup') if fresh else None
            if wu and wu.get('total'):
                done, total = int(wu.get('done') or 0), int(wu['total'])
                if wu.get('phase') == 'connecting':
                    st['reason'] = f'Connecting live feed… ({done}/{total} symbols ready)'
                else:
                    st['reason'] = f'Warming up — {done}/{total} symbols ready'
                st['warmup'] = {'done': done, 'total': total, 'phase': wu.get('phase') or 'baselines'}
            return 'starting', st
        return 'down', {'offline': True, 'data_mode': 'none', 'source': source,
                        'shared': source == 'shared', 'universe': label, 'broker': conn.broker,
                        'reason': st.get('reason') or 'Live feed is starting up…'}

    fh = (st.get('feed_health') or '')
    if st.get('halted') or fh.startswith('HALTED'):
        low = fh.lower()
        clean = fh.replace('HALTED — ', '')
        if any(k in low for k in ('expired', 'log in', 'login', 'valid token', 'session')):
            return 'need_login', _need_login_state(conn, source, label, clean)
        return 'down', {'offline': True, 'data_mode': 'none', 'source': source,
                        'shared': source == 'shared', 'universe': label, 'broker': conn.broker,
                        'rate_limited': _is_rl(fh),
                        'reason': clean or 'Live feed temporarily unavailable.'}

    st.update({'data_mode': 'live', 'source': source, 'shared': source == 'shared',
               'universe': label, 'broker': conn.broker})
    return 'live', st


def radar_state(db: Session, user: User) -> dict:
    """The user's radar feed. Simulation (if on) takes over; else prefer their OWN broker, falling back
    to the household's shared broker if their own is down (expired/auth/rate-limited)."""
    if user.sim_enabled:
        st = _sim_cc_for(user).live_state()
        if st.get('offline'):
            reason = (st.get('reason') or '').lower()
            st['data_mode'] = 'none'
            st['reason'] = ('Simulation is starting…' if 'starting' in reason
                            else st.get('reason') or 'Simulation starting…')
        else:
            st['data_mode'] = 'live'
        st.update({'source': 'sim', 'sim': True, 'universe': 'Simulation', 'broker': 'sim',
                   'sim_start': user.sim_start or '09:15', 'sim_end': user.sim_end or '15:30'})
        return st
    label = U.label_for(_universe_index(user))
    own = _own_broker(db, user)
    fallback_state = None   # best non-usable state to show if nothing is usable

    if own:
        status, st = _feed_for(db, own, user, 'own', _universe_index(user))
        if status in ('live', 'starting'):
            return st
        fallback_state = st   # own is down — try the shared feed, else show this

    shared = _household_broker(db, user.household_id, exclude_user_id=user.id)
    if shared:
        status, st = _feed_for(db, shared, user, 'shared', _universe_index(shared.user))
        if status in ('live', 'starting'):
            if own:
                st['fallback'] = True   # tell the UI this is the shared feed because own is down
            return st
        if fallback_state is None:
            fallback_state = st

    if fallback_state is not None:
        return fallback_state
    if os.environ.get('RADAR_DEMO') == '1':
        st = _demo_cc().live_state()
        st['data_mode'] = 'demo'
        st['universe'] = label
        return st
    return {'offline': True, 'need_broker': True, 'data_mode': 'none', 'universe': label,
            'reason': 'Connect your broker to load today\'s opportunities from live market data.'}
