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


def tick(db: Session, live_sync: bool = True) -> int:
    """One processing pass across all users with active orders. Returns the number of changes."""
    active = (db.query(Order)
              .filter(Order.status.in_(('pending', 'open')))
              .all())
    if not active:
        return 0
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
    return changed


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
            if is_market_day(now.date()) and '09:00' <= hhmm <= '15:45':
                passes += 1
                db = SessionLocal()
                try:
                    await asyncio.to_thread(tick, db, passes % 3 == 0)
                finally:
                    db.close()
        except Exception as e:
            print(f'[order-engine] tick error: {e}')
        await asyncio.sleep(8)


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
