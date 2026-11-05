"""FYERS token lifecycle — auth-code exchange and daily PIN-based refresh.

FYERS v3 access tokens expire each day (~06:30 IST). validate-authcode returns both a daily
access_token and a ~15-day refresh_token. With the user's trading PIN we can mint a fresh daily
access_token from the refresh_token via validate-refresh-token — no re-login for ~15 days.
"""
from __future__ import annotations
import hashlib

import requests

_API = 'https://api-t1.fyers.in/api/v3'
_TIMEOUT = 20


class TokenError(RuntimeError):
    pass


def app_id_hash(app_id: str, secret: str) -> str:
    return hashlib.sha256(f'{app_id}:{secret}'.encode()).hexdigest()


def exchange_code(app_id: str, secret: str, redirect: str, auth_code: str) -> tuple[str, str]:
    """Exchange an auth_code for (access_token, refresh_token)."""
    from fyers_apiv3 import fyersModel
    session = fyersModel.SessionModel(client_id=app_id, secret_key=secret, redirect_uri=redirect,
                                      response_type='code', grant_type='authorization_code')
    session.set_token(auth_code)
    result = session.generate_token()
    if result.get('s') != 'ok' or not result.get('access_token'):
        raise TokenError('Token request failed: ' + str(result.get('message', 'unknown')))
    return result['access_token'], (result.get('refresh_token') or '')


def refresh_access_token(app_id: str, secret: str, refresh_token: str, pin: str) -> str:
    """Mint a fresh daily access_token from a refresh_token + trading PIN."""
    if not refresh_token or not pin:
        raise TokenError('Missing refresh token or PIN.')
    try:
        resp = requests.post(f'{_API}/validate-refresh-token', timeout=_TIMEOUT, json={
            'grant_type': 'refresh_token',
            'appIdHash': app_id_hash(app_id, secret),
            'refresh_token': refresh_token,
            'pin': str(pin),
        })
        data = resp.json()
    except Exception as e:
        raise TokenError(f'Refresh request failed: {type(e).__name__}: {e}') from e
    if data.get('s') != 'ok' or not data.get('access_token'):
        raise TokenError('Refresh rejected: ' + str(data.get('message', 'unknown')))
    return data['access_token']
