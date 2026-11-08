"""Order lifecycle engine — moves orders through pending -> open (filled) -> closed, automatically.

PAPER orders are simulated against the user's live feed: a working order fills when the market trades
through its entry, and a filled position auto-closes when price touches its stop or target.

LIVE orders are *synced* from the broker (read-only): we poll FYERS order status to detect fills /
cancels / rejections and position closure. We NEVER place an order here — the bracket stop/target the
user confirmed at placement executes on the broker; we only reflect it. Manual Close/Cancel (user
taps) are the only places a live order action is initiated, and those live in routers/trading.py.

Only `closed` orders (genuinely entered AND exited) count toward realised P&L.
"""
from __future__ import annotations
from datetime import datetime

from math import floor

from sqlalchemy.orm import Session

from . import scanners, watchpins
from .models import Order, User


def close_fields(side: str, fill: float, stop: float, exit_price: float, qty: int):
    """Realised ₹ and R, measured from the ACTUAL fill price (not the requested entry)."""
    direction = 1 if side == 'LONG' else -1
    pnl = round((exit_price - fill) * qty * direction, 2)
    rps = abs(fill - stop) if stop else 0
    result_r = round((exit_price - fill) * direction / rps, 2) if rps else None
    return pnl, result_r


def mark_closed(order: Order, exit_price: float, note: str | None = None) -> None:
    basis = order.fill_price if order.fill_price is not None else order.entry
    order.exit_price = exit_price
    order.status = 'closed'
    order.closed_at = datetime.utcnow()
    order.pnl, order.result_r = close_fields(order.side, basis, order.stop or basis, exit_price, order.qty)
    if note:
        order.note = note


def _entry_triggered(order: Order, px: float) -> bool:
    """Breakout/touch entry: a LONG fills once the market trades at/through the entry from below,
    a SHORT once it trades at/through from above. (Entry already passed -> fills on the next tick.)"""
    if order.side == 'LONG':
        return px >= order.entry
    return px <= order.entry


def _exit_hit(order: Order, px: float):
    """(exit_price, reason) if the live price has hit the stop or target, else None."""
    if order.side == 'LONG':
        if order.stop and px <= order.stop:
            return order.stop, 'stop'
        if order.target and px >= order.target:
            return order.target, 'target'
    else:
        if order.stop and px >= order.stop:
            return order.stop, 'stop'
        if order.target and px <= order.target:
            return order.target, 'target'
    return None


def process_paper(order: Order, px: float) -> bool:
    """Advance one paper order against the latest price. Returns True if it changed."""
    if px is None:
        return False
    if order.status == 'pending':
        if _entry_triggered(order, px):
            order.status = 'open'
            order.fill_price = order.entry
            order.filled_at = datetime.utcnow()
            return True
        return False
    if order.status == 'open':
        hit = _exit_hit(order, px)
        if hit:
            exit_price, reason = hit
            mark_closed(order, exit_price, note=(order.note or '') or None)
            order._exit_reason = reason  # transient, for logging
            return True
    return False


def _price_map(db: Session, user: User) -> dict:
    """{bare symbol -> last price} from the user's effective live feed (own, else shared)."""
    try:
        st = scanners.radar_state(db, user)
    except Exception:
        return {}
    if st.get('data_mode') != 'live':
        return {}
    out = {}
    for r in (st.get('all') or []):
        sym, px = r.get('symbol'), r.get('price')
        if sym and px:
            out[watchpins.bare(sym)] = px
    return out


def _entered_today(db: Session, user_id: int, sym: str, today: str) -> bool:
    """True if an auto trade for this symbol was already opened today (one entry per symbol/day)."""
    from datetime import timezone as _tz
    from radar.utils import IST
    prior = (db.query(Order).filter_by(user_id=user_id, symbol=sym, source='auto')
             .order_by(Order.created_at.desc()).first())
    return bool(prior and prior.created_at and
                prior.created_at.replace(tzinfo=_tz.utc).astimezone(IST).date().isoformat() == today)


def _auto_trade(db: Session) -> int:
    """Per-user auto PAPER trading (admin-enabled). For each user with it on, drive trades off their
    live feed with no delay:
      - ENTER on a fresh RETEST_READY opportunity (one entry per symbol/day), sized by their risk.
      - EXIT an open position the moment an opposite (reversal) signal appears on the same stock —
        the 'exit opportunity'. (Stop/target exits are handled by process_paper the same tick; the
        session-end square-off is the final safety net.)
    Race-safe: a position closed here is marked 'closed' and skipped by the stop/target pass. Paper
    only — no real money. Returns the number of entries + exits made."""
    from radar.utils import load_config, now_ist
    users = db.query(User).filter(User.auto_paper_trade == 1).all()
    if not users:
        return 0
    cfg = load_config()
    today = now_ist().date().isoformat()
    changed = 0
    for u in users:
        try:
            st = scanners.radar_state(db, u)
        except Exception:
            continue
        if st.get('data_mode') != 'live':
            continue
        rows = st.get('all') or []
        price_map = {watchpins.bare(r['symbol']): r.get('price') for r in rows if r.get('symbol')}
        open_auto = {watchpins.bare(o.symbol): o for o in db.query(Order)
                     .filter_by(user_id=u.id, source='auto', status='open').all()}
        pending_auto = {watchpins.bare(o.symbol) for o in db.query(Order)
                        .filter_by(user_id=u.id, source='auto', status='pending').all()}
        sdata = (u.settings.data if u.settings else {}) or {}
        capital = float(sdata.get('capital_inr', cfg.get('capital_inr', 0)) or 0)
        risk_pct = float(sdata.get('risk_pct', cfg.get('risk_pct', 0)) or 0)
        max_risk = capital * risk_pct / 100 if (capital and risk_pct) else 0
        for r in rows:
            if r.get('state') != 'RETEST_READY':
                continue
            side = r.get('side')
            sym = watchpins.bare(r.get('symbol') or '')
            entry, stop, target = r.get('entry'), r.get('stop'), r.get('target')
            if not sym or side not in ('LONG', 'SHORT') or not entry or not stop:
                continue
            pos = open_auto.get(sym)
            if pos is not None:
                # Existing position + a new signal on the same stock. Opposite side = reversal/exit
                # opportunity -> exit now at the live price. Same side = already in, nothing to do.
                if pos.side != side:
                    px = price_map.get(sym) or entry
                    mark_closed(pos, px, note='Auto exit — opposite (reversal) signal on the stock.')
                    del open_auto[sym]
                    changed += 1
                continue
            # No open position: don't double-enter. Real trading = one entry per symbol/day; the
            # simulation loop may re-enter each cycle (after the prior position closed) so trades keep
            # flowing while you watch.
            if sym in pending_auto:
                continue
            if not u.sim_enabled and _entered_today(db, u.id, sym, today):
                continue
            rps = abs(entry - stop)
            qty = int(floor(max_risk / rps)) if (max_risk and rps) else 0
            if qty < 1:
                continue
            db.add(Order(user_id=u.id, symbol=sym, side=side, qty=qty, entry=entry, stop=stop,
                         target=target, status='pending', order_type='market', mode='paper',
                         sim=1 if u.sim_enabled else 0, source='auto',
                         note=f'Auto paper trade — algo RETEST_READY ({today}).'))
            pending_auto.add(sym)
            changed += 1
    if changed:
        db.commit()
    return changed


def _square_off_paper(db: Session) -> int:
    """Intraday safety: force-close any still-open real PAPER position when its session ends and the
    feed-based stop/target didn't trigger — 15:15 (live) or when the feed's session closes. Simulation
    orders are EXCLUDED: they live in accelerated sim-time (real 15:15 is irrelevant) and exit purely
    via target/stop; a real-clock square-off would instantly close them near entry."""
    from radar.utils import now_ist
    open_paper = db.query(Order).filter_by(status='open', mode='paper').filter(Order.sim == 0).all()
    if not open_paper:
        return 0
    live_cutoff = now_ist().strftime('%H:%M') >= '15:15'
    by_user: dict[int, list[Order]] = {}
    for o in open_paper:
        by_user.setdefault(o.user_id, []).append(o)
    closed = 0
    for uid, orders in by_user.items():
        user = db.get(User, uid)
        if user is None:
            continue
        try:
            st = scanners.radar_state(db, user)
        except Exception:
            st = {}
        feed_closed = bool(st.get('session_closed')) or 'complete' in (st.get('feed_health') or '').lower()
        if not (live_cutoff or feed_closed):
            continue
        pm = {watchpins.bare(r['symbol']): r.get('price') for r in (st.get('all') or []) if r.get('symbol')}
        for o in orders:
            exit_px = pm.get(watchpins.bare(o.symbol)) or o.target or o.fill_price or o.entry
            mark_closed(o, exit_px, note='Auto square-off at session end (intraday rule).')
            closed += 1
    if closed:
        db.commit()
    return closed


def tick(db: Session, live_sync: bool = True) -> int:
    """One processing pass: auto-trade, fills/exits, live sync, end-of-day square-off."""
    created = _auto_trade(db)
    active = (db.query(Order)
              .filter(Order.status.in_(('pending', 'open')))
              .all())
    if not active:
        return created + _square_off_paper(db)
    by_user: dict[int, list[Order]] = {}
    for o in active:
        by_user.setdefault(o.user_id, []).append(o)

    changed = 0
    for user_id, orders in by_user.items():
        user = db.get(User, user_id)
        if user is None:
            continue
        paper = [o for o in orders if o.mode != 'live']
        live = [o for o in orders if o.mode == 'live']
        if paper:
            pm = _price_map(db, user)
            if pm:
                for o in paper:
                    if process_paper(o, pm.get(watchpins.bare(o.symbol))):
                        changed += 1
        if live and live_sync:
            try:
                changed += _sync_live(db, user, live)
            except Exception as e:
                print(f'live order sync skipped (user {user_id}): {e}')
    if changed:
        db.commit()
    return created + changed + _square_off_paper(db)


async def run_order_engine() -> None:
    """Background loop: paper fills/exits every ~8s, live broker sync ~every 24s, market hours only."""
    import asyncio
    from radar.utils import now_ist
    from .db import SessionLocal
    print('[order-engine] on — paper auto fill/close + live broker sync (market hours)')
    passes = 0
    while True:
        try:
            from radar.utils import is_market_day
            now = now_ist()
            hhmm = now.strftime('%H:%M')
            market = is_market_day(now.date()) and '09:00' <= hhmm <= '15:45'
            db = SessionLocal()
            try:
                # Run during market hours OR whenever a user has an accelerated sim session on.
                if market or scanners.any_sim_active(db):
                    passes += 1
                    # Tight cadence for precise auto entry/exit; live broker sync throttled (~20s).
                    await asyncio.to_thread(tick, db, passes % 4 == 0)
            finally:
                db.close()
        except Exception as e:
            print(f'[order-engine] tick error: {e}')
        await asyncio.sleep(5)


def _sync_live(db: Session, user: User, orders: list[Order]) -> int:
    """Read-only reconcile of the user's LIVE orders against their broker. Never places an order."""
    from .broker_orders import fetch_orderbook, fetch_positions, OrderError
    own = scanners._own_broker(db, user)
    if own is None or not own.token_enc or not scanners._token_is_fresh_today(own):
        return 0
    from .crypto import decrypt
    token = decrypt(own.token_enc) or ''
    try:
        book = fetch_orderbook(own.app_id, token)        # {broker_order_id -> {status, traded_price}}
    except OrderError:
        return 0
    changed = 0
    net_by_symbol = None
    for o in orders:
        info = book.get(o.broker_order_id) if o.broker_order_id else None
        if o.status == 'pending' and info:
            st = info.get('status')
            if st == 'filled':
                o.status = 'open'
                o.fill_price = info.get('traded_price') or o.entry
                o.filled_at = datetime.utcnow()
                changed += 1
            elif st == 'cancelled':
                o.status = 'cancelled'; changed += 1
            elif st == 'rejected':
                o.status = 'rejected'; changed += 1
        elif o.status == 'open':
            # The broker's bracket may have squared this off. Detect via net position == 0.
            if net_by_symbol is None:
                try:
                    net_by_symbol = fetch_positions(own.app_id, token)
                except OrderError:
                    net_by_symbol = {}
            net = net_by_symbol.get(watchpins.bare(o.symbol))
            if net is not None and net.get('net_qty') == 0:
                exit_px = net.get('last_price') or o.target or o.fill_price or o.entry
                mark_closed(o, exit_px, note='Closed on broker (bracket stop/target).')
                changed += 1
    return changed
