"""Daily opportunities audit — persists what the radar flagged each day.

The live scanner holds state in memory; this records a durable, per-user daily trail of every
actionable opportunity (what, which side, best state reached, levels, score) so the user can later
review the day and see which signals they acted on. User actions live in the Order table; the
journal API joins the two.

Design Note: ACTIONABLE includes pre-signals (READY, BREAKOUT_PENDING) for progression tracking
and "almost" opportunity analysis. Many READY stocks never confirm, but recording them helps
answer: "How many watchlist candidates actually triggered?" and "Should I be more aggressive?"
For a cleaner journal, the UI can filter to show only CONFIRMED/RETEST_READY (actual trade signals).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from radar.utils import now_ist

from .models import SignalLog, User

# States worth remembering (an actual actionable opportunity, not idle monitoring).
# RETEST_READY has highest priority as it represents double-confirmation (breakout + support held).
ACTIONABLE = {'CONFIRMED', 'RETEST_READY', 'BREAKOUT_PENDING', 'READY'}
_PRIORITY = {
    'READY': 1,              # Pre-signal: watching for breakout
    'BREAKOUT_PENDING': 2,   # Pre-signal: breaking through, candle not closed
    'CONFIRMED': 3,          # 1st confirmation: breakout + volume
    'RETEST_READY': 4        # 2nd confirmation: support held (BEST signal)
}


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


def apply_prerequisite_filters(opportunities: list, user: User, strategy: str = 'ORB') -> tuple[list, int]:
    """Apply a user's pre-requisite filters to a list of opportunity dicts.

    Lives here (not in server.main) so the server-side journaling sweep AND the radar endpoints can
    share one implementation. Returns (filtered_opportunities, rejected_count). Best-effort / pure.
    """
    if not opportunities:
        return opportunities, 0
    if not user.settings:
        return opportunities, 0  # No settings = no filtering

    from radar.prerequisites import PrerequisiteConfig, PrerequisiteChecker
    import json as json_lib

    prereq_config = PrerequisiteConfig(
        min_rvol=user.settings.prereq_min_rvol or 1.0,
        rvol_enabled=bool(user.settings.prereq_rvol_enabled),
        min_liquidity_cr=user.settings.prereq_min_liquidity_cr,
        min_price=user.settings.prereq_min_price,
        max_price=user.settings.prereq_max_price,
        allowed_sectors=json_lib.loads(user.settings.prereq_allowed_sectors) if user.settings.prereq_allowed_sectors else None,
        blocked_symbols=json_lib.loads(user.settings.prereq_blocked_symbols) if user.settings.prereq_blocked_symbols else None,
    )
    if not prereq_config.rvol_enabled:
        return opportunities, 0

    checker = PrerequisiteChecker(prereq_config)
    filtered: list = []
    rejected = 0
    for opp in opportunities:
        symbol = opp.get('symbol', '')
        price = opp.get('price')
        if strategy == 'ORB':
            rvol = opp.get('rvol')
        elif strategy == 'SMC':
            rvol = (opp.get('confluence') or {}).get('rvol_cum')
        else:
            rvol = None
        liquidity_cr = None
        result = checker.check(symbol, {'rvol': rvol, 'price': price, 'liquidity_cr': liquidity_cr})
        # An unmeasurable (None) input isn't a failure — rejecting on it would empty the radar. Keep
        # the opportunity when every failed check is merely unmeasurable; reject only a real breach.
        unmeasurable = set()
        if rvol is None:
            unmeasurable.add('RVOL')
        if liquidity_cr is None:
            unmeasurable.add('Liquidity')
        only_unmeasurable = bool(result.failed_checks) and set(result.failed_checks) <= unmeasurable
        if result.passed or only_unmeasurable:
            filtered.append(opp)
        else:
            rejected += 1
    return filtered, rejected


def sweep(db: Session) -> int:
    """Server-side opportunity journaling — records each user's actionable opportunities to SignalLog
    on the scheduler's cadence, so the daily history is captured even when the user's browser is
    closed (the GET /api/radar journaling it replaces only ran while someone was polling).

    Read-only on the feed: uses scanners.effective_feed, which NEVER starts a scanner — it journals
    against whatever scanner is already running (started by the scheduler / order engine). Mirrors the
    radar endpoint: same per-user prerequisite filter on the ORB opportunity list. Returns the number
    of users whose journal advanced."""
    from . import scanners
    n = 0
    for user in db.query(User).all():
        try:
            cc, state = scanners.effective_feed(db, user)
            if cc is None or not state or state.get('offline'):
                continue
            opps = state.get('all') or []
            if not opps:
                continue
            filtered, _ = apply_prerequisite_filters(opps, user, 'ORB')
            record_opportunities(db, user.id, {'all': filtered})
            n += 1
        except Exception as e:     # one user's failure must never stop the others
            db.rollback()
            print(f'[journal] sweep failed for user {user.id}: {type(e).__name__}: {e}')
    return n
