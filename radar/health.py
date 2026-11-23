"""Scanner health signal — a tiny per-scanner status file the subprocess writes and the server reads.

Why it exists: a scanner can look "fresh" at the DB level (a token minted today) yet be rejected by
FYERS at runtime (-15/-16 "token expired/invalid"), or halt mid-session (auth, rate-limit, provider
outage). The subprocess knows the real outcome; the web process needs it to (a) show a Reconnect CTA
instead of a fake "live" feed, (b) fall back to the household's shared feed, and (c) avoid restarting
a scanner that will only auth-fail again.

Stored at ROOT/data/scanner_health_<scanner_id>.json. Best-effort: any IO error is swallowed.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone

from .utils import ROOT


def _path(scanner_id: str):
    return ROOT / 'data' / f'scanner_health_{scanner_id}.json'


def write_health(scanner_id: str, *, ok: bool, need_login: bool = False,
                 rate_limited: bool = False, reason: str = '', warmup: dict | None = None) -> None:
    if not scanner_id:
        return
    try:
        p = _path(scanner_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            'ok': bool(ok), 'need_login': bool(need_login), 'rate_limited': bool(rate_limited),
            'reason': reason or '', 'at': datetime.now(timezone.utc).isoformat(),
        }
        # Warm-up progress ({'done': int, 'total': int, 'phase': str}) — lets the web process show
        # "Warming up — X/N symbols ready" before the scanner's dashboard is up.
        if warmup is not None:
            payload['warmup'] = warmup
        p.write_text(json.dumps(payload), encoding='utf-8')
    except OSError:
        pass


def read_health(scanner_id: str) -> dict | None:
    if not scanner_id:
        return None
    try:
        return json.loads(_path(scanner_id).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def clear_health(scanner_id: str) -> None:
    if not scanner_id:
        return
    try:
        _path(scanner_id).unlink()
    except OSError:
        pass


def health_at(health: dict | None) -> datetime | None:
    """Parse the stored 'at' timestamp (tz-aware UTC), or None."""
    if not health or not health.get('at'):
        return None
    try:
        ts = datetime.fromisoformat(health['at'])
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def generic_failure_active(health: dict | None, token_refreshed_at, now: datetime,
                           window_secs: float = 600.0) -> bool:
    """True when the scanner's last health is a GENERIC start failure that should pause auto-restart.

    A scanner that crashes on start writes ok=False. Auth and rate-limit crashes carry their own
    flags (need_login / rate_limited) and are handled by dedicated guards. Everything else — e.g. the
    "too few RVOL baselines" ValueError — is a *generic* failure with neither flag. Without this, the
    web poll path respawns the scanner on every ~3s poll, and each respawn re-fetches ~100 FYERS
    history calls, so a scanner that keeps failing can exhaust the whole daily quota in minutes.

    Returns True only while the failure is recent (within `window_secs`) and the broker has NOT been
    re-logged-in since (a token minted after the failure earns a fresh attempt). `now` and
    `token_refreshed_at` may be naive or tz-aware; naive values are read as UTC.
    """
    if not health or health.get('ok') is not False:
        return False
    if health.get('need_login') or health.get('rate_limited'):
        return False  # handled by the auth / rate-limit guards
    at = health_at(health)
    if at is None:
        return False
    if token_refreshed_at is not None:
        tok = token_refreshed_at
        tok = tok if tok.tzinfo else tok.replace(tzinfo=timezone.utc)
        if tok > at:
            return False  # logged in after the failure — allow a fresh attempt
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return (now - at).total_seconds() <= window_secs
