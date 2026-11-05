"""In-product Contact/Support — users raise queries/issues/requests; delivered to the owner's
Telegram and stored durably so nothing is lost if Telegram is misconfigured."""
from __future__ import annotations
import os

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from radar.notify import send_telegram

from ..auth import require_user
from ..db import get_db
from ..models import SupportMessage, User

router = APIRouter(prefix='/api', tags=['support'])

_KINDS = {'question', 'issue', 'feature'}
_LABEL = {'question': 'Question', 'issue': 'Issue', 'feature': 'Feature request'}


@router.post('/support')
async def submit_support(request: Request, user: User = Depends(require_user),
                         db: Session = Depends(get_db)):
    b = await request.json()
    kind = (b.get('kind') or 'question').strip().lower()
    if kind not in _KINDS:
        kind = 'question'
    message = (b.get('message') or '').strip()
    if len(message) < 3:
        return JSONResponse({'error': 'Please enter a bit more detail.'}, status_code=400)
    if len(message) > 4000:
        message = message[:4000]

    row = SupportMessage(user_id=user.id, kind=kind, message=message)
    db.add(row)
    db.commit()
    db.refresh(row)

    # Best-effort delivery to the owner's Telegram (env-configured).
    token = os.environ.get('SUPPORT_TELEGRAM_BOT_TOKEN', '').strip()
    chat = os.environ.get('SUPPORT_TELEGRAM_CHAT_ID', '').strip()
    if token and chat:
        text = (f'<b>🆘 {_LABEL[kind]}</b> · Rockstar Radar\n'
                f'<b>From:</b> {user.display_name} ({user.email}) · role {user.role}\n'
                f'<b>Message:</b>\n{message}')
        res = send_telegram(text, token=token, chat_id=chat)
        if res.get('ok'):
            row.delivered = 1
            db.commit()

    return {'ok': True, 'id': row.id,
            'message': 'Thanks — your message has been sent. We\'ll get back to you.'}
