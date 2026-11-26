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
import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from radar import health
from radar import universe as U
from radar.control import ControlCenter
from radar.utils import IST, now_ist

from . import watchpins
from .crypto import decrypt
from .models import BrokerConnection, Order, User

_demo: ControlCenter | None = None
_scanners: dict[str, ControlCenter] = {}   # key "u<owner_id>" -> ControlCenter
_sim_ccs: dict[int, ControlCenter] = {}    # user_id -> their accelerated sim ControlCenter
_lock = threading.Lock()

# A scanner that crashes on start must not be respawned on every ~3s radar poll — each respawn
# re-fetches ~100 FYERS history baselines and can burn the whole 5,000/day quota in minutes. Cap
# (re)start attempts per owner to at most one per this many seconds.
_RESTART_COOLDOWN_SECS = 45.0
_last_start_attempt: dict[str, float] = {}   # key "u<owner_id>" -> monotonic time of last spawn

# --- web/scanner split (OKE migration P2) ---------------------------------------------------------
# When SCANNER_HOST is set (the `web` pod), this process owns NO scanners: radar_state/smc_state proxy
# over HTTP to the `scanner` pod's /internal endpoints. When it is unset (the `scanner` pod, local dev,
# or the single-container VM) everything runs locally exactly as before — the split is transparent.
SCANNER_HOST = os.environ.get('SCANNER_HOST') or ''
SCANNER_INTERNAL_PORT = int(os.environ.get('SCANNER_INTERNAL_PORT', '8080') or 8080)
INTERNAL_TOKEN = os.environ.get('INTERNAL_TOKEN', '') or ''


def _proxy_internal(path: str, user_id: int, extra: str = '') -> dict:
    """GET the scanner pod's internal state endpoint (web pod only). Read-only; cluster-internal."""
    import json
    import urllib.error
    import urllib.request
    url = f'http://{SCANNER_HOST}:{SCANNER_INTERNAL_PORT}/internal/{path}?user_id={int(user_id)}{extra}'
    req = urllib.request.Request(url, headers={'X-Internal-Token': INTERNAL_TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, OSError, ValueError):
        return {'offline': True, 'data_mode': 'none',
                'reason': 'The scanner is starting up. Live data resumes shortly.'}


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


def _one_minute(user: User) -> str:
    """The user's signal-candle choice, as the env flag the scanner subprocess reads.

    Defaults to off, matching config.json, so a user who has never opened Settings scans on
    5-minute candles — the setting this product ran on for its whole history.
    """
    data = (user.settings.data if user.settings else None) or {}
    return '1' if data.get('use_one_minute_candles', False) else '0'


def _rvol_env(user: User) -> tuple[str, str]:
    """The owner's RVOL calculation choice (mode, length) as env strings for the subprocess.

    Scanners are per-owner, so the whole feed uses the OWNER's RVOL mode/length (like the other
    engine-level settings). Defaults match config.json (cumulative / 10). utils.load_config reads
    RADAR_RVOL_MODE / RADAR_RVOL_LENGTH back into config inside the subprocess.
    """
    s = user.settings
    mode = (getattr(s, 'rvol_calculation_mode', None) if s else None) or 'cumulative'
    length = (getattr(s, 'rvol_length', None) if s else None) or 10
    return str(mode), str(int(length))


def _sim_cc_for(user: User) -> ControlCenter:
    """The user's accelerated simulation scanner (no FYERS, no login)."""
    key = f'sim{user.id}'
    start, end = (user.sim_start or '09:15'), (user.sim_end or '15:30')
    with _lock:
        cc = _sim_ccs.get(user.id)
        _rmode, _rlen = _rvol_env(user)
        env = {'RADAR_SIM_START': start, 'RADAR_SIM_END': end,
               'RADAR_SIM_SPEED': _sim_speed(user), 'RADAR_SCANNER_ID': key,
               'RADAR_ONE_MINUTE': _one_minute(user),
               'RADAR_RVOL_MODE': _rmode, 'RADAR_RVOL_LENGTH': _rlen}
        if cc is None:
            cc = ControlCenter(demo=False, sim=True, env_extra=env)
            cc.pid_path = cc.root / 'data' / f'.sim_{key}.pid'
            cc.scanner_out_path = cc.root / 'data' / f'sim_{key}.out'
            _sim_ccs[user.id] = cc
        elif cc.env_extra.get('RADAR_ONE_MINUTE') != env['RADAR_ONE_MINUTE']:
            # The interval is baked into the engine at construction, so a running practice session
            # can't adopt it. Recycle rather than leave the toggle looking applied but inert.
            cc.env_extra.update(env)
            try:
                if cc.scanner_status()['running']:
                    cc.stop_scanner()
            except Exception as e:
                print(f'sim stop before interval change skipped ({key}): {e}')
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


def _cc_for(owner_id: int, app_id: str, token: str, idx: str, pins: str = '',
            one_min: str = '1', rvol_mode: str = 'cumulative', rvol_length: str = '10') -> ControlCenter:
    """One scanner per broker owner (keyed by their user id). ``pins`` are the owner's manual
    watchlist tickers (comma-joined, canonical) — priority-scanned and force-included even if
    outside the chosen universe. They take effect on the owner's next scanner (re)start."""
    key = f'u{owner_id}'
    with _lock:
        cc = _scanners.get(key)
        if cc is None:
            cc = ControlCenter(demo=False, env_extra={
                'FYERS_APP_ID': app_id, 'FYERS_ACCESS_TOKEN': token, 'RADAR_UNIVERSE_INDEX': idx,
                'RADAR_MORNING_PINS': pins, 'RADAR_SCANNER_ID': key,
                'RADAR_ONE_MINUTE': one_min,
                'RADAR_RVOL_MODE': rvol_mode, 'RADAR_RVOL_LENGTH': rvol_length})
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
            # The signal interval is fixed when the engine is built, so a change here needs the
            # same recycle as new credentials — otherwise the setting reads as applied but isn't.
            changed = (cur.get('FYERS_ACCESS_TOKEN') != token
                       or cur.get('FYERS_APP_ID') != app_id
                       or cur.get('RADAR_UNIVERSE_INDEX') != idx
                       or cur.get('RADAR_ONE_MINUTE') != one_min
                       or cur.get('RADAR_RVOL_MODE') != rvol_mode
                       or cur.get('RADAR_RVOL_LENGTH') != rvol_length)
            cur['FYERS_ACCESS_TOKEN'] = token
            cur['FYERS_APP_ID'] = app_id
            cur['RADAR_UNIVERSE_INDEX'] = idx
            cur['RADAR_MORNING_PINS'] = pins
            cur['RADAR_ONE_MINUTE'] = one_min
            cur['RADAR_RVOL_MODE'] = rvol_mode
            cur['RADAR_RVOL_LENGTH'] = rvol_length
            if changed:
                health.clear_health(key)   # fresh creds get a clean slate; re-reports on (re)start
                try:
                    if cc.scanner_status()['running']:
                        cc.stop_scanner()
                except Exception as e:
                    print(f'scanner stop before token refresh skipped ({key}): {e}')
        try:
            if not cc.scanner_status()['running']:
                now = time.monotonic()
                if now - _last_start_attempt.get(key, 0.0) >= _RESTART_COOLDOWN_SECS:
                    _last_start_attempt[key] = now
                    cc.scanner_port = _free_port()   # a fresh free port on every (re)start
                    cc.start_scanner()
                # else: within the cooldown — a scanner that keeps crashing on start must not be
                # respawned every poll (quota burn). Leave it stopped; radar_state then falls through
                # to the household's shared feed, and we retry at most once per cooldown window.
        except Exception as e:
            print(f'live scanner start skipped ({key}): {e}')
        return cc


def effective_broker(db: Session, user: User):
    """Return (broker_connection, source) the user's radar should read: their own, else shared."""
    own = _own_broker(db, user)
    if own:
        return own, 'own'
    return _household_broker(db, user.household_id), 'shared'


def _usable_feed(cc: ControlCenter | None) -> tuple[ControlCenter | None, dict | None]:
    """(cc, live_state) if this already-running scanner's feed is actually usable, else (None, None).

    Applies the SAME gate as the radar display: skip a scanner that is offline, halted, or whose
    websocket has gone stale (health file says ok but no fresh ticks). Read-only."""
    if cc is None:
        return None, None
    st = cc.live_state()
    if st.get('offline') or st.get('halted') or _feed_stalled(st):
        return None, None
    return cc, st


def effective_feed(db: Session, user: User) -> tuple[ControlCenter | None, dict | None]:
    """The scanner + live state backing this user's radar/alerts: simulation, their OWN broker if its
    feed is actually live, else the household's shared broker if its feed is live. Health-aware
    (mirrors radar_state, incl. the stalled-websocket gate) and read-only — never starts a scanner or
    spends quota. Returns (None, None) when nothing usable is running."""
    if user.sim_enabled:
        with _lock:
            cc = _sim_ccs.get(user.id)
        return (cc, cc.live_state()) if cc is not None else (None, None)
    own = _own_broker(db, user)
    if own is not None and not (_auth_failed_health(own) or _rate_limited_health(own)):
        cc, st = _usable_feed(_scanners.get(f'u{own.user_id}'))
        if cc is not None:
            return cc, st
    shared = _household_broker(db, user.household_id, exclude_user_id=user.id)
    if shared is not None and not (_auth_failed_health(shared) or _rate_limited_health(shared)):
        cc, st = _usable_feed(_scanners.get(f'u{shared.user_id}'))
        if cc is not None:
            return cc, st
    if os.environ.get('RADAR_DEMO') == '1' and _demo is not None:
        return _demo, _demo.live_state()
    return None, None


def effective_cc(db: Session, user: User) -> ControlCenter | None:
    """The scanner backing this user's current radar — simulation, their own broker (if its feed is
    live), else the household's shared one. Health-aware via effective_feed: a dead-websocket own
    scanner is skipped so drill-downs/alerts read the household's healthy feed. Read-only."""
    return effective_feed(db, user)[0]


def smc_state(db: Session, user: User) -> dict:
    """SMC opportunities for this user. On the `web` pod proxies to the `scanner` pod; otherwise runs
    locally. Returns a dict with 'opportunities' (empty when offline), and 'offline': True when there's
    no live scanner, so callers can distinguish 'not running' from 'running but nothing qualifies'."""
    if SCANNER_HOST:
        return _proxy_internal('smc-state', user.id)
    return _smc_state_local(db, user)


def _smc_state_local(db: Session, user: User) -> dict:
    """The local SMC state: read-only, never starts a scanner (mirrors the /api/smc-radar proxy)."""
    import json
    import urllib.request
    import urllib.error
    cc = effective_cc(db, user)
    if cc is None:
        return {'offline': True, 'opportunities': []}
    try:
        with urllib.request.urlopen(
                f'http://127.0.0.1:{cc.scanner_port}/api/smc-state', timeout=3) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except (urllib.error.URLError, OSError, ValueError):
        return {'offline': True, 'opportunities': []}


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


def _start_failed_health(conn: BrokerConnection) -> dict | None:
    """The scanner's last health IF it crashed on start for a GENERIC reason (not auth/rate-limit)
    recently and the user hasn't re-logged-in since. Used to STOP auto-restarting a scanner that keeps
    failing — each restart re-fetches ~100 FYERS baselines, so an unguarded crash-loop can exhaust the
    daily quota. The auth and rate-limit cases keep their own dedicated guards."""
    h = health.read_health(f'u{conn.user_id}')
    if health.generic_failure_active(h, conn.token_refreshed_at, datetime.now(timezone.utc)):
        return h
    return None


def start_for_broker(db: Session, conn: BrokerConnection) -> bool:
    """Scheduler/supervisor entry point: start the owner's scanner if today's token is present and it
    hasn't already runtime-failed auth (don't restart into the same -15/-16 until they re-login)."""
    if not _token_is_fresh_today(conn) or not conn.token_enc:
        return False
    # Don't restart into a known auth failure, a hit rate limit, or a recent generic start crash —
    # restarting only burns more of the broker's daily API quota and re-triggers the same error.
    if _auth_failed_health(conn) or _rate_limited_health(conn) or _start_failed_health(conn):
        return False
    _rmode, _rlen = _rvol_env(conn.user)
    _cc_for(conn.user_id, conn.app_id, decrypt(conn.token_enc), _universe_index(conn.user),
            watchpins.pins_env(db, conn.user_id), _one_minute(conn.user), _rmode, _rlen)
    return True


# Back-compat alias for the scheduler.
start_for_household = start_for_broker


def stop_all_scanner_processes(proc_root: str = '/proc') -> int:
    """EOD / new-day cleanup: SIGTERM+SIGKILL every live `launch.py run` scanner process in this
    container so none lingers overnight holding a per-owner FYERS lock (a stale scanner blocks the next
    day's feed until it is manually killed). cc-independent — works even if the in-memory _scanners map
    was lost to a container restart. Linux /proc only (returns 0 elsewhere). Returns how many it hit."""
    import signal as _sig
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return 0
    pids = []
    for name in entries:
        if not name.isdigit():
            continue
        try:
            parts = open(f'{proc_root}/{name}/cmdline', 'rb').read().split(b'\x00')
        except OSError:
            continue
        if b'launch.py' in b' '.join(parts) and b'run' in parts:   # a live 'run' scanner (not sim/demo)
            pids.append(int(name))
    for sig in (_sig.SIGTERM, _sig.SIGKILL):
        for pid in pids:
            try:
                os.killpg(os.getpgid(pid), sig)
            except (OSError, ProcessLookupError):
                try:
                    os.kill(pid, sig)
                except OSError:
                    pass
    return len(pids)


def _need_login_state(conn, source, label, reason=None) -> dict:
    if not reason:
        reason = (('Your broker session has expired. SEBI requires a fresh login each trading day — '
                   'log in to resume your scan.') if source == 'own' else
                  'The shared feed will resume once your team admin logs in to the broker today.')
    return {'offline': True, 'need_login': True, 'data_mode': 'none', 'source': source,
            'shared': source == 'shared', 'universe': label, 'broker': conn.broker, 'reason': reason}


def _feed_stalled(st: dict) -> bool:
    """A running, non-closed scanner whose LIVE feed has gone dark — ~all symbols have no fresh tick.

    This is the failure mode the health file misses: the websocket dropped and is stuck reconnecting,
    so `scanner_health` still says ok=true / need_login=false / rate_limited=false, yet no bars
    complete and nothing confirms (the Friday MARUTI case). Detected by data staleness rather than the
    `feed_health` string, which the history/reconcile paths overwrite and so can't be trusted alone.
    Each snapshot row carries `stale` (last tick older than market_feed_stale_seconds)."""
    if st.get('session_closed'):
        return False
    rows = st.get('all') or []
    if not rows:
        return False
    return sum(1 for r in rows if r.get('stale')) / len(rows) >= 0.9


def _enrich_with_position_context(db: Session, user: User, state: dict) -> dict:
    """Enrich radar state with position-aware context for smart signal aging display.

    For RETEST_READY signals with 'aged' entry_status (>5 minutes old), check if the user
    has an open position. If so, update the entry_status to show position details instead
    of "entry window closed".

    This provides context-aware messaging:
    - Fresh (0-2 min): No message needed
    - Aging (2-5 min): Show signal age countdown
    - Aged + No position (>5 min): "Entry window closed"
    - Aged + Has position (>5 min): "In position - entered at ₹X (HH:MM)"
    """
    rows = state.get('all') or []
    if not rows:
        return state

    # Query user's open positions (auto and manual) for today
    today = now_ist().date().isoformat()
    open_positions = {}

    try:
        positions = db.query(Order).filter(
            Order.user_id == user.id,
            Order.status == 'open'
        ).all()

        for pos in positions:
            sym_bare = watchpins.bare(pos.symbol)
            open_positions[sym_bare] = {
                'entry': pos.entry,
                'side': pos.side,
                'created_at': pos.created_at,
                'source': pos.source,  # 'auto' or 'manual'
            }
    except Exception as e:
        # If position query fails, don't crash - just skip enrichment
        import logging
        logging.warning(f"Failed to query positions for entry_status enrichment: {e}")
        return state

    # Enrich each row with position-aware entry_status
    for row in rows:
        if row.get('entry_status') != 'aged':
            continue

        sym_bare = watchpins.bare(row.get('symbol') or '')
        if not sym_bare:
            continue

        # Check if user has open position on this symbol
        pos = open_positions.get(sym_bare)
        if pos:
            # User has position - show "in position" instead of "entry window closed"
            row['entry_status'] = 'in_position'
            row['position_entry'] = pos['entry']
            row['position_side'] = pos['side']
            row['position_time'] = pos['created_at'].astimezone(IST).strftime('%H:%M') if pos['created_at'] else None
            row['position_source'] = pos['source']

    return state


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
    sf = _start_failed_health(conn)
    if sf:
        # The scanner recently crashed on start for a generic reason — don't respawn it here (each
        # restart re-fetches ~100 FYERS baselines). Report 'down' so the caller falls through to the
        # household's shared feed; the cooldown in _cc_for allows one retry per window after this.
        return 'down', {'offline': True, 'data_mode': 'none', 'source': source,
                        'shared': source == 'shared', 'universe': label, 'broker': conn.broker,
                        'reason': sf.get('reason') or 'Live feed temporarily unavailable.'}

    _rmode, _rlen = _rvol_env(conn.user)
    cc = _cc_for(conn.user_id, conn.app_id, decrypt(conn.token_enc), idx,
                 watchpins.pins_env(db, conn.user_id), _one_minute(conn.user), _rmode, _rlen)
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

    # Running + token-valid + not halted, but the websocket may have gone dark (stuck reconnecting)
    # while the health file still reads ok=true. If the data is stale across the board, treat the
    # feed as down so the caller falls back to the household's healthy feed (display AND alerts).
    if _feed_stalled(st):
        return 'down', {'offline': True, 'data_mode': 'none', 'source': source,
                        'shared': source == 'shared', 'universe': label, 'broker': conn.broker,
                        'stalled': True,
                        'reason': 'Live market feed stalled (websocket not delivering fresh ticks).'}

    st.update({'data_mode': 'live', 'source': source, 'shared': source == 'shared',
               'universe': label, 'broker': conn.broker})

    # Enrich with position-aware context for smart signal aging
    st = _enrich_with_position_context(db, user, st)

    return 'live', st


def radar_state(db: Session, user: User) -> dict:
    """The user's radar feed. On the `web` pod proxies to the `scanner` pod; otherwise runs locally."""
    if SCANNER_HOST:
        return _proxy_internal('radar-state', user.id)
    return _radar_state_local(db, user)


def _radar_state_local(db: Session, user: User) -> dict:
    """The local radar feed. Simulation (if on) takes over; else prefer their OWN broker, falling back
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
        # Enrich with position-aware context for smart signal aging
        st = _enrich_with_position_context(db, user, st)
        return st
    # Non-trading day (NSE holiday / weekend, unless a special Muhurat session): show a clean
    # "market closed" state and do NOT start a scanner — the broker has no data, so running one just
    # wastes FYERS requests and shows a broken feed.
    from radar.utils import holiday as _holiday, is_market_day
    if not is_market_day():
        h = _holiday()
        return {'offline': True, 'market_closed': True, 'data_mode': 'none',
                'universe': U.label_for(_universe_index(user)), 'holiday': h or '',
                'reason': (f'Market closed today — {h}. Live scanning resumes next trading day.' if h
                           else 'Market closed for the weekend. Live scanning resumes next trading day.')}
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
