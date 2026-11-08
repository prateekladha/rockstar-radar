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


@router.get('/settings')
def household_settings(user: User = Depends(require_user), db: Session = Depends(get_db)):
    hh = db.get(Household, user.household_id)
    return {'can_manage': user.role in MANAGERS, **(hh.settings_public() if hh else
            {'trading_mode': 'paper', 'auto_paper_trade': False})}


@router.patch('/settings')
async def set_household_settings(request: Request, user: User = Depends(require_user),
                                db: Session = Depends(get_db)):
    if user.role not in MANAGERS:
        return JSONResponse({'error': 'Only an owner/admin can change trading settings.'},
                            status_code=403)
    b = await request.json()
    hh = db.get(Household, user.household_id)
    if 'trading_mode' in b:
        hh.trading_mode = 'live' if b.get('trading_mode') == 'live' else 'paper'
    if 'auto_paper_trade' in b:
        hh.auto_paper_trade = 1 if b.get('auto_paper_trade') else 0
    db.commit()
    return {'can_manage': True, **hh.settings_public()}


@router.get('')
def family(user: User = Depends(require_user), db: Session = Depends(get_db)):
    members = db.query(User).filter_by(household_id=user.household_id).all()
    hh = db.get(Household, user.household_id)
    return {
        'household': hh.name if hh else 'Household',
        'can_manage': user.role in MANAGERS,
        'members': [{'id': m.id, 'email': m.email, 'name': m.display_name, 'role': m.role,
                     'pending': m.google_sub is None, 'is_me': m.id == user.id}
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
async def set_role(mid: int, request: Request, user: User = Depends(require_user),
                   db: Session = Depends(get_db)):
    if user.role not in MANAGERS:
        return JSONResponse({'error': 'Only an owner/admin can change roles.'}, status_code=403)
    role = (await request.json()).get('role')
    if role not in ASSIGNABLE:
        return JSONResponse({'error': 'Invalid role.'}, status_code=400)
    m = db.query(User).filter_by(id=mid, household_id=user.household_id).first()
    if m is None:
        return JSONResponse({'error': 'Member not found.'}, status_code=404)
    admins = db.query(User).filter_by(household_id=user.household_id, role='admin').count()
    if m.role == 'admin' and role != 'admin' and admins <= 1:
        return JSONResponse({'error': 'The account must keep at least one admin.'}, status_code=400)
    m.role = role
    db.commit()
    return {'ok': True}


@router.delete('/member/{mid}')
def remove_member(mid: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    if user.role not in MANAGERS:
        return JSONResponse({'error': 'Only an owner/admin can remove members.'}, status_code=403)
    m = db.query(User).filter_by(id=mid, household_id=user.household_id).first()
    if m is None:
        return JSONResponse({'error': 'Member not found.'}, status_code=404)
    if m.id == user.id:
        return JSONResponse({'error': 'You can\'t remove yourself.'}, status_code=400)
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
