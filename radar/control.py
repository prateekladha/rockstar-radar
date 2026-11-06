"""Control Center backend (Phase 2 product).

Drives the exact same logic as the CLI (login, selection/watchlist, config, the live
scanner) but exposes it to a web UI so no terminal is needed. The proven `launch.py run`
scanner is managed as a subprocess and its live state is proxied, so the realtime engine
and rate-safety behavior are reused unchanged.

Per the 'design for public' principle, all state here is addressed through explicit paths
so a future multi-tenant layer can scope them per user without a rewrite.
"""
from __future__ import annotations
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from .fyers import (_auth_url, _exchange_and_save, _extract_auth_code, _login_creds,
                    _STATE_PATH)
from .selecting import SelectionError, load_morning_pins, normalize_morning_symbol
from .utils import ROOT, load_config, now_ist

_TIME_RE = re.compile(r'^(?:[01]?\d|2[0-3]):[0-5]\d$')

# Editable config fields: key -> (kind, min, max). 'time' fields are HH:MM strings.
EDITABLE_CONFIG = {
    'max_symbols': ('int', 1, 100),
    'min_price_inr': ('num', 1, 100000),
    'min_median_daily_turnover_cr': ('num', 0, 100000),
    'min_daily_atr_pct': ('num', 0, 50),
    'max_daily_atr_pct': ('num', 0, 50),
    'max_industry_members': ('int', 1, 100),
    'open_range_start': ('time', None, None),
    'open_range_minutes': ('int', 1, 60),
    'watch_start': ('time', None, None),
    'new_signals_stop': ('time', None, None),
    'near_boundary_pct': ('num', 0, 10),
    'ready_boundary_pct': ('num', 0, 10),
    'min_confirm_rvol': ('num', 0, 100),
    'min_watch_rvol': ('num', 0, 100),
    'min_bar_turnover_cr': ('num', 0, 10000),
    'min_open_range_width_pct': ('num', 0, 50),
    'max_open_range_width_pct': ('num', 0, 50),
    'max_extension_pct': ('num', 0, 50),
    'retest_tolerance_pct': ('num', 0, 50),
    'retest_expiry_minutes': ('int', 1, 240),
    'min_net_reward_risk': ('num', 0, 100),
    'estimated_roundtrip_cost_pct': ('num', 0, 10),
    'capital_inr': ('num', 0, 1000000000),
    'risk_pct': ('num', 0, 10),   # hard ceiling: keep conservative (0.5-1%)
}


class ControlError(Exception):
    pass


def validate_config_patch(patch: dict) -> dict:
    """Validate + coerce a config patch against EDITABLE_CONFIG. Returns cleaned values;
    raises ControlError on unknown key / wrong type / out-of-range. Shared by the global
    config writer and per-user settings."""
    cleaned = {}
    for key, value in patch.items():
        if key not in EDITABLE_CONFIG:
            raise ControlError(f'Unknown or protected config field: {key}')
        kind, lo, hi = EDITABLE_CONFIG[key]
        if kind == 'time':
            if not isinstance(value, str) or not _TIME_RE.match(value):
                raise ControlError(f'{key} must be HH:MM (24h), got {value!r}')
        else:
            try:
                num = int(value) if kind == 'int' else float(value)
            except (TypeError, ValueError):
                raise ControlError(f'{key} must be a {kind}, got {value!r}')
            if (lo is not None and num < lo) or (hi is not None and num > hi):
                raise ControlError(f'{key} must be between {lo} and {hi}, got {num}')
            value = num
        cleaned[key] = value
    return cleaned


class ControlCenter:
    def __init__(self, config_path: Optional[Path] = None, root: Optional[Path] = None,
                 demo: bool = False, env_extra: Optional[dict] = None):
        self.root = root or ROOT
        self.demo = demo   # cloud beta: run the simulated scanner, no FYERS credentials
        self.env_extra = env_extra or {}   # per-user broker token + universe for the subprocess
        self.config_path = Path(config_path) if config_path else self.root / 'config.json'
        self.env_path = self.root / '.env'
        self.watchlist_path = self.root / 'data' / 'morning_rockstars.txt'
        self.universe_path = self.root / 'data' / 'nifty500.csv'
        self.selection_path = self.root / 'data' / 'today100.json'
        # Per-account FYERS API lock + per-scanner log. In the multi-tenant server these are made
        # owner-specific (see server.scanners) so concurrent brokers never collide on one lock/file.
        self.lock_path = self.root / 'data' / '.fyers_api_process.lock'
        self.scanner_out_path = self.root / 'data' / 'scanner.out'
        self.scanner_port = int(os.environ.get('RADAR_SCANNER_PORT', '8899'))
        self.pid_path = self.root / 'data' / f'.scanner_{self.scanner_port}.pid'
        self._proc: Optional[subprocess.Popen] = None
        self._started_at: Optional[float] = None
        self._last_conn_check: Optional[dict] = None

    # ---- config -----------------------------------------------------------
    def get_config(self) -> dict:
        return load_config(self.config_path)

    def editable_config(self) -> dict:
        cfg = self.get_config()
        return {k: cfg.get(k) for k in EDITABLE_CONFIG}

    def update_config(self, patch: dict) -> dict:
        cfg = self.get_config()
        cfg.update(validate_config_patch(patch))
        if cfg.get('min_daily_atr_pct', 0) > cfg.get('max_daily_atr_pct', 0):
            raise ControlError('min_daily_atr_pct cannot exceed max_daily_atr_pct')
        if cfg.get('min_open_range_width_pct', 0) > cfg.get('max_open_range_width_pct', 0):
            raise ControlError('min_open_range_width_pct cannot exceed max_open_range_width_pct')
        self.config_path.write_text(json.dumps(cfg, indent=2) + '\n', encoding='utf-8')
        return self.editable_config()

    # ---- watchlist --------------------------------------------------------
    def get_watchlist(self) -> dict:
        raw = []
        if self.watchlist_path.exists():
            for line in self.watchlist_path.read_text(encoding='utf-8-sig').splitlines():
                line = line.split('#', 1)[0]  # strip comments per line, like load_morning_pins
                for tok in line.replace(',', ' ').split():
                    tok = tok.strip()
                    if tok:
                        raw.append(tok)
        cfg = self.get_config()
        merged = load_morning_pins(cfg, self.watchlist_path)  # canonical NSE:...-EQ, deduped
        return {'symbols': raw, 'resolved': merged,
                'config_pins': list(cfg.get('morning_pins') or [])}

    def set_watchlist(self, symbols: list[str]) -> dict:
        clean, seen = [], set()
        for s in symbols:
            s = (s or '').strip()
            if not s:
                continue
            canonical = normalize_morning_symbol(s)  # raises SelectionError if invalid
            if canonical not in seen:
                seen.add(canonical)
                clean.append(s.upper())
        self.watchlist_path.parent.mkdir(parents=True, exist_ok=True)
        self.watchlist_path.write_text('\n'.join(clean) + ('\n' if clean else ''), encoding='utf-8')
        return self.get_watchlist()

    # ---- connection / login ----------------------------------------------
    def _read_env_value(self, key: str) -> str:
        if not self.env_path.exists():
            return ''
        for line in self.env_path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                if k.strip() == key:
                    return v.strip().strip('"').strip("'")
        return ''

    def _write_env_value(self, key: str, value: str) -> None:
        lines = self.env_path.read_text(encoding='utf-8').splitlines() if self.env_path.exists() else []
        out, found = [], False
        for line in lines:
            if line.strip().startswith(key + '='):
                out.append(f'{key}={value}'); found = True
            else:
                out.append(line)
        if not found:
            out.append(f'{key}={value}')
        self.env_path.write_text('\n'.join(out) + '\n', encoding='utf-8')
        try:
            self.env_path.chmod(0o600)
        except OSError:
            pass
        os.environ[key] = value

    # ---- telegram ----
    def telegram_status(self) -> dict:
        return {'bot_token_present': bool(self._read_env_value('TELEGRAM_BOT_TOKEN')),
                'chat_id': self._read_env_value('TELEGRAM_CHAT_ID')}

    def set_telegram(self, bot_token: str, chat_id: str) -> dict:
        bot_token, chat_id = (bot_token or '').strip(), (chat_id or '').strip()
        if bot_token:
            self._write_env_value('TELEGRAM_BOT_TOKEN', bot_token)
        if chat_id:
            self._write_env_value('TELEGRAM_CHAT_ID', chat_id)
        return self.telegram_status()

    def test_telegram(self) -> dict:
        from .notify import send_telegram, telegram_configured
        if not telegram_configured():
            return {'ok': False, 'message': 'Set bot token and chat id first.'}
        return send_telegram('✅ Rockstar Radar — Telegram alerts are connected. '
                             'Actionable signals (RETEST_READY etc.) will arrive here.')

    def connection_status(self) -> dict:
        app_id = self._read_env_value('FYERS_APP_ID')
        token = self._read_env_value('FYERS_ACCESS_TOKEN')
        redirect = self._read_env_value('FYERS_REDIRECT_URI')
        return {
            'app_configured': bool(app_id) and 'YOUR_' not in app_id,
            'app_id': app_id,
            'redirect_uri': redirect,
            'token_present': bool(token),
            'last_check': self._last_conn_check,
        }

    def auth_url(self) -> str:
        """Build the FYERS login URL and persist the one-time state (no printing)."""
        app_id, _secret, redirect = _login_creds()
        import secrets as _secrets
        state = _secrets.token_urlsafe(20)
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(state, encoding='utf-8')
        try:
            _STATE_PATH.chmod(0o600)
        except OSError:
            pass
        return _auth_url(app_id, redirect, state)

    def complete_login(self, response_url: str) -> dict:
        app_id, secret, redirect = _login_creds()
        if not response_url or not response_url.strip():
            raise ControlError('Missing redirect URL / auth code.')
        expected = _STATE_PATH.read_text(encoding='utf-8').strip() if _STATE_PATH.exists() else ''
        if not expected:
            raise ControlError('No pending login. Click "Connect FYERS" first.')
        auth_code = _extract_auth_code(response_url, expected)
        _exchange_and_save(app_id, secret, redirect, auth_code)
        try:
            _STATE_PATH.unlink()
        except OSError:
            pass
        return self.connection_status()

    def test_connection(self) -> dict:
        """Live one-symbol read-only quote check; caches the result."""
        from .fyers import ApiError, FyersAdapter
        try:
            cfg = self.get_config()
            adapter = FyersAdapter(cfg)
            data = adapter.request('quotes', {'symbols': 'NSE:SBIN-EQ'})
            ok = any(x.get('s') == 'ok' for x in data.get('d', []))
            result = {'ok': ok, 'message': 'Live market data reachable.' if ok
                      else 'Quote call returned no valid data.',
                      'at': now_ist().strftime('%Y-%m-%d %H:%M:%S')}
        except ApiError as e:
            result = {'ok': False, 'message': str(e)[:200],
                      'at': now_ist().strftime('%Y-%m-%d %H:%M:%S')}
        self._last_conn_check = result
        return result

    # ---- scanner lifecycle (subprocess) ----------------------------------
    def _pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _read_pid(self) -> Optional[int]:
        if self.pid_path.exists():
            try:
                return int(self.pid_path.read_text().strip())
            except (ValueError, OSError):
                return None
        return None

    def scanner_status(self) -> dict:
        pid = self._read_pid()
        running = bool(pid and self._pid_alive(pid))
        if not running and self.pid_path.exists():
            try:
                self.pid_path.unlink()
            except OSError:
                pass
        uptime = int(time.time() - self._started_at) if (running and self._started_at) else None
        return {'running': running, 'pid': pid if running else None,
                'scanner_port': self.scanner_port, 'uptime_seconds': uptime}

    def start_scanner(self) -> dict:
        if self.scanner_status()['running']:
            raise ControlError('Scanner is already running.')
        command = 'demo' if self.demo else 'run'
        if (not self.demo and not self.env_extra.get('FYERS_ACCESS_TOKEN')
                and not self.connection_status()['token_present']):
            raise ControlError('Connect FYERS (login) before starting the scanner.')
        self.pid_path.parent.mkdir(parents=True, exist_ok=True)
        self.scanner_out_path.parent.mkdir(parents=True, exist_ok=True)
        log = self.scanner_out_path.open('ab')
        env = {**os.environ, **{k: str(v) for k, v in self.env_extra.items() if v is not None}}
        cmd = [sys.executable, str(self.root / 'launch.py'), command, '--port', str(self.scanner_port)]
        if not self.demo:
            # Isolate this scanner's selection + API lock (per broker-owner in the server).
            cmd += ['--selection', str(self.selection_path), '--lock', str(self.lock_path)]
        proc = subprocess.Popen(
            cmd, cwd=str(self.root), stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True, env=env)
        self._proc = proc
        self._started_at = time.time()
        self.pid_path.write_text(str(proc.pid), encoding='utf-8')
        return self.scanner_status()

    def stop_scanner(self) -> dict:
        pid = self._read_pid()
        if pid and self._pid_alive(pid):
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
        if self.pid_path.exists():
            try:
                self.pid_path.unlink()
            except OSError:
                pass
        self._proc = None
        self._started_at = None
        return {'running': False, 'pid': None,
                'scanner_port': self.scanner_port, 'uptime_seconds': None}

    def live_state(self) -> dict:
        """Proxy the scanner subprocess's /api/state; return offline marker if down."""
        if not self.scanner_status()['running']:
            return {'offline': True, 'reason': 'Scanner not running'}
        try:
            with urllib.request.urlopen(
                    f'http://127.0.0.1:{self.scanner_port}/api/state', timeout=3) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except (urllib.error.URLError, OSError, ValueError):
            return {'offline': True, 'reason': 'Scanner starting (preparing universe)…'}
