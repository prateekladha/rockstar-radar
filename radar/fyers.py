"""FYERS data-only adapter; does not import or call any order endpoint."""
from __future__ import annotations
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser
from collections import deque
from datetime import datetime
from pathlib import Path
from .models import Candle, Tick
from .utils import IST, ROOT, safe_float


class ApiError(RuntimeError):
    pass


class ApiAuthError(ApiError):
    pass


class ApiRateLimitError(ApiError):
    pass


class ApiPermissionError(ApiError):
    pass


class ApiInputError(ApiError):
    """FYERS explicitly reported invalid request input or symbol."""


class ApiProviderError(ApiError):
    """Ambiguous upstream/SDK failure: do not fan out requests to diagnose."""


class RateLimiter:
    """Conservative single-process REST limiter; NEVER use as a way around FYERS blocks.

    Deliberately below the FYERS Standard plan's 50/min published maximum to
    allow headroom for login, other FYERS activity and provider-side policies.
    A launch-level file lock separately prevents two local Radar API processes.
    """
    def __init__(self, spacing: float = 2.5, per_minute: int = 24, per_day: int = 4500):
        self.spacing = max(float(spacing), 2.5)
        self.per_minute = min(int(per_minute), 24)
        self.per_day = min(int(per_day), 4500)
        self.calls: deque[float] = deque()
        self.last = 0.0
        self.daily = 0
        self.current_day = None
        self.lock = threading.RLock()

    def acquire(self):
        while True:
            with self.lock:
                now = time.monotonic()
                today = datetime.now(IST).date()
                if self.current_day != today:
                    self.current_day, self.daily = today, 0
                    self.calls.clear()
                if self.daily >= self.per_day:
                    raise ApiRateLimitError('Local FYERS daily request safety budget reached. Stop for today.')
                while self.calls and now - self.calls[0] >= 60:
                    self.calls.popleft()
                wait = max(0, self.spacing - (now - self.last))
                if len(self.calls) >= self.per_minute:
                    wait = max(wait, 60 - (now - self.calls[0]) + 0.05)
                if wait <= 0:
                    self.calls.append(now)
                    self.last = now
                    self.daily += 1
                    return
            time.sleep(min(wait, 1.5))


class FyersAdapter:
    def __init__(self, config: dict):
        self.app_id = os.environ.get('FYERS_APP_ID', '').strip()
        self.token = os.environ.get('FYERS_ACCESS_TOKEN', '').strip()
        if not self.app_id or not self.token or 'YOUR_' in self.app_id:
            raise ApiError('Missing FYERS_APP_ID or FYERS_ACCESS_TOKEN in local .env. Run: python launch.py login')
        try:
            from fyers_apiv3 import fyersModel
        except ImportError as e:
            raise ApiError('Install FYERS SDK first: python -m pip install -r requirements.txt') from e
        self.client = fyersModel.FyersModel(client_id=self.app_id, token=self.token,
                                           is_async=False, log_path='')
        self.limit = RateLimiter(config.get('history_request_interval_seconds', 2.5))

    def request(self, method: str, data: dict) -> dict:
        """REST wrapper. Never retry permanent/ambiguous parameter failures blindly.

        FYERS SDK versions sometimes replace network/JSON exceptions with generic
        (-99, Bad request). The response alone is NOT proof of invalid symbols.
        """
        for attempt in range(3):
            self.limit.acquire()
            try:
                res = getattr(self.client, method)(data=data)
            except (OSError, RuntimeError) as e:
                # Only obvious transient exceptions are retried; no credentials
                # or whole request payload are ever logged.
                if attempt == 2:
                    raise ApiError(f'FYERS {method} transport failed: {type(e).__name__}: {e}') from e
                time.sleep(1.5 * (attempt + 1))
                continue
            except Exception as e:
                raise ApiError(f'FYERS {method} SDK exception: {type(e).__name__}: {e}') from e
            if not isinstance(res, dict):
                raise ApiError(f'Unexpected FYERS {method} response type: {type(res).__name__}')
            if res.get('s') == 'ok' or (method in ('quotes', 'quotes_v2') and
                                        res.get('code') == 200 and isinstance(res.get('d'), list)):
                return res
            code = res.get('code')
            err = str(res.get('message') or 'unspecified error')[:250]
            lowered = err.lower()
            if any(phrase in lowered for phrase in (
                    'error 1015', 'temporarily banned', 'temporarily blocked',
                    'rate limit', 'too many requests', 'cloudflare')):
                raise ApiRateLimitError(f'FYERS {method} access restricted: {err}. '
                                        'STOP requests and contact FYERS if the restriction persists.')
            if code in (-8, -15, -16, -17):
                raise ApiAuthError(f'FYERS {method} token expired/invalid ({code}). Run: python launch.py login')
            if code in (-360, -429, 429):
                raise ApiRateLimitError(f'FYERS {method} rate limit ({code}): {err}. Stop requests and retry later.')
            if code == 403:
                raise ApiPermissionError(f'FYERS {method} permission denied (403): {err}. '
                                         'Check Market Data permission on the FYERS app.')
            if code in (-50, -300, 400):
                raise ApiInputError(f'FYERS {method} rejected request input ({code}): {err}')
            if code == -99:
                # An SDK version may mask Cloudflare's HTML response as -99.
                # Never bisect 50 -> 25 -> ... on an opaque provider error.
                raise ApiProviderError(f'FYERS {method} returned generic -99: {err}; '
                                       'may be a provider/transport block. Do not retry in a loop.')
            if code not in (500, 502, 503, 504) or attempt == 2:
                raise ApiError(f'FYERS {method} ({code}): {err}')
            time.sleep(1.5 * (attempt + 1))
        raise ApiError(f'FYERS {method} request failed')

    def quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Retrieve quotes, isolate bad symbols ONLY for explicit input errors.

        The Standard plan allows 50 symbols per call. If a GET batch fails, try
        the official POST quotes_v2 method when installed; otherwise bisect to
        find a bad/unsupported FYERS symbol without losing the entire universe.
        Opaque -99 failures stop immediately so bans cannot trigger request storms.
        """
        if not symbols:
            return {}
        results: dict[str, dict] = {}
        skipped: dict[str, str] = {}
        request_count = 0

        def fetch(chunk: list[str]):
            nonlocal request_count
            if not chunk:
                return
            if len(chunk) > 50:
                raise ApiError('Internal error: quotes chunk exceeds Standard 50-symbol limit')
            request_count += 1
            failures: list[ApiError] = []
            response = None
            try:
                response = self.request('quotes', {'symbols': ','.join(chunk)})
            except (ApiAuthError, ApiRateLimitError, ApiPermissionError):
                raise
            except ApiError as e:
                failures.append(e)
                # FYERS quotes_v2 is the documented POST alternative, even on
                # Standard plan with up to 50 symbols. Older SDKs may lack it.
                if hasattr(self.client, 'quotes_v2'):
                    try:
                        request_count += 1
                        response = self.request('quotes_v2', {'symbols': list(chunk)})
                    except (ApiAuthError, ApiRateLimitError, ApiPermissionError):
                        raise
                    except ApiError as post_err:
                        failures.append(post_err)
            if response is not None:
                present = set()
                for row in response.get('d', []):
                    name = row.get('n', '')
                    if name not in chunk:
                        continue
                    present.add(name)
                    if row.get('s') == 'ok':
                        results[name] = row.get('v', {})
                    else:
                        skipped[name] = str(row.get('message') or 'FYERS marked symbol invalid')[:150]
                # An incomplete 'ok' response is not silently treated as quotes
                # for stocks that were not returned.
                for name in chunk:
                    if name not in present:
                        skipped[name] = 'Missing from successful FYERS quote response'
                return
            if not failures or not all(isinstance(e, ApiInputError) for e in failures):
                # Most importantly: two masked Cloudflare bans must not trigger
                # up to ~100 recursive quote requests for one batch of 50.
                detail = ' | '.join(str(err) for err in failures)[:300]
                raise ApiProviderError(f'FYERS quote batch failed; stopping without '
                                       f'splitting or retrying: {detail}')
            # Bisection is permitted only for an explicit invalid-symbol/input
            # response from FYERS, never for SDK -99 or a suspected rate limit.
            if len(chunk) == 1:
                skipped[chunk[0]] = ' | '.join(str(e) for e in failures)[:400]
                if len(skipped) >= 15 and not results:
                    raise ApiError('No usable quotes; at least 15 individual symbols failed. '
                                   'Run `python launch.py doctor` and verify network, market-data '
                                   'permission, token, SDK, and FYERS service status.')
                return
            mid = len(chunk) // 2
            fetch(chunk[:mid]); fetch(chunk[mid:])

        for i in range(0, len(symbols), 50):
            fetch(symbols[i:i + 50])
        if skipped:
            items = list(skipped.items())
            print(f'WARNING: FYERS quotes skipped {len(skipped)} of {len(symbols)} symbols; '
                  f'{len(results)} returned successfully (REST calls: {request_count}).')
            for symbol, err in items[:8]:
                print(f'  Unavailable {symbol}: {err[:150]}')
            if len(items) > 8:
                print(f'  ... plus {len(items) - 8} other missing symbols')
        if not results:
            raise ApiError('FYERS quotes returned zero usable stocks. Run `python launch.py doctor`; '
                           'check app market-data permission and valid daily token.')
        return results

    def doctor(self, universe_path: Path | None = None) -> None:
        """No-secret connection diagnostic using read-only quote requests."""
        import importlib.metadata
        try:
            version = importlib.metadata.version('fyers-apiv3')
        except importlib.metadata.PackageNotFoundError:
            version = 'unknown'
        print(f'FYERS SDK installed: {version}')
        print(f'GET Quotes API: checking one known symbol NSE:SBIN-EQ (no orders).')
        try:
            data = self.request('quotes', {'symbols': 'NSE:SBIN-EQ'})
            valid = [x for x in data.get('d', []) if x.get('s') == 'ok' and x.get('n') == 'NSE:SBIN-EQ']
            if not valid:
                raise ApiError('SBIN request returned no valid quote row')
        except ApiError as e:
            print('Single-symbol GET failed:', e)
            if hasattr(self.client, 'quotes_v2'):
                print('Trying official POST Quotes v2 for one symbol...')
                try:
                    data = self.request('quotes_v2', {'symbols': ['NSE:SBIN-EQ']})
                    valid = [x for x in data.get('d', []) if x.get('s') == 'ok' and x.get('n') == 'NSE:SBIN-EQ']
                    if not valid:
                        raise ApiError('POST returned no valid quote row')
                    print('POST quotes_v2 PASSED. GET may be problematic with your SDK/network.')
                except ApiError as post_err:
                    raise ApiError('Neither Quotes GET nor POST works for a known-valid stock. '
                                   f'GET: {e}; POST: {post_err}. Check Market Data permission, '
                                   'token validity, network/firewall and latest FYERS SDK.') from post_err
            else:
                raise ApiError('Single-symbol Quotes GET failed. Check Market Data permission, '
                               'daily token, latest FYERS SDK and network connection.') from e
        else:
            print('Single-symbol GET PASSED.')
        if universe_path and universe_path.exists():
            from .selecting import load_universe
            sample = [symbol for symbol, _ in load_universe(universe_path)][:50]
            print(f'Testing a full {len(sample)}-stock batch from the local universe...')
            quotes = self.quotes(sample)
            print(f'Batch test: {len(quotes)}/{len(sample)} usable quotes.')
            if len(quotes) < 40:
                raise ApiError('Fewer than 40 of the 50 test stocks returned quotes. '
                               'Check unsupported symbols in the NIFTY list or FYERS SDK logs.')
        else:
            print('Universe CSV not present; skipped 50-stock batch test. '
                  'Run `python launch.py download-universe` to enable it.')
        print('Doctor complete. You may run: python launch.py prepare')

    def history(self, symbol: str, resolution: str, frm: int, to: int) -> list[Candle]:
        result = self.request('history', {
            'symbol': symbol, 'resolution': resolution, 'date_format': '0',
            'range_from': str(int(frm)), 'range_to': str(int(to)), 'cont_flag': '1'
        })
        candles = []
        for raw in result.get('candles', []):
            try:
                candles.append(Candle.from_fyers(raw))
            except (ValueError, TypeError):
                continue
        return sorted(candles, key=lambda x: x.at)

    def subscribe(self, symbols: list[str], on_tick, on_health):
        """Blocking streaming connection. SDK internally reconnects; caller runs on own thread."""
        if len(symbols) > 100:
            raise ApiError('Cannot stream more than FYERS Standard 100-symbol cap.')
        try:
            from fyers_apiv3.FyersWebsocket import data_ws
        except ImportError as e:
            raise ApiError('FYERS SDK not installed') from e
        token = f'{self.app_id}:{self.token}'
        holder = {}

        def handle_message(msg):
            if not isinstance(msg, dict):
                return
            if msg.get('type') != 'sf':
                return
            try:
                symbol = msg['symbol']
                epoch = msg.get('exch_feed_time') or msg.get('last_traded_time')
                price = safe_float(msg.get('ltp'))
                if not epoch or not price or symbol not in symbols:
                    return
                on_tick(Tick(symbol=symbol, price=price,
                             time=datetime.fromtimestamp(int(epoch), IST),
                             daily_volume=int(msg.get('vol_traded_today') or 0),
                             avg_trade_price=safe_float(msg.get('avg_trade_price')),
                             bid_price=safe_float(msg.get('bid_price')),
                             ask_price=safe_float(msg.get('ask_price'))))
            except (KeyError, ValueError, TypeError) as e:
                on_health(f'Ignored invalid tick: {e}')

        def on_connect():
            on_health('CONNECTED')
            holder['socket'].subscribe(symbols=symbols, data_type='SymbolUpdate')
            holder['socket'].keep_running()

        def on_error(error):
            on_health(f'WebSocket error: {type(error).__name__}: {error}')

        def on_close(msg):
            on_health('DISCONNECTED: ' + str(msg)[:140])

        holder['socket'] = data_ws.FyersDataSocket(
            access_token=token, log_path='', litemode=False,
            write_to_file=False, reconnect=True, reconnect_retry=10,
            on_connect=on_connect, on_message=handle_message,
            on_error=on_error, on_close=on_close
        )
        holder['socket'].connect()
        return holder['socket']


_STATE_PATH = ROOT / 'data' / '.oauth_login_state'


def _login_creds():
    app_id = os.environ.get('FYERS_APP_ID', '').strip()
    secret = os.environ.get('FYERS_APP_SECRET', '').strip()
    redirect = os.environ.get('FYERS_REDIRECT_URI', '').strip()
    if not app_id or not secret or not redirect or 'YOUR_' in app_id:
        raise ApiError('Set APP_ID, APP_SECRET and REDIRECT_URI in local .env first.')
    return app_id, secret, redirect


def _auth_url(app_id: str, redirect: str, state: str) -> str:
    query = urllib.parse.urlencode({'client_id': app_id, 'redirect_uri': redirect,
                                    'response_type': 'code', 'state': state})
    return 'https://api-t1.fyers.in/api/v3/generate-authcode?' + query


def _exchange_and_save(app_id: str, secret: str, redirect: str, auth_code: str) -> str:
    from fyers_apiv3 import fyersModel
    session = fyersModel.SessionModel(client_id=app_id, secret_key=secret,
             redirect_uri=redirect, response_type='code', grant_type='authorization_code')
    session.set_token(auth_code)
    result = session.generate_token()
    if result.get('s') != 'ok' or not result.get('access_token'):
        raise ApiError('Token request failed: ' + str(result.get('message', 'unknown')))
    token = result['access_token']
    p = ROOT / '.env'
    lines = p.read_text(encoding='utf-8').splitlines() if p.exists() else []
    lines = [l for l in lines if not l.startswith('FYERS_ACCESS_TOKEN=')]
    lines.append('FYERS_ACCESS_TOKEN=' + token)
    p.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    try:
        p.chmod(0o600)
    except OSError:
        pass
    os.environ['FYERS_ACCESS_TOKEN'] = token
    return token


def _extract_auth_code(response_url: str, expected_state: str) -> str:
    params = urllib.parse.parse_qs(urllib.parse.urlsplit(response_url.strip()).query)
    if params.get('state', [''])[0] != expected_state:
        raise ApiError('OAuth state mismatch; login aborted. Do not continue.')
    auth_code = params.get('auth_code', [''])[0]
    if not auth_code:
        raise ApiError('The redirect URL did not contain an auth_code.')
    return auth_code


def login_interactive():
    """Interactive single-step login (needs a real terminal for the paste prompt)."""
    app_id, secret, redirect = _login_creds()
    state = secrets.token_urlsafe(20)
    url = _auth_url(app_id, redirect, state)
    print('FYERS login URL (opened in your browser):\n' + url)
    webbrowser.open(url)
    response_url = input('Paste COMPLETE redirect URL into this LOCAL terminal: ').strip()
    auth_code = _extract_auth_code(response_url, state)
    _exchange_and_save(app_id, secret, redirect, auth_code)
    print('Login successful. Token saved only to local .env; renew after 06:30 IST daily.')


def login_url() -> str:
    """Step 1 of a non-interactive login: print the auth URL and persist the state."""
    app_id, secret, redirect = _login_creds()
    state = secrets.token_urlsafe(20)
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(state, encoding='utf-8')
    try:
        _STATE_PATH.chmod(0o600)
    except OSError:
        pass
    url = _auth_url(app_id, redirect, state)
    print('STEP 1/2 — open this URL, sign in to FYERS, then copy the FULL redirect URL '
          'from your browser address bar:\n' + url)
    print('\nSTEP 2/2 — run:  python launch.py login-finish "<paste the full redirect URL>"')
    try:
        webbrowser.open(url)
    except Exception:
        pass
    return url


def login_finish(response_url: str | None) -> None:
    """Step 2 of a non-interactive login: exchange the pasted redirect URL for a token."""
    app_id, secret, redirect = _login_creds()
    if not response_url or not response_url.strip():
        raise ApiError('Pass the redirect URL: python launch.py login-finish "<full url>"')
    expected = _STATE_PATH.read_text(encoding='utf-8').strip() if _STATE_PATH.exists() else ''
    if not expected:
        raise ApiError('No pending login. Run `python launch.py login-url` first.')
    auth_code = _extract_auth_code(response_url, expected)
    _exchange_and_save(app_id, secret, redirect, auth_code)
    try:
        _STATE_PATH.unlink()
    except OSError:
        pass
    print('Login successful. Token saved only to local .env; renew after 06:30 IST daily.')
