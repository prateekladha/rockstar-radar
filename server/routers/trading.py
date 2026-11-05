"""Trading: place orders, track positions, realised/open P&L. Paper mode by default
(confirmed, never auto-fired). Orders are the source of truth for Journal + Insights."""
from __future__ import annotations
import os
from datetime import datetime, timedelta
from math import floor

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..auth import require_user
from ..db import get_db
from ..models import Order, User

router = APIRouter(prefix='/api', tags=['trading'])

# Demo closed trades so a new user's Journal / Insights / P&L are populated.
_SAMPLE = [
    ('NSE:BHARTIARTL-EQ', 'LONG', 1004.7, 1003.0, 1015.0, 1015.0),
    ('NSE:HINDALCO-EQ', 'SHORT', 556.0, 557.68, 548.8, 548.8),
    ('NSE:TRENT-EQ', 'LONG', 5620.0, 5602.0, 5710.0, 5602.0),
    ('NSE:MCX-EQ', 'LONG', 6420.0, 6395.0, 6560.0, 6560.0),
    ('NSE:SBIN-EQ', 'SHORT', 842.0, 846.0, 820.0, 846.0),
    ('NSE:TATAMOTORS-EQ', 'LONG', 988.0, 984.0, 1008.0, 1008.0),
    ('NSE:INFY-EQ', 'SHORT', 1875.0, 1882.0, 1840.0, 1875.0),
    ('NSE:RELIANCE-EQ', 'LONG', 2940.0, 2930.0, 2985.0, 2985.0),
    ('NSE:AXISBANK-EQ', 'SHORT', 1180.0, 1186.0, 1150.0, 1186.0),
    ('NSE:LT-EQ', 'LONG', 3650.0, 3636.0, 3710.0, 3710.0),
]


def _close_fields(side, entry, stop, exit_price, qty):
    direction = 1 if side == 'LONG' else -1
    pnl = round((exit_price - entry) * qty * direction, 2)
    rps = abs(entry - stop) or 1
    result_r = round((exit_price - entry) * direction / rps, 2)
    return pnl, result_r


def seed_demo_orders(db: Session, user: User) -> None:
    # Only ever populate fake trades for the public marketing demo. Real users see their own
    # paper trades (placed from radar signals) — empty until they take their first trade.
    if os.environ.get('RADAR_DEMO') != '1':
        return
    if db.query(Order).filter_by(user_id=user.id).count() > 0:
        return
    base = datetime.utcnow() - timedelta(days=1)
    for i, (sym, side, entry, stop, tgt, ex) in enumerate(_SAMPLE):
        qty = int(floor(6000 / abs(entry - stop)))
        pnl, r = _close_fields(side, entry, stop, ex, qty)
        db.add(Order(user_id=user.id, created_at=base + timedelta(minutes=i * 13),
                     closed_at=base + timedelta(minutes=i * 13 + 40), symbol=sym, side=side,
                     qty=qty, entry=entry, stop=stop, target=tgt, exit_price=ex,
                     status='closed', mode='paper', source='signal', pnl=pnl, result_r=r,
                     note='Opening-range breakout, retest entry.'))
    db.commit()


def _paginate(q, page, page_size):
    total = q.count()
    items = q.offset((page - 1) * page_size).limit(page_size).all()
    return total, items


@router.post('/orders')
async def place_order(request: Request, user: User = Depends(require_user),
                      db: Session = Depends(get_db)):
    b = await request.json()

    def num(key, required=False):
        v = b.get(key)
        if v in (None, ''):
            if required:
                raise ValueError(f'{key} is required')
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            raise ValueError(f'{key} must be a number')

    symbol = (b.get('symbol') or '').strip()
    side = (b.get('side') or '').upper()
    try:
        qty = int(b.get('qty'))
        entry = num('entry', required=True)
        stop = num('stop')
        target = num('target')
    except (TypeError, ValueError) as e:
        return JSONResponse({'error': str(e) if 'required' in str(e) or 'number' in str(e)
                             else 'Quantity must be a whole number.'}, status_code=400)
    if not symbol:
        return JSONResponse({'error': 'Symbol is required.'}, status_code=400)
    if side not in ('LONG', 'SHORT'):
        return JSONResponse({'error': 'Side must be Long or Short.'}, status_code=400)
    if qty <= 0:
        return JSONResponse({'error': 'Quantity must be greater than 0.'}, status_code=400)
    if entry <= 0 or (stop is not None and stop <= 0) or (target is not None and target <= 0):
        return JSONResponse({'error': 'Prices must be greater than 0.'}, status_code=400)
    o = Order(user_id=user.id, symbol=symbol, side=side, qty=qty, entry=entry,
              stop=stop, target=target, status='open', mode='paper',
              source=b.get('source', 'manual'), note=b.get('note'))
    db.add(o)
    db.commit()
    db.refresh(o)
    return o.public()


@router.post('/orders/{oid}/close')
async def close_order(oid: int, request: Request, user: User = Depends(require_user),
                      db: Session = Depends(get_db)):
    o = db.query(Order).filter_by(id=oid, user_id=user.id, status='open').first()
    if o is None:
        return JSONResponse({'error': 'Open order not found.'}, status_code=404)
    b = await request.json()
    exit_price = float(b.get('exit_price') or o.target or o.entry)
    o.exit_price = exit_price
    o.status = 'closed'
    o.closed_at = datetime.utcnow()
    o.pnl, o.result_r = _close_fields(o.side, o.entry, o.stop or o.entry, exit_price, o.qty)
    db.commit()
    return o.public()


@router.get('/orders')
def list_orders(user: User = Depends(require_user), db: Session = Depends(get_db),
                q: str = '', status: str = '', side: str = '',
                page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    seed_demo_orders(db, user)
    query = db.query(Order).filter_by(user_id=user.id)
    if q:
        query = query.filter(Order.symbol.ilike(f'%{q}%'))
    if status:
        query = query.filter(Order.status == status)
    if side:
        query = query.filter(Order.side == side.upper())
    query = query.order_by(Order.created_at.desc())
    total, items = _paginate(query, page, page_size)
    return {'items': [o.public() for o in items], 'total': total, 'page': page, 'page_size': page_size}


@router.get('/positions')
def positions(user: User = Depends(require_user), db: Session = Depends(get_db)):
    open_orders = db.query(Order).filter_by(user_id=user.id, status='open').order_by(Order.created_at.desc()).all()
    return {'items': [o.public() for o in open_orders], 'total': len(open_orders)}


@router.get('/pnl')
def pnl(user: User = Depends(require_user), db: Session = Depends(get_db)):
    seed_demo_orders(db, user)
    closed = db.query(Order).filter_by(user_id=user.id, status='closed').all()
    realised = round(sum(o.pnl or 0 for o in closed), 2)
    wins = [o for o in closed if (o.pnl or 0) > 0]
    open_count = db.query(Order).filter_by(user_id=user.id, status='open').count()
    return {'realised': realised, 'trades': len(closed), 'open': open_count,
            'wins': len(wins), 'win_rate': round(100 * len(wins) / len(closed), 1) if closed else 0}
