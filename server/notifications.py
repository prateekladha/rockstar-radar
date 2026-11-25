"""Telegram notifications — owner alerts (signups, daily P&L) and per-user reconnect reminders.

All sends are best-effort via the support bot token (SUPPORT_TELEGRAM_BOT_TOKEN). If the creds aren't
configured yet, every function is a quiet no-op — nothing breaks.
"""
from __future__ import annotations
import os
from datetime import timezone

from sqlalchemy.orm import Session

from radar.notify import send_telegram
from radar.utils import IST, now_ist

from .models import BrokerConnection, Order, User


def _support_token() -> str:
    return os.environ.get('SUPPORT_TELEGRAM_BOT_TOKEN', '').strip()


def _support_chat() -> str:
    return os.environ.get('SUPPORT_TELEGRAM_CHAT_ID', '').strip()


def _site() -> str:
    return (os.environ.get('PUBLIC_BASE_URL') or 'https://intraday.live').rstrip('/')


def notify_new_signup(user: User) -> None:
    token, chat = _support_token(), _support_chat()
    if not (token and chat):
        return
    text = (f'🎉 <b>New signup</b> · Rockstar Radar\n'
            f'<b>{user.display_name}</b> ({user.email})\n'
            f'{now_ist().strftime("%d %b %Y, %H:%M")} IST')
    try:
        send_telegram(text, token=token, chat_id=chat)
    except Exception as e:
        print(f'signup notify failed: {e}')


def _is_today_ist(dt) -> bool:
    if not dt:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST).date() == now_ist().date()


def notify_daily_pnl(db: Session) -> None:
    """End-of-session summary: each user's realised P&L for today, to the owner's support Telegram."""
    token, chat = _support_token(), _support_chat()
    if not (token and chat):
        return
    users = db.query(User).all()
    lines, total = [], 0.0
    for u in users:
        closed = (db.query(Order).filter_by(user_id=u.id, status='closed').all())
        day_pnl = sum((o.pnl or 0) for o in closed if _is_today_ist(o.closed_at))
        n = sum(1 for o in closed if _is_today_ist(o.closed_at))
        if n == 0:
            continue
        total += day_pnl
        lines.append(f'• {u.display_name}: ₹{round(day_pnl):,} ({n} trade{"s" if n != 1 else ""})')
    if not lines:
        lines = ['No closed trades today.']
    text = (f'📊 <b>Daily P&L</b> · {now_ist().strftime("%d %b %Y")}\n'
            + '\n'.join(lines)
            + f'\n<b>Total: ₹{round(total):,}</b>')
    try:
        send_telegram(text, token=token, chat_id=chat)
    except Exception as e:
        print(f'daily P&L notify failed: {e}')


def remind_reconnect(db: Session, conns: list[BrokerConnection]) -> int:
    """DM each user whose broker needs today's login, with the link — via their OWN registered Telegram
    bot (the per-user alert bot: AlertConfig.telegram_token_enc + telegram_chat_id, the same creds that
    deliver their signal alerts), NOT the shared support bot (which isn't provisioned on OKE). A user
    with no per-user bot configured simply gets no reminder."""
    from .crypto import decrypt
    from .models import AlertConfig
    sent = 0
    for c in conns:
        u = c.user
        if not u:
            continue
        cfg = db.query(AlertConfig).filter_by(user_id=u.id).first()
        if cfg is None:
            continue
        token = decrypt(cfg.telegram_token_enc)
        chat = (cfg.telegram_chat_id or '').strip()
        if not token or not chat:
            continue
        text = (f'🔔 <b>Rockstar Radar</b> — log in to your broker for today before the market opens '
                f'so your scan runs.\n👉 {_site()}/brokers')
        try:
            if send_telegram(text, token=token, chat_id=chat).get('ok'):
                sent += 1
        except Exception as e:
            print(f'reconnect reminder failed for {u.email}: {e}')
    return sent
