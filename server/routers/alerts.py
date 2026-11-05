"""Per-user alert rules + channels (Telegram token encrypted)."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from radar.notify import send_telegram

from ..auth import require_user
from ..crypto import decrypt, encrypt
from ..db import get_db
from ..models import AlertConfig, User

router = APIRouter(prefix='/api/alerts', tags=['alerts'])


def _config(db: Session, user: User) -> AlertConfig:
    c = db.query(AlertConfig).filter_by(user_id=user.id).first()
    if c is None:
        c = AlertConfig(user_id=user.id)
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


@router.get('')
def get_alerts(user: User = Depends(require_user), db: Session = Depends(get_db)):
    c = _config(db, user)
    return {'enabled': bool(c.enabled), 'states': c.states or [], 'min_score': c.min_score,
            'channels': c.channels or {}, 'telegram_chat_id': c.telegram_chat_id or '',
            'has_telegram_token': bool(c.telegram_token_enc),
            'quiet_from': c.quiet_from or '', 'quiet_to': c.quiet_to or ''}


@router.put('')
async def put_alerts(request: Request, user: User = Depends(require_user),
                     db: Session = Depends(get_db)):
    b = await request.json()
    c = _config(db, user)
    c.enabled = 1 if b.get('enabled', True) else 0
    if 'states' in b:
        c.states = b['states']
    if 'min_score' in b:
        c.min_score = int(b['min_score'] or 0)
    if 'channels' in b:
        c.channels = b['channels']
    if 'telegram_chat_id' in b:
        c.telegram_chat_id = (b['telegram_chat_id'] or '').strip()
    if b.get('telegram_token'):
        c.telegram_token_enc = encrypt(b['telegram_token'].strip())
    c.quiet_from = (b.get('quiet_from') or '').strip() or None
    c.quiet_to = (b.get('quiet_to') or '').strip() or None
    db.commit()
    return {'ok': True}


@router.post('/test')
def test_alert(user: User = Depends(require_user), db: Session = Depends(get_db)):
    c = _config(db, user)
    token = decrypt(c.telegram_token_enc)
    if not token or not c.telegram_chat_id:
        return {'ok': False, 'message': 'Set your Telegram bot token and chat id first.'}
    return send_telegram('✅ Rockstar Radar — your alerts are connected.',
                         token=token, chat_id=c.telegram_chat_id)
