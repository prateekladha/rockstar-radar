"""Rockstar Radar platform API (v1) — Google auth, per-user DB, serves the React SPA."""
from __future__ import annotations

# CRITICAL: Import SSL fix FIRST for local development
try:
    import ssl_fix  # noqa: F401
except ImportError:
    pass  # SSL fix not needed in production

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from radar.control import ControlCenter, ControlError, EDITABLE_CONFIG, validate_config_patch
from radar.selecting import SelectionError, normalize_morning_symbol
from radar.utils import load_config

from .auth import (DEV_LOGIN, current_user, google_enabled, oauth, register_google,
                   require_user, upsert_user)
from .db import get_db, init_db
from .models import Settings, User, Watchlist

ROOT = Path(__file__).resolve().parent.parent
WEB_DIST = ROOT / 'web' / 'dist'
SESSION_SECRET = os.environ.get('SESSION_SECRET', 'dev-insecure-change-me')

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Radar data is served per-household by server.scanners (real broker when connected,
    # else a lazily-started demo). The market-open scheduler refreshes tokens + starts scanners
    # each trading morning so the radar runs hands-off.
    import asyncio
    init_db()
    register_google()
    sched_task = engine_task = None
    if os.environ.get('RADAR_SCHED', '1') != '0':
        from .scheduler import run_scheduler
        sched_task = asyncio.create_task(run_scheduler())
    if os.environ.get('RADAR_ORDER_ENGINE', '1') != '0':
        from .order_engine import run_order_engine
        engine_task = asyncio.create_task(run_order_engine())
    try:
        yield
    finally:
        for t in (sched_task, engine_task):
            if t:
                t.cancel()


app = FastAPI(title='Rockstar Radar', lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site='lax', https_only=False)

from .routers import (alerts, brokers, charts, family, insights,  # noqa: E402
                      support, symbols, trading, watchlist)
app.include_router(brokers.router)
app.include_router(alerts.router)
app.include_router(insights.router)
app.include_router(family.router)
app.include_router(trading.router)
app.include_router(watchlist.router)
app.include_router(charts.router)
app.include_router(symbols.router)
app.include_router(support.router)


# ----------------------------------------------------------------- auth
@app.get('/auth/config')
def auth_config():
    return {'google': google_enabled(), 'dev': DEV_LOGIN}


@app.get('/auth/google/login')
async def auth_google_login(request: Request):
    if not google_enabled():
        return JSONResponse({'error': 'Google sign-in is not configured.'}, status_code=400)
    # Prefer PUBLIC_BASE_URL so the redirect_uri EXACTLY matches what's registered in Google
    # (avoids redirect_uri_mismatch behind a reverse proxy). Falls back to the request URL locally.
    base = os.environ.get('PUBLIC_BASE_URL', '').strip().rstrip('/')
    redirect_uri = (base + '/auth/google/callback') if base else str(request.url_for('auth_google_callback'))
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get('/auth/google/callback', name='auth_google_callback')
async def auth_google_callback(request: Request, db: Session = Depends(get_db)):
    try:
        token = await oauth.google.authorize_access_token(request)
        info = token.get('userinfo') or {}
        user = upsert_user(db, info)
        request.session['user_id'] = user.id
    except Exception as e:
        return HTMLResponse(f'<p>Login failed: {e}</p><a href="/">Back</a>', status_code=400)
    return RedirectResponse('/', status_code=303)


@app.post('/auth/dev-login')
def auth_dev_login(request: Request, db: Session = Depends(get_db)):
    if not DEV_LOGIN:
        return JSONResponse({'error': 'dev login disabled'}, status_code=403)
    user = upsert_user(db, {'sub': 'dev-user', 'email': 'dev@local.test',
                            'name': 'Dev User', 'picture': ''})
    request.session['user_id'] = user.id
    return {'ok': True, 'user': user.public()}


@app.post('/auth/logout')
def auth_logout(request: Request):
    request.session.clear()
    return {'ok': True}


# ----------------------------------------------------------------- per-user API
def _me_payload(user: User) -> dict:
    sdata = (user.settings.data if user.settings else {}) or {}
    return {**user.public(), 'telegram_chat_id': user.telegram_chat_id or '',
            'sim_enabled': bool(user.sim_enabled), 'sim_start': user.sim_start or '09:15',
            'sim_end': user.sim_end or '15:30', 'sim_speed': int(sdata.get('sim_speed', 10) or 30)}


@app.get('/api/me')
def api_me(user: User = Depends(require_user)):
    return _me_payload(user)


_HHMM = __import__('re').compile(r'^([01]\d|2[0-3]):[0-5]\d$')


@app.patch('/api/me')
async def api_patch_me(request: Request, user: User = Depends(require_user),
                       db: Session = Depends(get_db)):
    b = await request.json()
    if 'telegram_chat_id' in b:
        user.telegram_chat_id = ((b.get('telegram_chat_id') or '').strip()[:64]) or None
    if 'sim_start' in b and _HHMM.match(str(b.get('sim_start') or '')):
        user.sim_start = b['sim_start']
    if 'sim_end' in b and _HHMM.match(str(b.get('sim_end') or '')):
        user.sim_end = b['sim_end']
    if 'sim_speed' in b:
        try:
            sp = max(1, min(120, int(float(b.get('sim_speed')))))
            st = user.settings or Settings(user_id=user.id, data={})
            st.data = {**(st.data or {}), 'sim_speed': sp}
            db.add(st)
        except (TypeError, ValueError):
            pass
    sim_touched = any(k in b for k in ('sim_enabled', 'sim_start', 'sim_end', 'sim_speed'))
    if 'sim_enabled' in b:
        user.sim_enabled = 1 if b.get('sim_enabled') else 0
    db.commit()
    if sim_touched:   # restart the sim session fresh with the new settings on next radar load
        from . import scanners
        scanners.stop_sim(user.id)
    return _me_payload(user)


@app.post('/api/sim/reset')
def api_sim_reset(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Wipe this user's PRACTICE (simulation) trades + P&L and restart a fresh session. Only touches
    sim orders (sim=1) — real paper/live trades, any date, are never affected."""
    from .models import Order
    n = db.query(Order).filter_by(user_id=user.id).filter(Order.sim == 1).delete(
        synchronize_session=False)
    db.commit()
    from . import scanners
    scanners.stop_sim(user.id)   # next radar load starts a fresh looping session
    return {'ok': True, 'deleted': n}


@app.post('/api/onboarding')
async def api_onboarding(request: Request, user: User = Depends(require_user),
                         db: Session = Depends(get_db)):
    b = await request.json()
    fn = (b.get('first_name') or '').strip()
    ln = (b.get('last_name') or '').strip()
    if fn:
        user.first_name = fn
    if ln:
        user.last_name = ln
    user.onboarded = 1
    # Rename a default/auto household to the admin's name.
    from .models import Household
    hh = db.get(Household, user.household_id)
    if hh and (not hh.name or "'s Household" in hh.name) and fn:
        hh.name = f"{fn}'s Household"
    db.commit()
    return user.public()


def _parse_symbols(text: str) -> list[str]:
    out = []
    for line in (text or '').splitlines():
        line = line.split('#', 1)[0]
        for tok in line.replace(',', ' ').split():
            if tok.strip():
                out.append(tok.strip())
    return out


@app.get('/api/watchlist')
def api_get_watchlist(user: User = Depends(require_user)):
    text = user.watchlist.symbols_text if user.watchlist else ''
    symbols = _parse_symbols(text)
    resolved = []
    for s in symbols:
        try:
            resolved.append(normalize_morning_symbol(s))
        except SelectionError:
            pass
    return {'symbols': symbols, 'resolved': resolved}


@app.put('/api/watchlist')
async def api_put_watchlist(request: Request, user: User = Depends(require_user),
                            db: Session = Depends(get_db)):
    body = await request.json()
    clean, seen = [], set()
    try:
        for s in body.get('symbols', []):
            s = (s or '').strip()
            if not s:
                continue
            canonical = normalize_morning_symbol(s)
            if canonical not in seen:
                seen.add(canonical)
                clean.append(s.upper())
    except SelectionError as e:
        return JSONResponse({'error': str(e)}, status_code=400)
    wl = user.watchlist or Watchlist(user_id=user.id)
    wl.symbols_text = '\n'.join(clean)
    db.add(wl)
    db.commit()
    return {'ok': True, 'count': len(clean)}


@app.get('/api/settings')
def api_get_settings(user: User = Depends(require_user)):
    base = {k: load_config().get(k) for k in EDITABLE_CONFIG}
    base.update((user.settings.data if user.settings else {}) or {})
    return base


@app.patch('/api/settings')
async def api_patch_settings(request: Request, user: User = Depends(require_user),
                             db: Session = Depends(get_db)):
    try:
        cleaned = validate_config_patch(await request.json())
    except ControlError as e:
        return JSONResponse({'error': str(e)}, status_code=400)
    st = user.settings or Settings(user_id=user.id, data={})
    data = dict(st.data or {})
    data.update(cleaned)
    st.data = data
    db.add(st)
    db.commit()
    return api_get_settings(user)


@app.get('/api/prerequisites')
def api_get_prerequisites(user: User = Depends(require_user)):
    """Get user's prerequisite configuration for strategy evaluation."""
    import json
    if not user.settings:
        # Return defaults
        return {
            'min_rvol': 1.0,
            'rvol_enabled': True,
            'min_liquidity_cr': None,
            'min_price': None,
            'max_price': None,
            'allowed_sectors': None,
            'blocked_symbols': None
        }

    return {
        'min_rvol': user.settings.prereq_min_rvol or 1.0,
        'rvol_enabled': bool(user.settings.prereq_rvol_enabled),
        'min_liquidity_cr': user.settings.prereq_min_liquidity_cr,
        'min_price': user.settings.prereq_min_price,
        'max_price': user.settings.prereq_max_price,
        'allowed_sectors': json.loads(user.settings.prereq_allowed_sectors) if user.settings.prereq_allowed_sectors else None,
        'blocked_symbols': json.loads(user.settings.prereq_blocked_symbols) if user.settings.prereq_blocked_symbols else None
    }


@app.put('/api/prerequisites')
async def api_update_prerequisites(request: Request, user: User = Depends(require_user),
                                   db: Session = Depends(get_db)):
    """Update user's prerequisite configuration."""
    import json
    data = await request.json()

    # Validation
    if 'min_rvol' in data:
        try:
            min_rvol = float(data['min_rvol'])
            if min_rvol < 0:
                return JSONResponse({'error': 'min_rvol must be >= 0'}, status_code=400)
        except (TypeError, ValueError):
            return JSONResponse({'error': 'min_rvol must be a number'}, status_code=400)

    if 'min_liquidity_cr' in data and data['min_liquidity_cr'] is not None:
        try:
            float(data['min_liquidity_cr'])
        except (TypeError, ValueError):
            return JSONResponse({'error': 'min_liquidity_cr must be a number'}, status_code=400)

    if 'min_price' in data and data['min_price'] is not None:
        try:
            float(data['min_price'])
        except (TypeError, ValueError):
            return JSONResponse({'error': 'min_price must be a number'}, status_code=400)

    if 'max_price' in data and data['max_price'] is not None:
        try:
            float(data['max_price'])
        except (TypeError, ValueError):
            return JSONResponse({'error': 'max_price must be a number'}, status_code=400)

    # Get or create settings
    st = user.settings or Settings(user_id=user.id, data={})

    # Update fields
    if 'min_rvol' in data:
        st.prereq_min_rvol = float(data['min_rvol'])
    if 'rvol_enabled' in data:
        st.prereq_rvol_enabled = 1 if data['rvol_enabled'] else 0
    if 'min_liquidity_cr' in data:
        st.prereq_min_liquidity_cr = float(data['min_liquidity_cr']) if data['min_liquidity_cr'] is not None else None
    if 'min_price' in data:
        st.prereq_min_price = float(data['min_price']) if data['min_price'] is not None else None
    if 'max_price' in data:
        st.prereq_max_price = float(data['max_price']) if data['max_price'] is not None else None
    if 'allowed_sectors' in data:
        st.prereq_allowed_sectors = json.dumps(data['allowed_sectors']) if data['allowed_sectors'] else None
    if 'blocked_symbols' in data:
        st.prereq_blocked_symbols = json.dumps(data['blocked_symbols']) if data['blocked_symbols'] else None

    db.add(st)
    db.commit()

    return api_get_prerequisites(user)


EMA_SOURCES = ['close', 'open', 'high', 'low', 'hl2', 'hlc3', 'ohlc4']


def _ema_settings_payload(s) -> dict:
    return {
        'fast_length': (getattr(s, 'ema_fast_length', None) if s else None) or 5,
        'slow_length': (getattr(s, 'ema_slow_length', None) if s else None) or 20,
        'source': (getattr(s, 'ema_source', None) if s else None) or 'close',
        'offset': int((getattr(s, 'ema_offset', None) if s else 0) or 0),
    }


@app.get('/api/ema-settings')
def api_get_ema_settings(user: User = Depends(require_user)):
    """Get the user's EMA crossover strategy settings (fast/slow length, source, offset)."""
    return _ema_settings_payload(user.settings)


@app.put('/api/ema-settings')
async def api_update_ema_settings(request: Request, user: User = Depends(require_user),
                                  db: Session = Depends(get_db)):
    """Update the user's EMA crossover settings. Lengths 1-200, offset 0-100, source whitelisted."""
    data = await request.json()
    if 'source' in data and data['source'] not in EMA_SOURCES:
        return JSONResponse({'error': f'source must be one of: {", ".join(EMA_SOURCES)}'}, status_code=400)
    for key in ('fast_length', 'slow_length'):
        if key in data:
            try:
                v = int(data[key])
            except (TypeError, ValueError):
                return JSONResponse({'error': f'{key} must be a number'}, status_code=400)
            if v < 1 or v > 200:
                return JSONResponse({'error': f'{key} must be between 1 and 200'}, status_code=400)
    if 'offset' in data:
        try:
            off = int(data['offset'])
        except (TypeError, ValueError):
            return JSONResponse({'error': 'offset must be a number'}, status_code=400)
        if off < 0 or off > 100:
            return JSONResponse({'error': 'offset must be between 0 and 100'}, status_code=400)

    st = user.settings or Settings(user_id=user.id, data={})
    if 'fast_length' in data:
        st.ema_fast_length = int(data['fast_length'])
    if 'slow_length' in data:
        st.ema_slow_length = int(data['slow_length'])
    if 'source' in data:
        st.ema_source = data['source']
    if 'offset' in data:
        st.ema_offset = int(data['offset'])
    db.add(st)
    db.commit()
    return _ema_settings_payload(st)


@app.get('/api/rvol-settings')
def api_get_rvol_settings(user: User = Depends(require_user)):
    """Get user's RVOL calculation settings."""
    if not user.settings:
        # Return defaults
        return {
            'anchor_timeframe': 'day',
            'length': 10,
            'calculation_mode': 'cumulative'
        }

    return {
        'anchor_timeframe': user.settings.rvol_anchor_timeframe or 'day',
        'length': user.settings.rvol_length or 10,
        'calculation_mode': user.settings.rvol_calculation_mode or 'cumulative'
    }


@app.put('/api/rvol-settings')
async def api_update_rvol_settings(request: Request, user: User = Depends(require_user),
                                   db: Session = Depends(get_db)):
    """Update user's RVOL calculation settings."""
    data = await request.json()

    # Validation — only the anchors/modes actually implemented in radar.rvol are accepted, so the
    # settings can never save a value that silently no-ops. (session/week/month and mean/median are
    # not wired yet; add them here as they land.)
    valid_timeframes = ['day']
    valid_modes = ['cumulative', 'per_bar']

    if 'anchor_timeframe' in data and data['anchor_timeframe'] not in valid_timeframes:
        return JSONResponse({
            'error': f'anchor_timeframe must be one of: {", ".join(valid_timeframes)}'
        }, status_code=400)

    if 'calculation_mode' in data and data['calculation_mode'] not in valid_modes:
        return JSONResponse({
            'error': f'calculation_mode must be one of: {", ".join(valid_modes)}'
        }, status_code=400)

    if 'length' in data:
        try:
            length = int(data['length'])
            if length < 1 or length > 100:
                return JSONResponse({'error': 'length must be between 1 and 100'}, status_code=400)
        except (TypeError, ValueError):
            return JSONResponse({'error': 'length must be a number'}, status_code=400)

    # Get or create settings
    st = user.settings or Settings(user_id=user.id, data={})

    # Update fields
    if 'anchor_timeframe' in data:
        st.rvol_anchor_timeframe = data['anchor_timeframe']
    if 'length' in data:
        st.rvol_length = int(data['length'])
    if 'calculation_mode' in data:
        st.rvol_calculation_mode = data['calculation_mode']

    db.add(st)
    db.commit()

    return api_get_rvol_settings(user)


def _apply_prerequisite_filters(opportunities: list, user: User, strategy: str = 'ORB') -> tuple[list, int]:
    """Apply user's prerequisite filters to opportunities.

    Args:
        opportunities: List of opportunity dicts
        user: User with settings
        strategy: 'ORB' or 'SMC' (determines where to find RVOL)

    Returns:
        (filtered_opportunities, rejected_count)
    """
    if not opportunities:
        return opportunities, 0

    # Load user's prerequisite configuration
    if not user.settings:
        return opportunities, 0  # No settings = no filtering

    from radar.prerequisites import PrerequisiteConfig, PrerequisiteChecker
    import json as json_lib

    prereq_config = PrerequisiteConfig(
        min_rvol=user.settings.prereq_min_rvol or 1.0,
        rvol_enabled=bool(user.settings.prereq_rvol_enabled),
        min_liquidity_cr=user.settings.prereq_min_liquidity_cr,
        min_price=user.settings.prereq_min_price,
        max_price=user.settings.prereq_max_price,
        allowed_sectors=json_lib.loads(user.settings.prereq_allowed_sectors) if user.settings.prereq_allowed_sectors else None,
        blocked_symbols=json_lib.loads(user.settings.prereq_blocked_symbols) if user.settings.prereq_blocked_symbols else None
    )

    # If RVOL check is disabled, skip filtering
    if not prereq_config.rvol_enabled:
        return opportunities, 0

    checker = PrerequisiteChecker(prereq_config)
    filtered = []
    rejected = 0

    for opp in opportunities:
        # Extract data from opportunity
        symbol = opp.get('symbol', '')
        price = opp.get('price')

        # Extract RVOL based on strategy
        if strategy == 'ORB':
            # ORB: RVOL is directly in opportunity
            rvol = opp.get('rvol')
        elif strategy == 'SMC':
            # SMC: RVOL is in confluence.rvol_cum
            confluence = opp.get('confluence') or {}
            rvol = confluence.get('rvol_cum')
        else:
            rvol = None

        # For ORB, liquidity might be available from instrument info
        # For SMC, we might not have liquidity data readily available
        liquidity_cr = None

        # Run prerequisite check
        result = checker.check(symbol, {
            'rvol': rvol,
            'price': price,
            'liquidity_cr': liquidity_cr
        })

        # An "unavailable" (None) input means we could not MEASURE that factor — e.g. the SMC
        # confluence buffer is too short for a cumulative RVOL, or liquidity isn't computed here — NOT
        # that the factor is bad. Rejecting on that would empty the whole radar, so keep the
        # opportunity when EVERY failed check is merely unmeasurable; reject only on a real threshold
        # breach (a value that was actually computed and fell outside the limit).
        unmeasurable = set()
        if rvol is None:
            unmeasurable.add('RVOL')
        if liquidity_cr is None:
            unmeasurable.add('Liquidity')
        only_unmeasurable = bool(result.failed_checks) and set(result.failed_checks) <= unmeasurable
        if result.passed or only_unmeasurable:
            filtered.append(opp)
        else:
            rejected += 1
            # Log rejection for debugging
            print(f'[Prereq] {strategy} - Rejected {symbol}: {result.error_message} (RVOL={rvol})')

    return filtered, rejected


@app.get('/api/radar')
def api_radar(user: User = Depends(require_user), db: Session = Depends(get_db)):
    from . import journaling, scanners
    state = scanners.radar_state(db, user)

    # Apply prerequisite filters to ORB opportunities
    # ORB uses 'all' field, not 'opportunities'
    if state.get('all'):
        filtered_opps, rejected_count = _apply_prerequisite_filters(
            state['all'], user, strategy='ORB'
        )
        state['all'] = filtered_opps

        # Also filter 'top5' if present
        if state.get('top5'):
            # top5 is a subset of 'all', so filter it separately
            filtered_top5, _ = _apply_prerequisite_filters(
                state['top5'], user, strategy='ORB'
            )
            state['top5'] = filtered_top5

        # Add metadata about filtering
        if rejected_count > 0:
            state['prereq_filtered'] = rejected_count
            print(f'[Prereq] ORB - Filtered {rejected_count} opportunities for user {user.email}')

    if state.get('data_mode') == 'live':
        try:
            journaling.record_opportunities(db, user.id, state)
        except Exception as e:  # journaling must never break the radar
            print(f'opportunity journaling skipped: {e}')
    return state


def _smc_market_closed():
    """A clean 'market closed' payload when the market is off (weekend/holiday or outside 09:15-15:30),
    mirroring radar_state so the SMC screen shows the same message as the ORB radar instead of a
    misleading 'scanner starting / not running'. Returns None while the market is open."""
    from radar.utils import holiday as _holiday, is_market_day, now_ist
    if not is_market_day():
        h = _holiday()
        return {'offline': True, 'market_closed': True, 'holiday': h or '', 'opportunities': [],
                'reason': (f'Market closed today — {h}. Live scanning resumes next trading day.' if h
                           else 'Market closed for the weekend. Live scanning resumes next trading day.')}
    if not ('09:15' <= now_ist().strftime('%H:%M') <= '15:30'):
        return {'offline': True, 'market_closed': True, 'holiday': '', 'opportunities': [],
                'reason': 'Market is closed right now. Live scanning runs 09:15–15:30 on trading days.'}
    return None


@app.get('/api/smc-radar')
def api_smc_radar(user: User = Depends(require_user), db: Session = Depends(get_db)):
    from . import scanners
    closed = _smc_market_closed()
    # Mode-aware: local scanner subprocess (single container / scanner pod) OR a proxy to the scanner
    # pod (web pod). Returns 'offline': True when no live scanner, else the SMC state + opportunities.
    state = scanners.smc_state(db, user)
    if not state or state.get('offline'):
        return closed or {'offline': True, 'reason': 'Scanner not running', 'opportunities': []}

    # Apply prerequisite filters to SMC opportunities
    if state.get('opportunities'):
        filtered_opps, rejected_count = _apply_prerequisite_filters(
            state['opportunities'], user, strategy='SMC'
        )
        state['opportunities'] = filtered_opps
        if rejected_count > 0:
            state['prereq_filtered'] = rejected_count
            print(f'[Prereq] SMC - Filtered {rejected_count} opportunities for user {user.email}')
    return state


def _internal_authorized(request: Request) -> bool:
    """Cluster-internal endpoints are reachable only inside the K8s network and gated by a shared
    token (INTERNAL_TOKEN). When no token is configured (single container / dev) they're open —
    they're not exposed via the public ingress anyway."""
    from . import scanners
    tok = scanners.INTERNAL_TOKEN
    return (not tok) or request.headers.get('X-Internal-Token') == tok


@app.get('/internal/radar-state')
def internal_radar_state(user_id: int, request: Request, db: Session = Depends(get_db)):
    """The scanner pod serves the local radar state for the web pod (OKE migration P2). Not public."""
    from . import scanners
    if not _internal_authorized(request):
        return JSONResponse({'error': 'forbidden'}, status_code=403)
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        return {'offline': True, 'data_mode': 'none', 'reason': 'unknown user'}
    return scanners._radar_state_local(db, u)


@app.get('/internal/smc-state')
def internal_smc_state(user_id: int, request: Request, db: Session = Depends(get_db)):
    """The scanner pod serves the local SMC state for the web pod. Not public."""
    from . import scanners
    if not _internal_authorized(request):
        return JSONResponse({'error': 'forbidden'}, status_code=403)
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        return {'offline': True, 'opportunities': []}
    return scanners._smc_state_local(db, u)


@app.get('/healthz')
def healthz():
    """Liveness: the process is up. Used by the K8s liveness/startup probes."""
    return {'ok': True}


@app.get('/readyz')
def readyz():
    """Readiness: the web pod is ready only once it can reach the scanner pod; the scanner pod (or a
    single container) is ready when its process is up."""
    from . import scanners
    if scanners.SCANNER_HOST:
        import urllib.request
        try:
            with urllib.request.urlopen(
                    f'http://{scanners.SCANNER_HOST}:{scanners.SCANNER_INTERNAL_PORT}/healthz',
                    timeout=3) as r:
                if r.status == 200:
                    return {'ready': True}
        except Exception:
            pass
        return JSONResponse({'ready': False, 'reason': 'scanner unreachable'}, status_code=503)
    return {'ready': True}


@app.post('/api/debug-stock')
async def api_debug_stock(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Debug endpoint: analyze a single stock with SMC engine."""
    from radar.fyers import FyersAdapter
    from radar.debug_analysis import analyze_single_stock
    from radar.utils import load_config
    from . import scanners

    body = await request.json()
    symbol_input = (body.get('symbol') or '').strip()

    if not symbol_input:
        return JSONResponse({'success': False, 'error': 'Symbol required'}, status_code=400)

    # Use user's broker connection if available, otherwise simulation won't work
    conn, _ = scanners.effective_broker(db, user)
    if not conn or not conn.token_enc:
        return JSONResponse({
            'success': False,
            'error': 'Broker not connected',
            'message': 'Connect your broker to use debug analysis'
        }, status_code=400)

    from .crypto import decrypt
    import os
    import traceback

    try:
        # Temporarily set env vars for adapter creation (FyersAdapter reads from env in __init__)
        old_app_id = os.environ.get('FYERS_APP_ID')
        old_token = os.environ.get('FYERS_ACCESS_TOKEN')

        try:
            os.environ['FYERS_APP_ID'] = conn.app_id
            os.environ['FYERS_ACCESS_TOKEN'] = decrypt(conn.token_enc) or ''

            # Create adapter with user's credentials (reads from env vars we just set)
            adapter = FyersAdapter(load_config())

            # Load user's prerequisite configuration
            from radar.prerequisites import PrerequisiteConfig
            import json as json_lib

            prereq_config = None
            if user.settings:
                prereq_config = PrerequisiteConfig(
                    min_rvol=user.settings.prereq_min_rvol or 1.0,
                    rvol_enabled=bool(user.settings.prereq_rvol_enabled),
                    min_liquidity_cr=user.settings.prereq_min_liquidity_cr,
                    min_price=user.settings.prereq_min_price,
                    max_price=user.settings.prereq_max_price,
                    allowed_sectors=json_lib.loads(user.settings.prereq_allowed_sectors) if user.settings.prereq_allowed_sectors else None,
                    blocked_symbols=json_lib.loads(user.settings.prereq_blocked_symbols) if user.settings.prereq_blocked_symbols else None
                )

            # The user's RVOL calculation choice (mode/length) so the Debug tab matches the radar.
            from radar.rvol import RvolConfig
            rvol_cfg = RvolConfig(
                mode=(user.settings.rvol_calculation_mode if user.settings else None) or 'cumulative',
                length=(user.settings.rvol_length if user.settings else None) or 10,
            )

            # The user's EMA crossover settings (fast/slow length, source, offset).
            ema_cfg = _ema_settings_payload(user.settings)

            # Run analysis
            force = body.get('force', False)
            result = analyze_single_stock(adapter, symbol_input, load_config(), force=force,
                                          prereq_config=prereq_config, rvol_cfg=rvol_cfg,
                                          ema_cfg=ema_cfg)

            return result
        finally:
            # Restore original env vars
            if old_app_id is None:
                os.environ.pop('FYERS_APP_ID', None)
            else:
                os.environ['FYERS_APP_ID'] = old_app_id

            if old_token is None:
                os.environ.pop('FYERS_ACCESS_TOKEN', None)
            else:
                os.environ['FYERS_ACCESS_TOKEN'] = old_token
    except Exception as e:
        # Log full traceback for debugging
        print(f'[DEBUG API ERROR] {type(e).__name__}: {e}')
        print(traceback.format_exc())
        return JSONResponse({
            'success': False,
            'error': 'Analysis failed',
            'message': f'{type(e).__name__}: {e}',
            'traceback': traceback.format_exc()
        }, status_code=500)


@app.get('/api/universe')
def api_universe(user: User = Depends(require_user)):
    from radar import universe as U
    data = (user.settings.data if user.settings else None) or {}
    current = data.get('universe_index') or U.DEFAULT
    return {'catalog': U.catalog(), 'current': current if U.is_valid(current) else U.DEFAULT}


@app.put('/api/universe')
async def set_universe(request: Request, user: User = Depends(require_user),
                      db: Session = Depends(get_db)):
    from radar import universe as U
    from .models import Settings
    idx = (await request.json()).get('universe_index')
    if not U.is_valid(idx):
        return JSONResponse({'error': 'Unknown index'}, status_code=400)
    st = user.settings or Settings(user_id=user.id, data={})
    data = dict(st.data or {})
    data['universe_index'] = idx
    st.data = data
    db.add(st)
    db.commit()
    return {'ok': True, 'current': idx, 'label': U.label_for(idx)}


# ----------------------------------------------------------------- Blog (static, crawlable)
# Public SEO/GEO pages served as REAL HTML (not the client-rendered SPA shell) at clean, canonical
# URLs. Source lives in web/public/blog/ and is copied to web/dist/blog/ by the vite build. These
# routes are registered BEFORE the SPA catch-all below, so they win; the .html files stay reachable
# too, but each page's <link rel="canonical"> points at the clean URL to avoid duplicate content.
def _blog_file(name: str):
    if not WEB_DIST.exists():
        return None
    blog_dir = (WEB_DIST / 'blog').resolve()
    f = (blog_dir / name).resolve()
    if f.is_file() and str(f).startswith(str(blog_dir) + os.sep):
        return FileResponse(str(f), media_type='text/html; charset=utf-8')
    return None


@app.get('/blog', response_class=HTMLResponse)
@app.get('/blog/', response_class=HTMLResponse)
def blog_index():
    return _blog_file('index.html') or HTMLResponse('<h1>Blog coming soon.</h1>', status_code=404)


@app.get('/blog/how-to-connect-fyers', response_class=HTMLResponse)
def blog_connect_fyers():
    return _blog_file('how-to-connect-fyers.html') or HTMLResponse('<h1>Not found</h1>', status_code=404)


# ----------------------------------------------------------------- SPA
if WEB_DIST.exists():
    app.mount('/assets', StaticFiles(directory=str(WEB_DIST / 'assets')), name='assets')

    @app.get('/{full_path:path}', response_class=HTMLResponse)
    def spa(full_path: str):
        # Serve real files that live at the dist root (favicon.svg, robots.txt, sitemap.xml, …)
        # before falling back to the SPA shell. Guard against path traversal.
        if full_path:
            candidate = (WEB_DIST / full_path).resolve()
            if candidate.is_file() and str(candidate).startswith(str(WEB_DIST.resolve()) + os.sep):
                # version.json must never be cached — the open SPA polls it to detect a new deploy.
                if candidate.name == 'version.json':
                    return FileResponse(str(candidate), headers={
                        'Cache-Control': 'no-store, no-cache, must-revalidate', 'Pragma': 'no-cache'})
                return FileResponse(str(candidate))
        index = WEB_DIST / 'index.html'
        if index.exists():
            # Never cache index.html — it points at hashed asset files; caching it would
            # keep serving an old build's CSS/JS. (Assets themselves are content-hashed = safe to cache.)
            return FileResponse(str(index), headers={
                'Cache-Control': 'no-store, no-cache, must-revalidate', 'Pragma': 'no-cache'})
        return HTMLResponse('<h1>SPA not built — run: cd web && npm install && npm run build</h1>')
else:
    @app.get('/', response_class=HTMLResponse)
    def spa_placeholder():
        return HTMLResponse('<h1>Rockstar Radar API up.</h1>'
                            '<p>Build the SPA: <code>cd web && npm install && npm run build</code></p>')
