"""The user's single connected broker — used for market data, quotes, history AND orders.

One active platform per user, editable anytime, with:
  * a Test Connection check that works on the credentials currently in the form (no save needed),
  * a guided OAuth login (Connect) that sends the user to the broker, captures the access token on
    the callback, encrypts + saves it, and returns the user to the Broker page.

The OAuth redirect URL is OUR callback endpoint — the user never types it; we show it so they can
register it in their broker app.
"""
from __future__ import annotations
import os
import secrets
from urllib.parse import parse_qs, urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from datetime import datetime, timezone

from ..auth import current_user, require_user
from ..broker_tokens import exchange_code
from ..crypto import decrypt, encrypt
from ..db import get_db
from ..models import BrokerConnection, User

router = APIRouter(prefix='/api/brokers', tags=['brokers'])

# The platform catalog. "available" = integrated now; "coming_soon" = on the roadmap.
PLATFORMS = [
    {'id': 'fyers', 'label': 'FYERS', 'status': 'available', 'oauth': True,
     'help': 'Create an API app at myapi.fyers.in, paste its App ID and Secret, then register the '
             'redirect URL shown below in that app. Click Connect to log in to FYERS.'},
    {'id': 'zerodha', 'label': 'Zerodha Kite', 'status': 'available', 'oauth': False,
     'help': 'Create a Kite Connect app at developers.kite.trade and register the redirect URL '
             'shown below.'},
    {'id': 'upstox', 'label': 'Upstox', 'status': 'coming_soon'},
    {'id': 'angelone', 'label': 'Angel One', 'status': 'coming_soon'},
    {'id': 'dhan', 'label': 'Dhan', 'status': 'coming_soon'},
    {'id': 'groww', 'label': 'Groww', 'status': 'coming_soon'},
    {'id': 'paytmmoney', 'label': 'Paytm Money', 'status': 'coming_soon'},
    {'id': 'fivepaisa', 'label': '5paisa', 'status': 'coming_soon'},
]
_AVAILABLE = {p['id'] for p in PLATFORMS if p['status'] == 'available'}
_OAUTH = {p['id'] for p in PLATFORMS if p.get('oauth')}


def _base_url(request: Request) -> str:
    """Public origin for building the OAuth redirect. Behind a reverse proxy (Caddy) set
    PUBLIC_BASE_URL so the https scheme/host are correct; otherwise derive from the request."""
    env = os.environ.get('PUBLIC_BASE_URL', '').strip().rstrip('/')
    if env:
        return env
    return str(request.base_url).rstrip('/')


def _callback_uri(request: Request) -> str:
    return _base_url(request) + '/api/brokers/callback'


def _parse_auth_code(text: str) -> tuple[str, str]:
    """Pull (auth_code, state) out of a pasted redirect URL, or treat the text as a raw code."""
    if '://' in text or '?' in text or '=' in text:
        q = parse_qs(urlsplit(text).query)
        code = (q.get('auth_code') or q.get('code') or [''])[0]
        return code, (q.get('state') or [''])[0]
    return text, ''


def _active(db: Session, user: User) -> BrokerConnection | None:
    return (db.query(BrokerConnection).filter_by(user_id=user.id)
            .order_by(BrokerConnection.updated_at.desc()).first())


def _token_fresh_today(c: BrokerConnection) -> bool:
    """True if the user has logged in today (IST). SEBI requires a fresh login each trading day."""
    from radar.utils import IST, now_ist
    ts = c.token_refreshed_at
    if not ts or not c.token_enc:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(IST).date() == now_ist().date()


def _save_tokens(c: BrokerConnection, access: str, refresh: str) -> None:
    c.token_enc = encrypt(access)
    if refresh:
        c.refresh_enc = encrypt(refresh)
    c.token_refreshed_at = datetime.now(timezone.utc)
    c.status = 'connected'


@router.get('')
def get_broker(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    c = _active(db, user)
    callback = _callback_uri(request)
    redirect = (c.redirect_uri if c and c.redirect_uri else callback)
    return {
        'platforms': PLATFORMS,
        'callback_uri': callback,
        'active': None if c is None else {
            'platform': c.broker, 'app_id': c.app_id, 'redirect_uri': redirect,
            'status': c.status, 'has_secret': bool(c.secret_enc), 'has_token': bool(c.token_enc),
            'oauth': c.broker in _OAUTH,
            # auto = the broker redirects back to us (we capture silently); otherwise manual hand-off.
            'auto': redirect == callback,
            # SEBI mandates a fresh login each trading day — fresh_today = logged in today (IST).
            'fresh_today': _token_fresh_today(c),
            'token_refreshed_at': c.token_refreshed_at.isoformat() if c.token_refreshed_at else None,
        },
    }


@router.put('')
async def set_broker(request: Request, user: User = Depends(require_user),
                     db: Session = Depends(get_db)):
    b = await request.json()
    platform = b.get('platform')
    if platform not in _AVAILABLE:
        return JSONResponse({'error': 'That platform is not available yet.'}, status_code=400)
    app_id = (b.get('app_id') or '').strip()
    secret = (b.get('secret') or '').strip()
    # One active broker per user — drop any previous connection for a clean switch.
    for old in db.query(BrokerConnection).filter_by(user_id=user.id).all():
        if old.broker != platform:
            db.delete(old)
    c = db.query(BrokerConnection).filter_by(user_id=user.id, broker=platform).first()
    if c is None:
        c = BrokerConnection(user_id=user.id, broker=platform, capability='all')
        db.add(c)
    pin = (b.get('pin') or '').strip()
    if app_id:
        c.app_id = app_id
    if secret:
        c.secret_enc = encrypt(secret)
        c.token_enc = None  # new secret invalidates any old token — user must reconnect
        c.refresh_enc = None
    if pin:
        c.pin_enc = encrypt(pin)
    # Redirect URL: default to OUR callback (automatic capture). A user whose existing broker app
    # has its own registered redirect URL can supply it — we then use the manual code hand-off.
    custom = (b.get('redirect_uri') or '').strip()
    c.redirect_uri = custom or _callback_uri(request)
    c.status = 'configured' if (c.app_id and c.secret_enc) else 'incomplete'
    db.commit()
    return {'ok': True, 'status': c.status}


@router.post('/test')
async def test_broker(request: Request, user: User = Depends(require_user),
                      db: Session = Depends(get_db)):
    """Connection check. Works on the credentials in the form (passed in the body) even before
    they're saved. If a live token exists, performs a real read-only quote call."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    form_app = (body.get('app_id') or '').strip()
    form_secret = (body.get('secret') or '').strip()
    c = _active(db, user)

    # Resolve the credentials to check: prefer what's in the form, fall back to saved.
    app_id = form_app or (c.app_id if c else '')
    has_secret = bool(form_secret) or bool(c and c.secret_enc)
    if not app_id or not has_secret:
        return {'ok': False, 'message': 'Enter your App ID and Secret first.'}

    # Real quote call only possible with a saved live token.
    if c and c.broker == 'fyers' and c.token_enc and not form_secret:
        try:
            from radar.fyers import ApiError, FyersAdapter
            os.environ['FYERS_APP_ID'] = c.app_id
            os.environ['FYERS_ACCESS_TOKEN'] = decrypt(c.token_enc) or ''
            data = FyersAdapter({}).request('quotes', {'symbols': 'NSE:SBIN-EQ'})
            ok = any(x.get('s') == 'ok' for x in data.get('d', []))
            return {'ok': ok, 'message': 'Live market data is reachable — you are connected.'
                    if ok else 'Quote check failed — your token may have expired. Reconnect.'}
        except ApiError as e:
            return {'ok': False, 'message': str(e)[:160]}
        except Exception as e:
            return {'ok': False, 'message': f'{type(e).__name__}: {e}'[:160]}

    return {'ok': True, 'message': 'Credentials look good. Click Connect to log in and stream '
            'live data.'}


@router.get('/login')
def broker_login(request: Request, user: User = Depends(require_user),
                 db: Session = Depends(get_db)):
    """Automatic flow: the broker app is registered with OUR callback, so we redirect the browser
    to the broker sign-in and capture the token when it redirects back to /callback."""
    c = _active(db, user)
    if c is None or not c.app_id or not c.secret_enc:
        return RedirectResponse('/brokers?error=credentials', status_code=303)
    if c.broker not in _OAUTH:
        return RedirectResponse('/brokers?error=unsupported', status_code=303)
    callback = _callback_uri(request)
    if (c.redirect_uri or callback) != callback:
        # App uses a custom redirect — the broker won't send the code back to us. Use manual.
        return RedirectResponse('/brokers?error=manual', status_code=303)
    from radar.fyers import _auth_url
    c.redirect_uri = callback
    state = secrets.token_urlsafe(16)
    request.session['broker_oauth_state'] = state
    db.commit()
    return RedirectResponse(_auth_url(c.app_id, callback, state), status_code=303)


@router.post('/login-url')
def broker_login_url(request: Request, user: User = Depends(require_user),
                     db: Session = Depends(get_db)):
    """Manual flow (existing broker apps): return the sign-in URL built with the user's own
    registered redirect. The user opens it, signs in, and pastes the redirected URL back."""
    c = _active(db, user)
    if c is None or not c.app_id or not c.secret_enc:
        return JSONResponse({'error': 'Save your App ID and Secret first.'}, status_code=400)
    if c.broker not in _OAUTH:
        return JSONResponse({'error': 'Guided login for this platform is coming soon.'},
                            status_code=400)
    from radar.fyers import _auth_url
    redirect = c.redirect_uri or _callback_uri(request)
    state = secrets.token_urlsafe(16)
    request.session['broker_oauth_state'] = state
    return {'url': _auth_url(c.app_id, redirect, state), 'redirect_uri': redirect}


@router.post('/login-finish')
async def broker_login_finish(request: Request, user: User = Depends(require_user),
                              db: Session = Depends(get_db)):
    """Manual flow step 2: the user pastes the full URL they were redirected to (or just the
    auth_code). We extract the code and exchange it for an access token using their redirect."""
    body = await request.json()
    pasted = (body.get('response_url') or body.get('auth_code') or '').strip()
    if not pasted:
        return JSONResponse({'error': 'Paste the full URL you were redirected to.'},
                            status_code=400)
    c = _active(db, user)
    if c is None or not c.app_id or not c.secret_enc:
        return JSONResponse({'error': 'Save your App ID and Secret first.'}, status_code=400)
    auth_code, state = _parse_auth_code(pasted)
    if not auth_code:
        return JSONResponse({'error': 'That URL has no auth_code — paste the complete redirected '
                             'URL from your browser address bar.'}, status_code=400)
    expected = request.session.pop('broker_oauth_state', None)
    if state and expected and state != expected:
        return JSONResponse({'error': 'Security check failed (state mismatch). Start the login '
                             'again.'}, status_code=400)
    redirect = c.redirect_uri or _callback_uri(request)
    try:
        access, refresh = exchange_code(c.app_id, decrypt(c.secret_enc) or '', redirect, auth_code)
    except Exception as e:
        return JSONResponse({'error': 'The broker rejected the login: ' + str(e)[:140]},
                            status_code=400)
    _save_tokens(c, access, refresh)
    db.commit()
    return {'ok': True, 'auto_refresh': bool(c.pin_enc and c.refresh_enc)}


@router.get('/callback')
def broker_callback(request: Request, db: Session = Depends(get_db),
                    user: User | None = Depends(current_user)):
    """Broker OAuth redirect lands here. Exchange the auth_code for a token, save it, go back."""
    if user is None:
        return RedirectResponse('/brokers?error=session', status_code=303)
    params = request.query_params
    expected = request.session.pop('broker_oauth_state', None)
    if not params.get('state') or params.get('state') != expected:
        return RedirectResponse('/brokers?error=state', status_code=303)
    auth_code = params.get('auth_code')
    if not auth_code:
        return RedirectResponse('/brokers?error=' + (params.get('message') or 'no_code'),
                                status_code=303)
    c = _active(db, user)
    if c is None or not c.app_id or not c.secret_enc:
        return RedirectResponse('/brokers?error=credentials', status_code=303)
    try:
        access, refresh = exchange_code(c.app_id, decrypt(c.secret_enc) or '', c.redirect_uri,
                                        auth_code)
    except Exception:
        return RedirectResponse('/brokers?error=exchange', status_code=303)
    _save_tokens(c, access, refresh)
    db.commit()
    return RedirectResponse('/brokers?connected=1', status_code=303)


