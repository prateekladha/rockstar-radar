"""Rockstar Radar platform API (v1) — Google auth, per-user DB, serves the React SPA."""
from __future__ import annotations
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
    sched_task = None
    if os.environ.get('RADAR_SCHED', '1') != '0':
        from .scheduler import run_scheduler
        sched_task = asyncio.create_task(run_scheduler())
    try:
        yield
    finally:
        if sched_task:
            sched_task.cancel()


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
    redirect_uri = str(request.url_for('auth_google_callback'))
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
@app.get('/api/me')
def api_me(user: User = Depends(require_user)):
    return user.public()


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


@app.get('/api/radar')
def api_radar(user: User = Depends(require_user), db: Session = Depends(get_db)):
    from . import journaling, scanners
    state = scanners.radar_state(db, user)
    if state.get('data_mode') == 'live':
        try:
            journaling.record_opportunities(db, user.id, state)
        except Exception as e:  # journaling must never break the radar
            print(f'opportunity journaling skipped: {e}')
    return state


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
