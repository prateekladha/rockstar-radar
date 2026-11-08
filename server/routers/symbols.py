"""Symbol search by company NAME or ticker (order entry / watchlist add).

Source of truth is the full FYERS NSE cash-market symbol master (every tradable NSE EQ stock), cached
on disk + in memory, refreshed daily. Falls back to the NIFTY 500 constituent CSV, then a tiny static
list, so search always works even if the download is unavailable.
"""
from __future__ import annotations
import csv
import re
import urllib.request
from datetime import date

from fastapi import APIRouter, Depends, Query

from radar.utils import ROOT, now_ist

from ..auth import require_user
from ..models import User

router = APIRouter(tags=['symbols'])
_CACHE = None   # list of {symbol, name}
_CACHE_DAY = None

# FYERS public symbol master for NSE cash market (all EQ/BE equities).
_FYERS_NSE_URL = 'https://public.fyers.in/sym_details/NSE_CM.csv'
_EQ_RE = re.compile(r'^NSE:[A-Z0-9&._-]+-(EQ|BE)$')

_FALLBACK = [
    ('RELIANCE', 'Reliance Industries'), ('SBIN', 'State Bank of India'),
    ('HDFCBANK', 'HDFC Bank'), ('ICICIBANK', 'ICICI Bank'), ('INFY', 'Infosys'),
    ('TCS', 'Tata Consultancy Services'), ('BHARTIARTL', 'Bharti Airtel'),
    ('TATAMOTORS', 'Tata Motors'), ('AXISBANK', 'Axis Bank'), ('LT', 'Larsen & Toubro'),
]


def _parse_fyers_master(text: str) -> list[dict]:
    rows = []
    seen = set()
    for line in text.splitlines():
        if not line or 'NSE:' not in line:
            continue
        fields = [f.strip() for f in line.split(',')]
        sym = next((f for f in fields if _EQ_RE.match(f)), None)
        if not sym or sym in seen:
            continue
        seen.add(sym)
        # FYERS puts a descriptive name in field[1]; fall back to the bare ticker.
        bare = sym[4:].rsplit('-', 1)[0]
        name = fields[1] if len(fields) > 1 and fields[1] and 'NSE:' not in fields[1] else bare
        rows.append({'symbol': sym, 'name': name})
    return rows


def _load_fyers_master() -> list[dict]:
    cache_file = ROOT / 'data' / 'nse_symbols.csv'
    today = now_ist().date()
    # Use a same-day on-disk cache if present.
    if cache_file.exists():
        try:
            mday = date.fromtimestamp(cache_file.stat().st_mtime)
            if mday == today:
                rows = _parse_fyers_master(cache_file.read_text(encoding='utf-8', errors='ignore'))
                if rows:
                    return rows
        except OSError:
            pass
    # Download fresh (best effort).
    try:
        req = urllib.request.Request(_FYERS_NSE_URL, headers={'User-Agent': 'rockstar-radar/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode('utf-8', errors='ignore')
        rows = _parse_fyers_master(text)
        if rows:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(text, encoding='utf-8')
            return rows
    except Exception as e:
        print(f'FYERS symbol master download failed, falling back: {e}')
    return []


def _load_nifty500() -> list[dict]:
    rows = []
    try:
        with (ROOT / 'data' / 'nifty500.csv').open(encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                sym = (r.get('Symbol') or r.get('symbol') or '').strip()
                name = (r.get('Company Name') or r.get('Company') or sym).strip()
                if sym:
                    rows.append({'symbol': f'NSE:{sym}-EQ', 'name': name})
    except Exception:
        rows = []
    return rows


def _load():
    global _CACHE, _CACHE_DAY
    today = now_ist().date()
    if _CACHE is not None and _CACHE_DAY == today:
        return _CACHE
    rows = _load_fyers_master() or _load_nifty500()
    if not rows:
        rows = [{'symbol': f'NSE:{s}-EQ', 'name': n} for s, n in _FALLBACK]
    _CACHE, _CACHE_DAY = rows, today
    return _CACHE


@router.get('/api/symbols')
def search(user: User = Depends(require_user), q: str = '', limit: int = Query(10, ge=1, le=25)):
    q = (q or '').strip().lower()
    if len(q) < 2:
        return {'items': []}
    rows = _load()
    hits = [r for r in rows if q in r['name'].lower() or q in r['symbol'].lower()]
    # Prefer ticker/name prefix matches, then shorter names (closer matches).
    def bare(r):
        return r['symbol'][4:].rsplit('-', 1)[0].lower()
    hits.sort(key=lambda r: (not (bare(r).startswith(q) or r['name'].lower().startswith(q)),
                             len(r['name'])))
    return {'items': hits[:limit]}
