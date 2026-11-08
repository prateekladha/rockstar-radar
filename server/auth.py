"""Authentication — Google Sign-In (OAuth/OIDC) + server sessions.

No OTP/SMS. A DEV_LOGIN fallback lets us run and test the whole app before the Google OAuth
client is configured. First login for a new email creates a Household (that user becomes owner).
"""
from __future__ import annotations
import os
from datetime import datetime

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import get_db
from .models import Household, User

GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '').strip()
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '').strip()
DEV_LOGIN = os.environ.get('DEV_LOGIN') == '1'

oauth = OAuth()


def register_google() -> bool:
    if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
        oauth.register(
            name='google',
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid email profile'},
        )
        return True
    return False


def google_enabled() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def upsert_user(db: Session, info: dict) -> User:
    """Create or update a user from an OIDC userinfo dict ({sub,email,name,picture})."""
    sub = info.get('sub')
    email = (info.get('email') or '').lower()
    if not email:
        raise ValueError('No email in identity profile')
    user = db.query(User).filter(
        (User.google_sub == sub) | (User.email == email)).first()
    # A real first-time signup: brand-new user, or an invited member activating (no google_sub yet).
    is_new_signup = user is None or user.google_sub is None
    given = (info.get('given_name') or '').strip()
    family = (info.get('family_name') or '').strip()
    if not given and info.get('name'):
        parts = info['name'].split()
        given, family = parts[0], ' '.join(parts[1:])
    if user is None:
        hh = Household(name=(info.get('name') or email.split('@')[0]) + "'s Household")
        db.add(hh)
        db.flush()
        user = User(household_id=hh.id, google_sub=sub, email=email,
                    name=info.get('name'), first_name=given or None, last_name=family or None,
                    picture=info.get('picture'), role='admin')   # first user of a household = admin
        db.add(user)
        db.flush()
        hh.owner_user_id = user.id   # the creator is the owner (protected from demotion/removal)
    else:
        if sub:
            user.google_sub = sub
        user.name = info.get('name') or user.name
        user.first_name = user.first_name or given or None
        user.last_name = user.last_name or family or None
        user.picture = info.get('picture') or user.picture
        user.last_login = datetime.utcnow()
    db.commit()
    db.refresh(user)
    if is_new_signup:
        try:
            from .notifications import notify_new_signup
            notify_new_signup(user)
        except Exception as e:
            print(f'signup notify skipped: {e}')
    return user


def current_user(request: Request, db: Session = Depends(get_db)):
    uid = request.session.get('user_id')
    return db.get(User, uid) if uid else None


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = current_user(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail='Not authenticated')
    return user


def require_admin(request: Request, db: Session = Depends(get_db)) -> User:
    user = require_user(request, db)
    if user.role != 'admin':
        raise HTTPException(status_code=403, detail='Admin only')
    return user
