"""Control Center web app (Phase 2 product, FastAPI + Jinja2 SSR).

Pages are server-side rendered (Jinja2): the HTML arrives fully populated with current
connection/scanner/watchlist/settings state. Mutations use POST -> redirect (PRG), also
server-rendered. The only client-side piece is the live-radar fragment, which polls the
JSON /api/state endpoint (a 2s-refreshing feed can't be statically rendered).

A small JSON API is retained for that live fragment and for programmatic/testing use.
Bound to 127.0.0.1 only. Secrets are never sent to the browser (token = boolean).
"""
from __future__ import annotations
import os
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .control import ControlCenter, ControlError
from .fyers import ApiError
from .selecting import SelectionError

DEMO = os.environ.get('RADAR_DEMO') == '1'   # cloud beta: simulated data, no credentials
control = ControlCenter(demo=DEMO)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # In demo/beta, auto-start the simulated scanner so users land on a live radar.
    if DEMO and os.environ.get('RADAR_AUTOSTART', '1') == '1':
        try:
            if not control.scanner_status()['running']:
                control.start_scanner()
        except Exception as e:  # never block startup on this
            print(f'Demo autostart skipped: {e}')
    yield
    if DEMO:
        try:
            control.stop_scanner()
        except Exception:
            pass


app = FastAPI(title='Rockstar Radar Control Center', lifespan=lifespan)
WEBROOT = Path(__file__).resolve().parent.parent / 'webapp'
templates = Jinja2Templates(directory=str(WEBROOT / 'templates'))
app.mount('/static', StaticFiles(directory=str(WEBROOT / 'static')), name='static')


def _fail(e: Exception, code: int = 400):
    return JSONResponse({'error': str(e)}, status_code=code)


def _redirect(request: Request, msg: str = '', err: str = ''):
    q = {}
    if msg:
        q['msg'] = msg
    if err:
        q['err'] = err
    url = '/' + ('?' + urllib.parse.urlencode(q) if q else '')
    return RedirectResponse(url=url, status_code=303)


def _fmt_uptime(seconds):
    if seconds is None:
        return None
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f'{h}h {m}m' if h else f'{m}m {s}s'


# ---------------------------------------------------------------- SSR pages
@app.get('/', response_class=HTMLResponse)
def index(request: Request, msg: str = '', err: str = ''):
    conn = control.connection_status()
    scanner = control.scanner_status()
    watch = control.get_watchlist()
    callback_url = str(request.base_url).rstrip('/') + '/auth/callback'
    try:
        auth_url = control.auth_url()
    except (ApiError, ControlError) as e:
        auth_url = ''
        err = err or f'Login unavailable: {e}'
    return templates.TemplateResponse(request=request, name='control.html', context={
        'conn': conn,
        'scanner': scanner,
        'uptime': _fmt_uptime(scanner.get('uptime_seconds')),
        'watchlist_text': '\n'.join(watch['symbols']),
        'watchlist_count': len(watch['resolved']),
        'cfg': control.editable_config(),
        'auth_url': auth_url,
        'callback_url': callback_url,
        'redirect_ok': conn['redirect_uri'] == callback_url,
        'telegram': control.telegram_status(),
        'demo': DEMO,
        'msg': msg, 'err': err,
    })


@app.post('/ui/watchlist')
def ui_watchlist(request: Request, symbols: str = Form('')):
    toks = [t.strip() for t in symbols.replace(',', '\n').splitlines() if t.strip()]
    try:
        out = control.set_watchlist(toks)
        return _redirect(request, msg=f'Watchlist saved — {len(out["resolved"])} valid symbol(s).')
    except (SelectionError, ControlError) as e:
        return _redirect(request, err=str(e))


@app.post('/ui/config')
async def ui_config(request: Request):
    form = await request.form()
    patch = {k: v for k, v in form.items()}
    try:
        control.update_config(patch)
        return _redirect(request, msg='Settings saved — applied on next scanner start.')
    except (ControlError, ValueError) as e:
        return _redirect(request, err=str(e))


@app.post('/ui/scanner/start')
def ui_scanner_start(request: Request):
    try:
        control.start_scanner()
        return _redirect(request, msg='Scanner starting — building today\'s universe (several minutes).')
    except (ControlError, ApiError, OSError) as e:
        return _redirect(request, err=str(e))


@app.post('/ui/scanner/stop')
def ui_scanner_stop(request: Request):
    control.stop_scanner()
    return _redirect(request, msg='Scanner stopped.')


@app.post('/ui/connection/test')
def ui_connection_test(request: Request):
    r = control.test_connection()
    return _redirect(request, msg='Live data reachable ✓' if r['ok'] else '',
                     err='' if r['ok'] else f'Connection test failed: {r["message"]}')


@app.post('/ui/login/paste')
def ui_login_paste(request: Request, redirect_url: str = Form('')):
    try:
        control.complete_login(redirect_url)
        return _redirect(request, msg='Connected to FYERS ✓')
    except (ApiError, ControlError) as e:
        return _redirect(request, err=str(e))


@app.post('/ui/telegram')
def ui_telegram(request: Request, bot_token: str = Form(''), chat_id: str = Form('')):
    control.set_telegram(bot_token, chat_id)
    return _redirect(request, msg='Telegram settings saved. Restart the scanner to apply to live alerts.')


@app.post('/ui/telegram/test')
def ui_telegram_test(request: Request):
    r = control.test_telegram()
    return _redirect(request, msg='Test alert sent ✓' if r['ok'] else '',
                     err='' if r['ok'] else f'Telegram test failed: {r["message"]}')


@app.post('/api/telegram/test')
def api_telegram_test():
    return control.test_telegram()


@app.get('/auth/callback', response_class=HTMLResponse)
def auth_callback(request: Request):
    """FYERS one-click redirect lands here; exchange the code and confirm."""
    params = request.query_params
    if params.get('error_msg') or params.get('error'):
        return _callback_page(False, f'FYERS login error: {params.get("error_msg") or params.get("error")}')
    try:
        control.complete_login(str(request.url))
        return _callback_page(True, 'Connected to FYERS. Close this tab and return to the Control Center.')
    except (ApiError, ControlError) as e:
        return _callback_page(False, str(e))


# ---------------------------------------------------------------- JSON API
@app.get('/api/status')
def status():
    return {'connection': control.connection_status(), 'scanner': control.scanner_status()}


@app.get('/api/login/url')
def login_url():
    try:
        return {'auth_url': control.auth_url()}
    except (ApiError, ControlError) as e:
        return _fail(e)


class PasteBody(BaseModel):
    redirect_url: str


@app.post('/api/login/paste')
def login_paste(body: PasteBody):
    try:
        return control.complete_login(body.redirect_url)
    except (ApiError, ControlError) as e:
        return _fail(e)


@app.post('/api/connection/test')
def connection_test():
    return control.test_connection()


@app.get('/api/watchlist')
def get_watchlist():
    return control.get_watchlist()


class WatchlistBody(BaseModel):
    symbols: list[str]


@app.put('/api/watchlist')
def put_watchlist(body: WatchlistBody):
    try:
        return control.set_watchlist(body.symbols)
    except (SelectionError, ControlError) as e:
        return _fail(e)


@app.get('/api/config')
def get_config():
    return control.editable_config()


@app.patch('/api/config')
async def patch_config(request: Request):
    try:
        return control.update_config(await request.json())
    except (ControlError, ValueError) as e:
        return _fail(e)


@app.post('/api/scanner/start')
def scanner_start():
    try:
        return control.start_scanner()
    except (ControlError, ApiError, OSError) as e:
        return _fail(e)


@app.post('/api/scanner/stop')
def scanner_stop():
    return control.stop_scanner()


@app.get('/api/state')
def live_state():
    return control.live_state()


def _callback_page(ok: bool, message: str) -> str:
    color = '#48d3a4' if ok else '#ff8797'
    icon = '✓' if ok else '✕'
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>FYERS login</title>
<style>body{{background:#0b1020;color:#f2f6ff;font-family:ui-sans-serif,system-ui,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.box{{text-align:center;max-width:460px;padding:32px;border:1px solid #2a3650;border-radius:16px;background:#131b2e}}
.icon{{font-size:46px;color:{color}}}h1{{font-size:20px;margin:12px 0}}p{{color:#93a0b6;line-height:1.5}}</style>
</head><body><div class="box"><div class="icon">{icon}</div>
<h1>{'Connected' if ok else 'Login failed'}</h1><p>{message}</p></div></body></html>'''
