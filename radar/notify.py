"""Telegram alerts for actionable signals (Phase 2 MVP, per CLAUDE.md).

Sends the FULL trade ticket (symbol, side, entry, stop, target, suggested qty, rupee risk,
R:R) so nothing is acted on without the ticket visible. Read-only: this NEVER places an
order; it notifies you to review and decide. No-ops silently if Telegram isn't configured.
"""
from __future__ import annotations
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from .risk import position_size

# Signal states worth a push (skip noisy WATCH/READY/NONE).
ALERT_STATES = {'RETEST_READY', 'CONFIRMED', 'RETRACTED'}


def telegram_creds() -> tuple[str, str]:
    return (os.environ.get('TELEGRAM_BOT_TOKEN', '').strip(),
            os.environ.get('TELEGRAM_CHAT_ID', '').strip())


def telegram_configured() -> bool:
    token, chat = telegram_creds()
    return bool(token and chat)


def send_telegram(text: str, token: Optional[str] = None,
                  chat_id: Optional[str] = None) -> dict:
    """Post a message. Returns {ok, message}. No exception on network/config failure."""
    if token is None or chat_id is None:
        token, chat_id = telegram_creds()
    if not token or not chat_id:
        return {'ok': False, 'message': 'Telegram not configured (set bot token + chat id).'}
    payload = json.dumps({'chat_id': chat_id, 'text': text,
                          'parse_mode': 'HTML', 'disable_web_page_preview': True}).encode()
    req = urllib.request.Request(
        f'https://api.telegram.org/bot{token}/sendMessage',
        data=payload, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = json.loads(resp.read().decode('utf-8'))
            return {'ok': bool(body.get('ok')), 'message': body.get('description', 'sent')}
    except urllib.error.HTTPError as e:
        try:
            desc = json.loads(e.read().decode()).get('description', str(e))
        except Exception:
            desc = str(e)
        return {'ok': False, 'message': f'Telegram error: {desc}'}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {'ok': False, 'message': f'Telegram unreachable: {e}'}


def format_ticket(sig, config: dict) -> str:
    """Build the HTML message for a signal, including suggested qty and rupee risk."""
    bare = sig.symbol.replace('NSE:', '').replace('-EQ', '')
    prov = ' ⚠️<b>PROVISIONAL</b> (live, pending confirm)' if getattr(sig, 'provisional', False) else ''
    header = {'RETEST_READY': f'🎯 <b>{bare}</b> {sig.side} — RETEST READY',
              'CONFIRMED': f'✅ <b>{bare}</b> {sig.side} — breakout confirmed',
              'RETRACTED': f'🛑 <b>{bare}</b> — signal RETRACTED (stand down)'}.get(
                  sig.state, f'<b>{bare}</b> {sig.side} — {sig.state}')
    lines = [header + prov, f'<i>{sig.time} IST · score {sig.score}</i>']
    if sig.state == 'RETEST_READY' and sig.entry and sig.stop:
        s = position_size(sig.entry, sig.stop, config.get('capital_inr', 0),
                          config.get('risk_pct', 0))
        tgt = f'{sig.target:.2f}' if sig.target else '—'
        rr = f'{sig.net_rr:.2f}' if sig.net_rr else '—'
        lines += [
            '',
            f'Entry  <b>{sig.entry:.2f}</b>',
            f'Stop   <b>{sig.stop:.2f}</b>',
            f'Target <b>{tgt}</b>   (net R:R {rr})',
            f'Qty    <b>{s["qty"]}</b>  (risk ≈ ₹{s["actual_risk"]:.0f} of '
            f'₹{s["risk_budget"]:.0f} budget)',
            '',
            '⚠️ Estimate only. Verify MIS eligibility, spread, levels & trend. '
            'Flat by 3:20 PM IST. Not an auto-order.']
    elif sig.state == 'CONFIRMED':
        lines.append('Waiting for a clean retest before any entry ticket.')
    return '\n'.join(lines)


def notify_signal(sig, config: dict) -> None:
    """Fire-and-forget push for an actionable signal; silent if unconfigured."""
    if sig.state not in ALERT_STATES or not telegram_configured():
        return
    send_telegram(format_ticket(sig, config))
