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
from ..models import BrokerConnection, Order, User
from ..watchpins import bare as _bare

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
    # Trading requires the user's OWN broker — never a teammate's/admin's shared broker.
    own = (db.query(BrokerConnection)
           .filter(BrokerConnection.user_id == user.id, BrokerConnection.broker == 'fyers',
                   BrokerConnection.app_id.isnot(None), BrokerConnection.secret_enc.isnot(None))
           .first())
    if own is None:
        return JSONResponse({'error': 'Connect your own broker before placing trades.',
                             'need_broker': True}, status_code=403)

    # Trading mode is a HOUSEHOLD setting (admin-controlled), not a per-order choice.
    from ..models import Household
    hh = db.get(Household, user.household_id)
    mode = (hh.trading_mode if hh else 'paper') or 'paper'
    order_type = (b.get('order_type') or 'limit').lower()

    from radar.utils import load_config
    cfg = load_config()
    sdata = (user.settings.data if user.settings else {}) or {}
    risk_pct = float(sdata.get('risk_pct', cfg.get('risk_pct', 0)) or 0)

    broker_oid = None
    if mode == 'live':
        from .. import scanners
        from ..broker_orders import OrderError, fetch_funds, place_live_order
        from ..crypto import decrypt
        if not own.token_enc or not scanners._token_is_fresh_today(own):
            return JSONResponse({'error': 'Log in to your broker for today before placing a live '
                                 'order.', 'need_login': True}, status_code=403)
        # Live capital comes from the BROKER (not Settings). Insufficient funds -> clear message,
        # never a silent fall back to paper.
        token = decrypt(own.token_enc) or ''
        try:
            capital = fetch_funds(own.app_id, token)
        except OrderError as e:
            return JSONResponse({'error': 'Could not read your broker balance to place a live '
                                 'order: ' + str(e)}, status_code=400)
        cost = entry * qty
        if capital <= 0 or cost > capital + 1e-6:
            return JSONResponse({'error': f'Insufficient broker balance for this live trade. Needs '
                                 f'~₹{round(cost):,} but your available balance is ₹{round(capital):,}. '
                                 'Add funds or reduce the quantity.'}, status_code=400)
        max_risk = capital * risk_pct / 100 if risk_pct else 0
        if stop and max_risk and abs(entry - stop) * qty > max_risk + 1e-6:
            return JSONResponse({'error': f'This trade risks ₹{round(abs(entry - stop) * qty):,} — '
                                 f'over your limit of ₹{round(max_risk):,} ({risk_pct}% of your broker '
                                 f'balance ₹{round(capital):,}). Lower the quantity or tighten the '
                                 'stop.'}, status_code=400)
        try:
            broker_oid = place_live_order(own.app_id, token, symbol=symbol, side=side, qty=qty,
                                          entry=entry, stop=stop, target=target, order_type=order_type)
        except OrderError as e:
            return JSONResponse({'error': 'Broker rejected the order: ' + str(e)}, status_code=400)
    else:
        # Paper risk ceiling uses the user's configured capital (Settings, else config).
        capital = float(sdata.get('capital_inr', cfg.get('capital_inr', 0)) or 0)
        max_risk = capital * risk_pct / 100 if (capital and risk_pct) else 0
        if stop and max_risk and abs(entry - stop) * qty > max_risk + 1e-6:
            return JSONResponse({'error': f'This trade risks ₹{round(abs(entry - stop) * qty):,} — '
                                 f'over your limit of ₹{round(max_risk):,} ({risk_pct}% of '
                                 f'₹{round(capital):,}). Lower the quantity or tighten the stop.'},
                                status_code=400)

    # New orders start as PENDING (working). They become `open` only when actually filled — paper by
    # the live feed (below / by the engine), live by broker sync. Only truly-closed orders book P&L.
    o = Order(user_id=user.id, symbol=symbol, side=side, qty=qty, entry=entry,
              stop=stop, target=target, status='pending', order_type=order_type, mode=mode,
              broker_order_id=broker_oid, source=b.get('source', 'manual'), note=b.get('note'))
    db.add(o)
    db.commit()
    db.refresh(o)
    # Paper: if the market has already traded through the entry, fill it immediately so it shows as
    # an open position at once (otherwise the engine fills it on its next pass, within seconds).
    if mode == 'paper':
        try:
            from ..order_engine import _price_map, process_paper
            px = _price_map(db, user).get(_bare(symbol))
            if px is not None and process_paper(o, px):
                db.commit()
                db.refresh(o)
        except Exception as e:
            print(f'immediate paper fill skipped: {e}')
    return o.public()


@router.post('/orders/{oid}/close')
async def close_order(oid: int, request: Request, user: User = Depends(require_user),
                      db: Session = Depends(get_db)):
    from ..order_engine import _price_map, mark_closed
    o = db.query(Order).filter_by(id=oid, user_id=user.id).first()
    if o is None:
        return JSONResponse({'error': 'Order not found.'}, status_code=404)
    if o.status != 'open':
        return JSONResponse({'error': 'Only a filled, open position can be closed. A working order '
                             'that has not filled yet should be cancelled instead.'}, status_code=400)
    b = await request.json()
    live_px = _price_map(db, user).get(_bare(o.symbol))
    # Live: square off at the broker (user-initiated — the only place we fire an exit order).
    if o.mode == 'live':
        from .. import scanners
        from ..broker_orders import OrderError, square_off_live
        from ..crypto import decrypt
        own = scanners._own_broker(db, user)
        if own is None or not own.token_enc or not scanners._token_is_fresh_today(own):
            return JSONResponse({'error': 'Log in to your broker for today to close this live '
                                 'position.', 'need_login': True}, status_code=403)
        try:
            square_off_live(own.app_id, decrypt(own.token_enc) or '', symbol=o.symbol,
                            side=o.side, qty=o.qty)
        except OrderError as e:
            return JSONResponse({'error': 'Broker rejected the square-off: ' + str(e)}, status_code=400)
    exit_price = float(b.get('exit_price') or live_px or o.target or o.fill_price or o.entry)
    mark_closed(o, exit_price)
    db.commit()
    return o.public()


@router.post('/orders/{oid}/cancel')
async def cancel_order(oid: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    o = db.query(Order).filter_by(id=oid, user_id=user.id, status='pending').first()
    if o is None:
        return JSONResponse({'error': 'No working order to cancel (it may already be filled or '
                             'closed).'}, status_code=404)
    if o.mode == 'live' and o.broker_order_id:
        from .. import scanners
        from ..broker_orders import OrderError, cancel_live_order
        from ..crypto import decrypt
        own = scanners._own_broker(db, user)
        if own and own.token_enc and scanners._token_is_fresh_today(own):
            try:
                cancel_live_order(own.app_id, decrypt(own.token_enc) or '', o.broker_order_id)
            except OrderError as e:
                return JSONResponse({'error': 'Broker rejected the cancel: ' + str(e)}, status_code=400)
    o.status = 'cancelled'
    o.closed_at = datetime.utcnow()
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
    """Filled, open positions with self-updating (unrealised) P&L from the live feed."""
    from ..order_engine import _price_map
    pm = _price_map(db, user)
    open_orders = (db.query(Order).filter_by(user_id=user.id, status='open')
                   .order_by(Order.created_at.desc()).all())
    items = [o.public(last_price=pm.get(_bare(o.symbol))) for o in open_orders]
    running = round(sum((i['unrealized'] or 0) for i in items), 2)
    return {'items': items, 'total': len(items), 'running_pnl': running}


@router.get('/working-orders')
def working_orders(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """Working (pending, not-yet-filled) orders — these are cancellable, not closable."""
    rows = (db.query(Order).filter_by(user_id=user.id, status='pending')
            .order_by(Order.created_at.desc()).all())
    return {'items': [o.public() for o in rows], 'total': len(rows)}


@router.get('/pnl')
def pnl(user: User = Depends(require_user), db: Session = Depends(get_db)):
    seed_demo_orders(db, user)
    # Realised P&L counts ONLY genuinely-closed trades (entered AND exited) — never working/pending
    # or cancelled orders.
    closed = db.query(Order).filter_by(user_id=user.id, status='closed').all()
    realised = round(sum(o.pnl or 0 for o in closed), 2)
    wins = [o for o in closed if (o.pnl or 0) > 0]
    open_count = db.query(Order).filter_by(user_id=user.id, status='open').count()
    working = db.query(Order).filter_by(user_id=user.id, status='pending').count()
    from ..order_engine import _price_map
    pm = _price_map(db, user)
    open_orders = db.query(Order).filter_by(user_id=user.id, status='open').all()
    running = round(sum((o.public(last_price=pm.get(_bare(o.symbol)))['unrealized'] or 0)
                        for o in open_orders), 2)
    return {'realised': realised, 'trades': len(closed), 'open': open_count, 'working': working,
            'running_pnl': running, 'wins': len(wins),
            'win_rate': round(100 * len(wins) / len(closed), 1) if closed else 0}
