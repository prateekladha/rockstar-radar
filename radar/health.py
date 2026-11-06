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


def write_health(scanner_id: str, *, ok: bool, need_login: bool = False, reason: str = '') -> None:
    if not scanner_id:
        return
    try:
        p = _path(scanner_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            'ok': bool(ok), 'need_login': bool(need_login), 'reason': reason or '',
            'at': datetime.now(timezone.utc).isoformat(),
        }), encoding='utf-8')
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
