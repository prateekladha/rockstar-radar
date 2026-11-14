"""Per-user alert rules + channels (Telegram token encrypted)."""
from __future__ import annotations
from datetime import timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from radar.notify import get_telegram_chats, send_telegram
from radar.utils import IST

from ..auth import require_user
from ..crypto import decrypt, encrypt
from ..db import get_db
from ..models import AlertConfig, AlertDelivery, User

router = APIRouter(prefix='/api/alerts', tags=['alerts'])

# You only alert on signals that mean "a trade is setting up" — never on negative outcomes
# (RETRACTED/FAILED are not actionable, so they're not offered or stored).
ALERT_STATES = ['CONFIRMED', 'RETEST_READY', 'BREAKOUT_PENDING', 'READY']


def _clean_states(states) -> list[str]:
    seen = [s for s in (states or []) if s in ALERT_STATES]
    return seen or ['RETEST_READY', 'CONFIRMED']


def _ist(dt) -> str:
    """Timestamps are stored naive UTC; everything the user reads is IST."""
    if dt is None:
        return ''
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(IST).strftime('%H:%M:%S')


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
    # The delivery log is the honest answer to "is this actually working?" — far better than a
    # Test button, which only proves the chat id is reachable.
    recent = (db.query(AlertDelivery).filter_by(user_id=user.id)
              .order_by(AlertDelivery.sent_at.desc()).limit(12).all())
    return {'enabled': bool(c.enabled), 'states': _clean_states(c.states), 'min_score': c.min_score,
            'available_states': ALERT_STATES,
            'channels': c.channels or {}, 'telegram_chat_id': c.telegram_chat_id or '',
            'has_telegram_token': bool(c.telegram_token_enc),
            'quiet_from': c.quiet_from or '', 'quiet_to': c.quiet_to or '',
            'recent': [{'symbol': d.symbol, 'side': d.side, 'state': d.state, 'ok': bool(d.ok),
                        'detail': d.detail or '', 'at': _ist(d.sent_at)}
                       for d in recent]}


@router.get('/chats')
def discover_chats(user: User = Depends(require_user), db: Session = Depends(get_db)):
    """List the groups/chats this user's bot can post to, so nobody has to hunt for a chat id."""
    c = _config(db, user)
    token = decrypt(c.telegram_token_enc)
    if not token:
        return {'ok': False, 'chats': [], 'message': 'Save your bot token first.'}
    return get_telegram_chats(token)


@router.put('')
async def put_alerts(request: Request, user: User = Depends(require_user),
                     db: Session = Depends(get_db)):
    b = await request.json()
    c = _config(db, user)
    c.enabled = 1 if b.get('enabled', True) else 0
    if 'states' in b:
        c.states = _clean_states(b['states'])
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
    from ..alerting import sample_message
    return send_telegram(sample_message(user), token=token, chat_id=c.telegram_chat_id)
