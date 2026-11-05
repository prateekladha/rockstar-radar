"""Smart watchlist — the daily auto-shortlist of intraday stocks with long/short plans."""
from __future__ import annotations
import os
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from radar.utils import now_ist

from ..auth import require_admin, require_user
from ..db import get_db
from ..models import SmartPick, User

router = APIRouter(prefix='/api/smart-watchlist', tags=['watchlist'])


def _plan(entry, sl, inval, targets, note):
    return {'entry': entry, 'sl': sl, 'invalidation': inval, 'targets': targets, 'note': note}


_DEMO = [
    ('AUROPHARMA', 'Aurobindo Pharma', 'both', True,
     _plan('1,740.50–1,742', '1,734', '1,691', ['1,756', '1,775', '1,800'], 'Result-acceptance long; failure short available.'),
     _plan('1,672.50–1,673.20', '1,682', '1,740.50', ['1,655', '1,635', '1,610'], 'Bearish on rejection of highs.')),
    ('BSE', 'BSE Ltd', 'both', True,
     _plan('3,704–3,707', '3,683', '3,576', ['3,741', '3,800', '3,900'], 'Strong market-wide positive watch; high-volatility two-way.'),
     _plan('3,562–3,563.50', '3,578', '3,703', ['3,525', '3,474', '3,400'], 'Short if it loses the gap.')),
    ('APOLLOHOSP', 'Apollo Hospitals', 'long', True,
     _plan('8,713–8,720', '8,675', '8,429', ['8,826', '8,950', '9,070'], 'Preferred positive-result watch; failure short available.'), None),
    ('PIIND', 'PI Industries', 'short', False, None,
     _plan('2,149–2,150', '2,162', '2,238', ['2,124', '2,098', '2,050'], 'Result-rejection short; bad-news-absorption long available.')),
    ('NYKAA', 'FSN E-Commerce', 'long', False,
     _plan('360.10–360.40', '357.50', '342.05', ['364.60', '373.60', '380'], 'Positive-result watch; failure short available.'), None),
    ('SCI', 'Shipping Corp', 'long', False,
     _plan('274.05–274.30', '271.50', '257', ['278.50', '287', '295'], 'Strong positive watch; extended-price caution.'), None),
    ('DABUR', 'Dabur India', 'both', False,
     _plan('399.20–399.50', '397', '382.55', ['403.30', '411.60', '420'], 'Two-way watch; short if opening is extended.'),
     _plan('386.50–386.70', '390', '399.15', ['378.40', '374.25', '365'], 'Gap-failure short.')),
]


def seed_demo_picks(db: Session, user: User) -> None:
    # Demo picks are for the public marketing demo only. Real users get picks generated from the
    # live scanner during market hours (empty before the open).
    if os.environ.get('RADAR_DEMO') != '1':
        return
    today = now_ist().date().isoformat()
    if db.query(SmartPick).filter_by(user_id=user.id, day=today).count() > 0:
        return
    for sym, name, bias, focus, lp, sp in _DEMO:
        db.add(SmartPick(user_id=user.id, household_id=user.household_id, day=today, symbol=sym,
                         name=name, bias=bias, focus=1 if focus else 0, long_plan=lp, short_plan=sp))
    db.commit()


def _name_from_symbol(sym: str) -> str:
    return (sym or '').split(':')[-1].replace('-EQ', '').replace('-BE', '')


def _r(x):
    return round(x, 2) if isinstance(x, (int, float)) else x


def _or_plans(orh: float, orl: float):
    """Long/short plans derived from the opening range (OR high/low), mirroring the ORB setup."""
    rng = orh - orl
    if rng <= 0:
        return None, None
    long_plan = {'entry': str(_r(orh)), 'sl': str(_r(orl)),
                 'invalidation': f'5-min close back below {_r(orl)}',
                 'targets': [str(_r(orh + rng)), str(_r(orh + 2 * rng))],
                 'note': 'Long on a confirmed break & hold above the opening-range high.'}
    short_plan = {'entry': str(_r(orl)), 'sl': str(_r(orh)),
                  'invalidation': f'5-min close back above {_r(orh)}',
                  'targets': [str(_r(orl - rng)), str(_r(orl - 2 * rng))],
                  'note': 'Short on a confirmed break & hold below the opening-range low.'}
    return long_plan, short_plan


# A pick is only meaningful once the stock is actually setting up — not merely "has an opening
# range". Require an actionable state or a real score so the shortlist isn't the whole universe.
_PICK_STATES = {'CONFIRMED', 'RETEST_READY', 'BREAKOUT_PENDING', 'READY', 'WATCH'}


def _bias_for(r: dict) -> str:
    """Directional bias from the engine's side, else from where price sits vs the opening range."""
    side = (r.get('side') or '').upper()
    if side == 'LONG':
        return 'long'
    if side == 'SHORT':
        return 'short'
    px, orh, orl = r.get('price'), r.get('orh'), r.get('orl')
    if px and orh and px > orh:
        return 'long'
    if px and orl and px < orl:
        return 'short'
    return 'both'


def generate_smart_picks(db: Session, user: User, state: dict) -> None:
    """Rebuild this user's AUTO picks from their effective feed — only symbols genuinely setting up
    (actionable state or a real score), ranked by score. Manual picks (source='manual') kept.
    If nothing qualifies (e.g. pre-open or after close), today's auto picks are cleared."""
    rows = [r for r in (state.get('all') or [])
            if r.get('orh') and r.get('orl')
            and (r.get('state') in _PICK_STATES or (r.get('score') or 0) > 0)]
    rows.sort(key=lambda r: -(r.get('score') or 0))
    today = now_ist().date().isoformat()
    db.query(SmartPick).filter_by(user_id=user.id, day=today, source='auto').delete()
    for i, r in enumerate(rows[:20]):
        lp, sp = _or_plans(r['orh'], r['orl'])
        bias = _bias_for(r)
        nm = _name_from_symbol(r['symbol'])
        db.add(SmartPick(user_id=user.id, household_id=user.household_id, day=today, symbol=nm,
                         name=nm, bias=bias, focus=1 if i < 5 else 0, source='auto',
                         long_plan=lp if bias in ('long', 'both') else None,
                         short_plan=sp if bias in ('short', 'both') else None,
                         note=r.get('reason')))
    db.commit()


@router.get('')
def list_picks(user: User = Depends(require_user), db: Session = Depends(get_db),
               q: str = '', bias: str = '', page: int = Query(1, ge=1),
               page_size: int = Query(20, ge=1, le=100)):
    seed_demo_picks(db, user)
    # Refresh today's shortlist from the user's effective feed (their own broker, else shared).
    try:
        from .. import scanners
        state = scanners.radar_state(db, user)
        if state.get('data_mode') == 'live':
            generate_smart_picks(db, user, state)
    except Exception as e:
        print(f'smart-pick generation skipped: {e}')
    today = now_ist().date().isoformat()
    query = db.query(SmartPick).filter_by(user_id=user.id, day=today)
    if q:
        query = query.filter(SmartPick.symbol.ilike(f'%{q}%'))
    if bias:
        query = query.filter(SmartPick.bias == bias)
    query = query.order_by(SmartPick.focus.desc(), SmartPick.symbol)
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return {'items': [p.public() for p in items], 'total': total, 'page': page,
            'page_size': page_size, 'day': today}


@router.post('')
async def add_pick(request: Request, admin: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    b = await request.json()
    if not b.get('symbol'):
        return JSONResponse({'error': 'Symbol is required.'}, status_code=400)
    db.add(SmartPick(user_id=admin.id, household_id=admin.household_id, day=now_ist().date().isoformat(),
                     symbol=b['symbol'].upper(), name=b.get('name'), bias=b.get('bias', 'both'),
                     focus=1 if b.get('focus') else 0, source='manual',
                     long_plan=b.get('long_plan'), short_plan=b.get('short_plan'), note=b.get('note')))
    db.commit()
    return {'ok': True}
