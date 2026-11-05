"""Household (family/firm) members + RBAC. Owner/admin manage members & roles."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..auth import require_user
from ..db import get_db
from ..models import Household, User

router = APIRouter(prefix='/api/family', tags=['family'])
MANAGERS = {'admin'}
ASSIGNABLE = {'admin', 'trader'}


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
    if m and m.id != user.id and m.role != 'admin':
        db.delete(m)
        db.commit()
    return {'ok': True}
