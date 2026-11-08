"""Insights + audit CSV, computed from the user's real trades (Orders)."""
from __future__ import annotations
import csv
import io

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from datetime import timezone

from fastapi import Query

from radar.utils import IST, now_ist

from ..auth import require_user
from ..db import get_db
from ..models import Order, SignalLog, User
from .trading import compute_pnl, seed_demo_orders

router = APIRouter(tags=['insights'])


@router.get('/api/insights')
def insights(user: User = Depends(require_user), db: Session = Depends(get_db), mode: str = ''):
    seed_demo_orders(db, user)
    q = db.query(Order).filter_by(user_id=user.id, status='closed')
    # Keep paper, live and simulation separate (matches the global Paper/Actual toggle).
    if user.sim_enabled:
        q = q.filter(Order.sim == 1)
    else:
        q = q.filter(Order.sim == 0)
        if mode in ('paper', 'live'):
            q = q.filter(Order.mode == mode)
    closed = q.order_by(Order.closed_at).all()
    rs = [o.result_r or 0 for o in closed]
    wins = [o for o in closed if (o.pnl or 0) > 0]

    def by_side(side):
        c = [o for o in closed if o.side == side]
        w = [o for o in c if (o.pnl or 0) > 0]
        return {'total': len(c), 'win_rate': round(100 * len(w) / len(c), 1) if c else 0,
                'r': round(sum(o.result_r or 0 for o in c), 2)}

    equity, cum = [], 0.0
    for o in closed:
        cum += o.result_r or 0
        equity.append({'t': o.closed_at.isoformat() if o.closed_at else None,
                       'symbol': o.symbol, 'r': round(cum, 2)})

    # Daily realised P&L (₹) by the trade's IST close date, for the daily bar chart.
    from collections import defaultdict
    from datetime import timezone
    from radar.utils import IST
    daily = defaultdict(float)
    for o in closed:
        if o.closed_at is None or o.pnl is None:
            continue
        d = o.closed_at if o.closed_at.tzinfo else o.closed_at.replace(tzinfo=timezone.utc)
        daily[d.astimezone(IST).date().isoformat()] += o.pnl
    daily_pnl = [{'day': k, 'pnl': round(v, 2)} for k, v in sorted(daily.items())]

    best = max(closed, key=lambda o: o.result_r or 0, default=None)
    worst = min(closed, key=lambda o: o.result_r or 0, default=None)
    # Headline P&L uses the SAME Running/Realised rule as the Trades page (realisation only after the
    # session ends; sim is perpetual so nothing is realised) — so the two pages can never disagree.
    pnl = compute_pnl(db, user, mode)
    return {
        'daily_pnl': daily_pnl,
        'trades': len(closed),
        'wins': len(wins), 'losses': len(closed) - len(wins),
        'win_rate': round(100 * len(wins) / len(closed), 1) if closed else 0,
        'avg_r': round(sum(rs) / len(rs), 2) if rs else 0,
        'expectancy_r': round(sum(rs) / len(closed), 2) if closed else 0,
        'total_r': round(sum(rs), 2),
        'realised': pnl['realised'], 'running_pnl': pnl['running_pnl'], 'sim': pnl['sim'],
        'long': by_side('LONG'), 'short': by_side('SHORT'),
        'equity': equity,
        'best': {'symbol': best.symbol, 'r': best.result_r} if best else None,
        'worst': {'symbol': worst.symbol, 'r': worst.result_r} if worst else None,
    }


def _acted_symbols(db, user_id, day):
    """Symbols the user placed an order on during `day` (IST) — to mark opportunities as acted."""
    orders = db.query(Order).filter_by(user_id=user_id).all()
    acted = set()
    for o in orders:
        # Order.created_at is naive UTC; compare its IST calendar day.
        ts = o.created_at
        if ts is None:
            continue
        try:
            d = (ts.replace(tzinfo=timezone.utc).astimezone(IST)).date().isoformat()
        except Exception:
            d = None
        if d == day:
            acted.add((o.symbol or '').split(':')[-1].replace('-EQ', ''))
    return acted


@router.get('/api/journal')
def journal(user: User = Depends(require_user), db: Session = Depends(get_db),
            day: str = '', q: str = '', side: str = '',
            page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    """The day's opportunities (what the radar flagged) + whether the user acted on each."""
    day = day or now_ist().date().isoformat()
    query = db.query(SignalLog).filter_by(user_id=user.id, day=day)
    if q:
        query = query.filter(SignalLog.symbol.ilike(f'%{q}%'))
    if side:
        query = query.filter(SignalLog.side == side.upper())
    query = query.order_by(SignalLog.score.desc(), SignalLog.symbol)
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    acted = _acted_symbols(db, user.id, day)

    def row(s):
        sym_short = (s.symbol or '').split(':')[-1].replace('-EQ', '')
        return {'id': s.id, 'ts': s.ts.isoformat() if s.ts else None, 'symbol': s.symbol,
                'side': s.side, 'state': s.state, 'score': s.score, 'entry': s.entry,
                'stop': s.stop, 'target': s.target, 'net_rr': s.net_rr, 'rvol': s.rvol,
                'provisional': bool(s.provisional), 'note': s.note, 'outcome': s.outcome,
                'timeline': s.timeline or [], 'acted': sym_short in acted}

    days = [d[0] for d in db.query(SignalLog.day).filter_by(user_id=user.id)
            .distinct().order_by(SignalLog.day.desc()).limit(30).all() if d[0]]
    return {'items': [row(s) for s in items], 'total': total, 'page': page,
            'page_size': page_size, 'day': day, 'days': days}


@router.get('/api/audit.csv')
def audit_csv(user: User = Depends(require_user), db: Session = Depends(get_db)):
    seed_demo_orders(db, user)
    rows = db.query(Order).filter_by(user_id=user.id).order_by(Order.created_at.desc()).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['placed', 'closed', 'symbol', 'side', 'qty', 'entry', 'stop', 'target',
                'exit', 'status', 'mode', 'pnl', 'result_r'])
    for o in rows:
        w.writerow([o.created_at, o.closed_at, o.symbol, o.side, o.qty, o.entry, o.stop,
                    o.target, o.exit_price, o.status, o.mode, o.pnl, o.result_r])
    return StreamingResponse(iter([buf.getvalue()]), media_type='text/csv',
                             headers={'Content-Disposition': 'attachment; filename=rockstar_trades.csv'})
