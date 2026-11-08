from __future__ import annotations
import json
import os
from datetime import datetime, date, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
ROOT = Path(__file__).resolve().parent.parent


def now_ist() -> datetime:
    return datetime.now(IST)


def local_day(day: date | None = None) -> date:
    return day or now_ist().date()


def market_dt(day: date, hhmm: str) -> datetime:
    hour, minute = (int(x) for x in hhmm.split(':'))
    return datetime.combine(day, time(hour, minute), IST)


def bar_start(dt: datetime) -> datetime:
    t = dt.astimezone(IST)
    return t.replace(minute=(t.minute // 5) * 5, second=0, microsecond=0)


# Special NSE sessions (e.g. Diwali Muhurat) with a non-standard window. Auto-activates on the date
# and auto-expires after, so no env toggle to remember. Times are IST.
_SPECIAL_SESSIONS = {
    '2026-11-08': {'open_range_start': '14:20', 'watch_start': '14:25',
                   'new_signals_stop': '15:15', 'label': 'Diwali Muhurat'},
}


def special_session(day: date | None = None) -> dict | None:
    """The special-session override for `day` (default today IST), or None on a normal day."""
    key = (day or now_ist().date()).isoformat()
    return _SPECIAL_SESSIONS.get(key)


def is_special_session(day: date | None = None) -> bool:
    return special_session(day) is not None


def is_market_day(day: date | None = None) -> bool:
    """A normal weekday OR a special trading session (Muhurat can fall on a weekend)."""
    d = day or now_ist().date()
    return d.weekday() < 5 or is_special_session(d)


def load_config(path: str | Path | None = None) -> dict:
    with open(path or ROOT / 'config.json', encoding='utf-8') as f:
        cfg = json.load(f)
    special = special_session()
    if special:
        for k in ('open_range_start', 'watch_start', 'new_signals_stop'):
            cfg[k] = special[k]
    return cfg


def read_env(path: Path | None = None) -> None:
    """Local .env loader that won't override shell variables."""
    p = path or ROOT / '.env'
    if p.exists():
        for line in p.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('\"').strip("'"))


def previous_weekday(day: date) -> date:
    t = day - timedelta(days=1)
    while t.weekday() >= 5:
        t -= timedelta(days=1)
    return t


def safe_float(x, default=0.0) -> float:
    try:
        v = float(x)
        return v if v == v and abs(v) < 1e30 else default
    except (TypeError, ValueError):
        return default
