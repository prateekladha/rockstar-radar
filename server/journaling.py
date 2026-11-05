"""Daily opportunities audit — persists what the radar flagged each day.

The live scanner holds state in memory; this records a durable, per-user daily trail of every
actionable opportunity (what, which side, best state reached, levels, score) so the user can later
review the day and see which signals they acted on. User actions live in the Order table; the
journal API joins the two.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from radar.utils import now_ist

from .models import SignalLog

# States worth remembering (an actual actionable opportunity, not idle monitoring).
ACTIONABLE = {'CONFIRMED', 'RETEST_READY', 'BREAKOUT_PENDING', 'READY'}
_PRIORITY = {'READY': 1, 'BREAKOUT_PENDING': 2, 'RETEST_READY': 3, 'CONFIRMED': 4}


def _s(v):
    return None if v is None else str(v)


def record_opportunities(db: Session, user_id: int, state: dict) -> None:
    """Upsert today's actionable opportunities for this user (dedup by symbol+side, keep the
    highest-priority state reached and the latest levels). Best-effort; never raises to the caller."""
    rows = [r for r in (state.get('all') or []) if r.get('state') in ACTIONABLE]
    if not rows:
        return
    day = now_ist().date().isoformat()
    existing = {(s.symbol, s.side): s for s in
                db.query(SignalLog).filter_by(user_id=user_id, day=day).all()}
    changed = False
    for r in rows:
        key = (r.get('symbol'), r.get('side'))
        state_name = r.get('state')
        prev = existing.get(key)
        if prev is None:
            db.add(SignalLog(
                user_id=user_id, day=day, symbol=r.get('symbol'), side=r.get('side'),
                state=state_name, score=r.get('score') or 0,
                entry=_s(r.get('entry')), stop=_s(r.get('stop')), target=_s(r.get('target')),
                net_rr=_s(r.get('net_rr')), rvol=_s(r.get('rvol')),
                qty=r.get('qty'), provisional=1 if r.get('provisional') else 0,
                note=r.get('reason'),
                timeline=[{'t': now_ist().strftime('%H:%M:%S'), 'event': state_name,
                           'detail': r.get('reason')}]))
            changed = True
        elif _PRIORITY.get(state_name, 0) > _PRIORITY.get(prev.state, 0):
            tl = list(prev.timeline or [])
            tl.append({'t': now_ist().strftime('%H:%M:%S'), 'event': state_name,
                       'detail': r.get('reason')})
            prev.state = state_name
            prev.score = max(prev.score or 0, r.get('score') or 0)
            prev.entry, prev.stop, prev.target = _s(r.get('entry')), _s(r.get('stop')), _s(r.get('target'))
            prev.net_rr, prev.rvol = _s(r.get('net_rr')), _s(r.get('rvol'))
            prev.provisional = 1 if r.get('provisional') else 0
            prev.timeline = tl
            changed = True
    if changed:
        db.commit()
