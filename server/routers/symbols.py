"""Symbol search by company NAME or symbol (for order entry / watchlist add)."""
from __future__ import annotations
import csv

from fastapi import APIRouter, Depends, Query

from radar.utils import ROOT

from ..auth import require_user
from ..models import User

router = APIRouter(tags=['symbols'])
_CACHE = None   # list of {symbol, name}
_FALLBACK = [
    ('RELIANCE', 'Reliance Industries'), ('SBIN', 'State Bank of India'),
    ('HDFCBANK', 'HDFC Bank'), ('ICICIBANK', 'ICICI Bank'), ('INFY', 'Infosys'),
    ('TCS', 'Tata Consultancy Services'), ('BHARTIARTL', 'Bharti Airtel'),
    ('HINDALCO', 'Hindalco Industries'), ('TATAMOTORS', 'Tata Motors'),
    ('AXISBANK', 'Axis Bank'), ('LT', 'Larsen & Toubro'), ('ITC', 'ITC'),
    ('MARUTI', 'Maruti Suzuki'), ('SUNPHARMA', 'Sun Pharmaceutical'),
    ('BAJFINANCE', 'Bajaj Finance'), ('KOTAKBANK', 'Kotak Mahindra Bank'),
    ('WIPRO', 'Wipro'), ('ADANIENT', 'Adani Enterprises'), ('TRENT', 'Trent'),
    ('MCX', 'Multi Commodity Exchange'),
]


def _load():
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    rows = []
    csv_path = ROOT / 'data' / 'nifty500.csv'
    try:
        with csv_path.open(encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for r in reader:
                sym = (r.get('Symbol') or r.get('symbol') or '').strip()
                name = (r.get('Company Name') or r.get('Company') or sym).strip()
                if sym:
                    rows.append({'symbol': f'NSE:{sym}-EQ', 'name': name})
    except Exception:
        rows = []
    if not rows:
        rows = [{'symbol': f'NSE:{s}-EQ', 'name': n} for s, n in _FALLBACK]
    _CACHE = rows
    return _CACHE


@router.get('/api/symbols')
def search(user: User = Depends(require_user), q: str = '', limit: int = Query(10, ge=1, le=25)):
    q = (q or '').strip().lower()
    if len(q) < 2:
        return {'items': []}
    hits = [r for r in _load() if q in r['name'].lower() or q in r['symbol'].lower()]
    # exact/prefix matches first
    hits.sort(key=lambda r: (not r['name'].lower().startswith(q), r['name']))
    return {'items': hits[:limit]}
