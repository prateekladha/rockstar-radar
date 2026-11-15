"""Per-user signal alerts — the dispatcher behind the Alerts page.

This lives in the server rather than the scanner for two reasons: the rules are per user, while a
single scanner can feed a whole household; and the scanner subprocess has no database. It is driven
by the scheduler, NOT by the browser polling /api/radar — the whole point is that a setup fires on
your phone with the dashboard closed.

Every send is recorded in AlertDelivery, which doubles as the dedup key: the sweep re-reads the same
radar state every few seconds, and a symbol sits in RETEST_READY for many minutes.
"""
from __future__ import annotations
from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from radar.notify import format_ticket, send_telegram
from radar.utils import load_config, now_ist

from .crypto import decrypt
from .models import AlertConfig, AlertDelivery, User

DEFAULT_STATES = ['CONFIRMED', 'RETEST_READY']
# A signal only alerts while it is FRESH. RETEST_READY already ages out of the radar (-> SIGNAL_AGED
# after 5 min), but CONFIRMED can sit in `all` for hours — without this gate, the first sweep after a
# user enables alerts mid-session (empty dedup) would blast a Telegram for every already-confirmed
# symbol at once. A confirmation fires at its bar close, so anything within the last few minutes is a
# genuinely current entry; older than this is backlog and is skipped (but still never re-alerted).
try:
    _FRESH_SEC = int(load_config().get('alert_fresh_seconds', 360) or 360)
except Exception:
    _FRESH_SEC = 360


def _num(v):
    try:
        return float(v) if v is not None and v != '' else None
    except (TypeError, ValueError):
        return None


def _in_quiet_hours(cfg: AlertConfig, now) -> bool:
    """Quiet windows may wrap past midnight (e.g. 22:00 -> 07:00), so a plain range test is wrong."""
    start, end = (cfg.quiet_from or '').strip(), (cfg.quiet_to or '').strip()
    if not start or not end:
        return False
    hhmm = now.strftime('%H:%M')
    return (start <= hhmm < end) if start <= end else (hhmm >= start or hhmm < end)


def _config_for(user: User) -> dict:
    """Radar config with the user's own capital/risk, so the ticket's suggested quantity and rupee
    risk match what they see in the app rather than the server defaults."""
    cfg = dict(load_config())
    data = (user.settings.data if user.settings else None) or {}
    for key in ('capital_inr', 'risk_pct'):
        if data.get(key) is not None:
            cfg[key] = data[key]
    return cfg


def _ticket(row: dict, when) -> SimpleNamespace:
    """Shape a radar row like a Signal so the live scanner's formatter can render it — one message
    format for every path, so a phone alert never disagrees with the dashboard."""
    return SimpleNamespace(
        symbol=row.get('symbol') or '', side=row.get('side') or '', state=row.get('state') or '',
        time=when.strftime('%Y-%m-%d %H:%M:%S'), score=row.get('score') or 0,
        entry=_num(row.get('entry')), stop=_num(row.get('stop')), target=_num(row.get('target')),
        net_rr=_num(row.get('net_rr')), provisional=bool(row.get('provisional')))


def dispatch(db: Session, user: User, state: dict) -> int:
    """Send alerts for any newly-reached state in this user's radar. Returns messages sent."""
    cfg = db.query(AlertConfig).filter_by(user_id=user.id).first()
    if cfg is None or not cfg.enabled:
        return 0
    if not (cfg.channels or {}).get('telegram', True):
        return 0
    token, chat = decrypt(cfg.telegram_token_enc), (cfg.telegram_chat_id or '').strip()
    if not token or not chat:
        return 0
    now = now_ist()
    if _in_quiet_hours(cfg, now):
        return 0

    wanted = set(cfg.states or DEFAULT_STATES)
    floor = int(cfg.min_score or 0)
    day = now.date().isoformat()
    simulated = bool(user.sim_enabled)
    conf = _config_for(user)
    already = {(d.symbol, d.side, d.state) for d in
               db.query(AlertDelivery).filter_by(user_id=user.id, day=day).all()}

    sent = 0
    for row in (state.get('all') or []):
        st = row.get('state')
        if st not in wanted or (row.get('score') or 0) < floor:
            continue
        # Freshness gate: only alert a currently-fresh signal. A CONFIRMED that has sat for hours
        # (age unknown/too old) is backlog — skip it (never claimed, so never sent, and no spam when
        # alerts are enabled mid-session). Fresh signals are caught within one 20s sweep of appearing.
        age = row.get('signal_age_sec')
        if age is None or age > _FRESH_SEC:
            continue
        key = (row.get('symbol'), row.get('side'), st)
        if not key[0] or key in already:
            continue
        # Claim the key BEFORE sending. If the send hangs or the process dies mid-flight we would
        # far rather lose one alert than re-announce the same setup on every sweep.
        row_rec = AlertDelivery(user_id=user.id, day=day, symbol=key[0], side=key[1], state=st)
        db.add(row_rec)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()          # another sweep already claimed it
            already.add(key)
            continue
        already.add(key)
        res = send_telegram(format_ticket(_ticket(row, now), conf, simulated=simulated),
                            token=token, chat_id=chat)
        row_rec.ok = 1 if res.get('ok') else 0
        row_rec.detail = (res.get('message') or '')[:300]
        db.commit()
        if res.get('ok'):
            sent += 1
    return sent


def sample_message(user: User) -> str:
    """Exactly what a real alert looks like, for the Test button.

    A test that just says "connected" proves the chat id resolves and nothing else. This renders
    the real ticket through the real formatter with this user's own capital and risk, so what
    arrives now is character-for-character what arrives on a Monday morning.
    """
    row = {'symbol': 'NSE:BHARTIARTL-EQ', 'side': 'LONG', 'state': 'RETEST_READY', 'score': 86,
           'entry': 2094.0, 'stop': 2071.80, 'target': 2140.0, 'net_rr': 2.31}
    # No practice banner even in simulation: the test banner already says this isn't real, and
    # stacking two makes the ticket itself harder to read — which is the thing being shown.
    body = format_ticket(_ticket(row, now_ist()), _config_for(user))
    return ('🧪 <b>TEST ALERT</b> — sample data. No such setup exists right now.\n'
            'A real one arrives the moment a stock reaches this state.\n\n' + body)


def sweep(db: Session) -> int:
    """Every user with alerts on, against whatever scanner is already feeding their radar.

    Uses effective_cc, which never starts a scanner: a background notifier must not spin up a
    broker session or spend quota on behalf of someone who isn't even using the app.
    """
    from . import scanners
    users = (db.query(User).join(AlertConfig, AlertConfig.user_id == User.id)
             .filter(AlertConfig.enabled == 1).all())
    total = 0
    for user in users:
        try:
            cc = scanners.effective_cc(db, user)
            if cc is None:
                continue
            state = cc.live_state()
            if state.get('offline'):
                continue
            total += dispatch(db, user, state)
        except Exception as e:     # one user's failure must never stop the others
            db.rollback()
            print(f'[alerts] sweep failed for user {user.id}: {type(e).__name__}: {e}')
    return total
