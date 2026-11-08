"""Household (family/firm) members + RBAC. Owner/admin manage members & roles."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..auth import require_user
from ..db import get_db
from ..models import (AlertConfig, BrokerConnection, Household, Order, Settings, SignalLog,
                      SmartPick, SupportMessage, User, Watchlist)

router = APIRouter(prefix='/api/family', tags=['family'])
MANAGERS = {'admin'}
ASSIGNABLE = {'admin', 'trader'}


def _owner_id(db: Session, hh: Household) -> int | None:
    """The household owner — its creator. Backfills legacy households (owner = earliest member)."""
    if hh is None:
        return None
    if hh.owner_user_id:
        return hh.owner_user_id
    first = (db.query(User).filter_by(household_id=hh.id).order_by(User.id.asc()).first())
    if first:
        hh.owner_user_id = first.id
        db.commit()
        return first.id
    return None


@router.get('')
def family(user: User = Depends(require_user), db: Session = Depends(get_db)):
    members = db.query(User).filter_by(household_id=user.household_id).all()
    hh = db.get(Household, user.household_id)
    owner_id = _owner_id(db, hh)
    return {
        'household': hh.name if hh else 'Household',
        'can_manage': user.role in MANAGERS,
        'is_owner': user.id == owner_id,
        'members': [{'id': m.id, 'email': m.email, 'name': m.display_name, 'role': m.role,
                     'pending': m.google_sub is None, 'is_me': m.id == user.id,
                     'is_owner': m.id == owner_id,
                     'trading_mode': m.trading_mode or 'paper',
                     'auto_paper_trade': bool(m.auto_paper_trade)}
                    for m in members],
    }


@router.post('/invite')
async def invite(request: Request, user: User = Depends(require_user),
                 db: Session = Depends(get_db)):
    if user.role not in MANAGERS:
        return JSONResponse({'error': 'Only an owner/admin can invite members.'}, status_code=403)
    b = await request.json()
    email = (b.get('email') or '').lower().strip()
    role = b.get('role', 'trader')
    if '@' not in email:
        return JSONResponse({'error': 'A valid email is required.'}, status_code=400)
    if role not in ASSIGNABLE:
        role = 'trader'
    if db.query(User).filter_by(email=email).first():
        return JSONResponse({'error': 'That email already has an account.'}, status_code=400)
    # Pre-create the member in this household; they attach on first Google login (same email).
    db.add(User(household_id=user.household_id, email=email,
                name=email.split('@')[0], role=role))
    db.commit()
    return {'ok': True}


@router.patch('/member/{mid}')
async def set_member(mid: int, request: Request, user: User = Depends(require_user),
                     db: Session = Depends(get_db)):
    """Admin updates a member's role and/or trading flags (paper/live, auto paper-trade)."""
    if user.role not in MANAGERS:
        return JSONResponse({'error': 'Only an owner/admin can manage members.'}, status_code=403)
    b = await request.json()
    m = db.query(User).filter_by(id=mid, household_id=user.household_id).first()
    if m is None:
        return JSONResponse({'error': 'Member not found.'}, status_code=404)
    hh = db.get(Household, user.household_id)
    owner_id = _owner_id(db, hh)

    if 'role' in b:
        role = b.get('role')
        if role not in ASSIGNABLE:
            return JSONResponse({'error': 'Invalid role.'}, status_code=400)
        # The owner can never be demoted (only they created the household).
        if m.id == owner_id and role != 'admin':
            return JSONResponse({'error': 'The owner\'s role can\'t be changed.'}, status_code=400)
        admins = db.query(User).filter_by(household_id=user.household_id, role='admin').count()
        if m.role == 'admin' and role != 'admin' and admins <= 1:
            return JSONResponse({'error': 'The account must keep at least one admin.'}, status_code=400)
        m.role = role
    if 'trading_mode' in b:
        m.trading_mode = 'live' if b.get('trading_mode') == 'live' else 'paper'
    if 'auto_paper_trade' in b:
        m.auto_paper_trade = 1 if b.get('auto_paper_trade') else 0
    db.commit()
    return {'ok': True, 'id': m.id, 'role': m.role, 'trading_mode': m.trading_mode or 'paper',
            'auto_paper_trade': bool(m.auto_paper_trade)}


@router.delete('/member/{mid}')
def remove_member(mid: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if user.role not in MANAGERS:
        return JSONResponse({'error': 'Only an owner/admin can remove members.'}, status_code=403)
    m = db.query(User).filter_by(id=mid, household_id=user.household_id).first()
    if m is None:
        return JSONResponse({'error': 'Member not found.'}, status_code=404)
    if m.id == user.id:
        return JSONResponse({'error': 'You can\'t remove yourself.'}, status_code=400)
    if m.id == _owner_id(db, db.get(Household, user.household_id)):
        return JSONResponse({'error': 'The household owner can\'t be removed.'}, status_code=400)
    # Only guard against orphaning the household of its last admin. A pending invite or any
    # non-last admin is freely removable by another admin.
    if m.role == 'admin':
        admins = db.query(User).filter_by(household_id=user.household_id, role='admin').count()
        if admins <= 1:
            return JSONResponse({'error': 'This is the only admin. Make someone else an admin '
                                 'first, then remove this one.'}, status_code=400)
    # Remove dependent rows first — Postgres enforces the foreign keys, so a bare user delete would
    # fail (this is why removal "silently" failed on prod). Relationship cascades cover
    # Watchlist/Settings/BrokerConnection; the rest we clear explicitly.
    for Model in (Order, SmartPick, SignalLog, SupportMessage, AlertConfig, BrokerConnection,
                  Settings, Watchlist):
        db.query(Model).filter_by(user_id=m.id).delete(synchronize_session=False)
    db.delete(m)
    db.commit()
    return {'ok': True}
