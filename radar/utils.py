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


def load_config(path: str | Path | None = None) -> dict:
    with open(path or ROOT / 'config.json', encoding='utf-8') as f:
        return json.load(f)


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
