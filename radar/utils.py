from __future__ import annotations
import json
import os
from datetime import datetime, date, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
ROOT = Path(__file__).resolve().parent.parent


# Simulation clock: when installed (only inside a `launch.py sim` subprocess), now_ist() returns an
# accelerated sim time instead of the wall clock, so the WHOLE engine runs in sim time. Every module
# calls now_ist() (the function), so this one hook reroutes them all. The simulation loop re-anchors
# the clock to the session start at the top of each replay cycle (reanchor_sim_clock).
_SIM = None   # {'start': datetime, 'speed': float, 'anchor': datetime}


def install_sim_clock(sim_start_hhmm: str, speed: float) -> None:
    """Start a sim clock at today's `sim_start_hhmm`, advancing `speed`x real time."""
    global _SIM
    anchor = datetime.now(IST)
    hour, minute = (int(x) for x in sim_start_hhmm.split(':'))
    _SIM = {'start': datetime.combine(anchor.date(), time(hour, minute), IST),
            'speed': max(1.0, float(speed)), 'anchor': anchor}


def reanchor_sim_clock() -> None:
    """Reset the sim clock to the session start, now (called at the start of each replay cycle)."""
    if _SIM is not None:
        _SIM['anchor'] = datetime.now(IST)


def now_ist() -> datetime:
    if _SIM is not None:
        elapsed = (datetime.now(IST) - _SIM['anchor']).total_seconds() * _SIM['speed']
        return _SIM['start'] + timedelta(seconds=elapsed)
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


# NSE equity trading HOLIDAYS (weekday closures) — the market is shut even though it's a weekday, so
# don't start scanners / burn FYERS requests, and show users a clean "market closed" message. Source:
# official NSE 2026 holiday calendar. Update yearly. (Weekend holidays are already covered by weekday()>=5;
# listing a weekend date here is harmless.) A special session (Muhurat) overrides this.
_HOLIDAYS = {
    '2026-01-26': 'Republic Day', '2026-03-03': 'Holi', '2026-03-26': 'Shri Ram Navami',
    '2026-03-31': 'Shri Mahavir Jayanti', '2026-04-03': 'Good Friday',
    '2026-04-14': 'Dr. Baba Saheb Ambedkar Jayanti', '2026-05-01': 'Maharashtra Day',
    '2026-05-28': 'Bakri Id', '2026-06-26': 'Muharram', '2026-09-14': 'Ganesh Chaturthi',
    '2026-10-02': 'Mahatma Gandhi Jayanti', '2026-10-20': 'Dussehra',
    '2026-11-10': 'Diwali-Balipratipada', '2026-11-24': 'Prakash Gurpurb Sri Guru Nanak Dev',
    '2026-12-25': 'Christmas',
}


def special_session(day: date | None = None) -> dict | None:
    """The special-session override for `day` (default today IST), or None on a normal day."""
    key = (day or now_ist().date()).isoformat()
    return _SPECIAL_SESSIONS.get(key)


def is_special_session(day: date | None = None) -> bool:
    return special_session(day) is not None


def holiday(day: date | None = None) -> str | None:
    """The NSE holiday name for `day` (default today IST), or None. A special session is NOT a
    holiday (Muhurat trades)."""
    d = day or now_ist().date()
    if is_special_session(d):
        return None
    return _HOLIDAYS.get(d.isoformat())


def is_market_day(day: date | None = None) -> bool:
    """A trading day: a weekday that is NOT an NSE holiday, OR a special session (Muhurat, which can
    fall on a weekend/holiday)."""
    d = day or now_ist().date()
    if is_special_session(d):
        return True
    return d.weekday() < 5 and holiday(d) is None


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
