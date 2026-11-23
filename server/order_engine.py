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

from . import scanners, watchpins, exit_engine
from .models import Order, User


def close_fields(side: str, fill: float, stop: float, exit_price: float, qty: int):
    """Realised ₹ and R, measured from the ACTUAL fill price (not the requested entry)."""
    direction = 1 if side == 'LONG' else -1
    pnl = round((exit_price - fill) * qty * direction, 2)
    rps = abs(fill - stop) if stop else 0
    result_r = round((exit_price - fill) * direction / rps, 2) if rps else None
    return pnl, result_r


def mark_closed(order: Order, exit_price: float, note: str | None = None,
                reason: str | None = None) -> None:
    """Close a paper/live order, accounting for any partial book. Realised ₹ = runner P&L + booked
    P&L; R is measured from the ORIGINAL stop (init_stop) over the full size, so a breakeven move
    doesn't erase the trade's risk denominator."""
    basis = order.fill_price if order.fill_price is not None else order.entry
    direction = 1 if order.side == 'LONG' else -1
    booked_qty = order.booked_qty or 0
    runner_qty = (order.qty or 0) - booked_qty
    runner_pnl = ((exit_price - basis) * runner_qty * direction) if basis is not None else 0.0
    total = round(runner_pnl + (order.booked_pnl or 0.0), 2)
    init_stop = order.init_stop or order.stop or basis
    rps = abs(basis - init_stop) if (basis and init_stop) else 0
    order.exit_price = exit_price
    order.status = 'closed'
    order.closed_at = datetime.utcnow()
    order.pnl = total
    order.result_r = round(total / (rps * order.qty), 2) if (rps and order.qty) else None
    if reason:
        order._exit_reason = reason
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


def _manage_open_paper(order: Order, px: float, cfg: dict, now_ist_dt) -> bool:
    """Adaptive management for an OPEN paper position (Phase 0 exit engine): breakeven@1R, partial
    book-half, and the velocity time-decay governor. Mutates `order` in place and may CLOSE it (the
    governor books remaining at market). Returns True if anything changed. Safe no-op for legacy
    orders with no captured init_stop."""
    if not order.init_stop or order.fill_price is None:
        return False
    side, fill = order.side, order.fill_price
    changed = False
    be_r = float(cfg.get('exit_breakeven_at_r', 1.0) or 0)
    part_frac = float(cfg.get('exit_partial_frac', 0.5) or 0)
    part_r = float(cfg.get('exit_partial_at_r', 1.0) or 0)

    # 1) Partial book-half at +part_r, and move the runner's stop to breakeven.
    if (part_frac > 0 and part_r > 0 and not order.booked_qty
            and exit_engine.reached_r(side, fill, order.init_stop, px, part_r)):
        bq = int(floor((order.qty or 0) * part_frac))
        if bq >= 1:
            direction = 1 if side == 'LONG' else -1
            order.booked_qty = bq
            order.booked_pnl = round((px - fill) * bq * direction, 2)
            order.stop = fill
            order.be_moved = 1
            changed = True

    # 2) Breakeven at +be_r (independent of partials, if not already moved).
    if be_r > 0 and not order.be_moved and exit_engine.reached_r(side, fill, order.init_stop, px, be_r):
        order.stop = fill
        order.be_moved = 1
        changed = True

    # 3) Velocity governor: book the remaining at market when the far target is out of reach in the
    #    time left before the management cutoff (the APL Apollo rule).
    if bool(cfg.get('exit_velocity_governor', True)) and now_ist_dt is not None and order.filled_at:
        elapsed_min = (datetime.utcnow() - order.filled_at).total_seconds() / 60.0
        if exit_engine.velocity_exit(side, fill, px, order.target, elapsed_min, now_ist_dt,
                                     str(cfg.get('exit_mgmt_cutoff', '15:00')),
                                     float(cfg.get('exit_velocity_slack', 1.5) or 1.5)):
            mark_closed(order, px, reason='velocity')
            return True
    return changed


def process_paper(order: Order, px: float, cfg: dict | None = None, now_ist_dt=None) -> bool:
    """Advance one paper order against the latest price. Returns True if it changed."""
    if px is None:
        return False
    if order.status == 'pending':
        if _entry_triggered(order, px):
            order.status = 'open'
            order.fill_price = order.entry
            order.filled_at = datetime.utcnow()
            if order.init_stop is None:
                order.init_stop = order.stop   # capture the ORIGINAL stop for 1R math
            return True
        return False
    if order.status == 'open':
        changed = _manage_open_paper(order, px, cfg or {}, now_ist_dt)
        if order.status == 'closed':   # governor already booked it
            return True
        hit = _exit_hit(order, px)     # stop (maybe breakeven now) / target
        if hit:
            exit_price, reason = hit
            mark_closed(order, exit_price, reason=reason)
            return True
        return changed
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


def _trades_today(db: Session, user_id: int, sym: str, today: str) -> int:
    """Count of auto trades for this symbol ENTERED today (any direction, both auto sources).

    Replaces the old one-per-symbol/day guard. The re-entry model allows multiple, BOTH-DIRECTION
    trades per symbol across the day up to `max_trades_per_symbol` (the trader scalps the swing —
    see docs §2.8). Concurrency is capped separately to 1 by the live held-position set at each call
    site, so this only limits total re-entries, not simultaneous stacking."""
    from datetime import timezone as _tz
    from radar.utils import IST
    rows = (db.query(Order).filter(Order.user_id == user_id, Order.symbol == sym,
                                   Order.source.in_(('auto', 'auto_smc')))
            .order_by(Order.created_at.desc()).limit(25).all())
    return sum(1 for o in rows if o.created_at and
               o.created_at.replace(tzinfo=_tz.utc).astimezone(IST).date().isoformat() == today)


def _auto_trade(db: Session) -> int:
    """Per-user auto PAPER trading (admin-enabled). For each user with it on, drive trades off their
    live feed with no delay:
      - ENTER on a fresh opportunity (one entry per symbol/day), sized by their risk, at the signal
        status the user chose: RETEST_READY (default, double-confirmed) or CONFIRMED (the earlier,
        aggressive trigger — fires on the breakout itself, validated + fresh only).
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
    # How long a CONFIRMED breakout stays "fresh" enough to enter (mirrors the 5-min retest aging
    # the engine applies to RETEST_READY). Guards against backfilling an entry on a CONFIRMED that
    # has sat on the radar for hours at a stale price when auto-trade is (re)enabled mid-session.
    try:
        fresh_sec = int(cfg.get('auto_trade_fresh_seconds', 300) or 300)
    except (TypeError, ValueError):
        fresh_sec = 300
    changed = 0
    for u in users:
        try:
            st = scanners.radar_state(db, u)
        except Exception:
            continue
        if st.get('data_mode') != 'live':
            continue
        # Once a one-pass sim session has ended, the state is frozen — don't keep re-entering a symbol
        # that's stuck in RETEST_READY. (Exits are moot too: no new opposite signals appear; the
        # session-end square-off closes anything still open.)
        sim_closed = bool(u.sim_enabled and st.get('session_closed'))
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
        # Which signal status this user wants to auto-enter on. RETEST_READY (default) = the safer
        # double-confirmation; CONFIRMED = the aggressive, earlier trigger (fires on the breakout
        # itself, so stocks that never retest still trade).
        trigger = str(sdata.get('auto_trade_trigger',
                      cfg.get('auto_trade_trigger', 'RETEST_READY')) or 'RETEST_READY').upper()
        if trigger not in ('RETEST_READY', 'CONFIRMED'):
            trigger = 'RETEST_READY'
        for r in rows:
            state = r.get('state')
            if trigger == 'CONFIRMED':
                # Enter on the breakout confirmation OR a later retest, whichever comes first
                # (one entry per symbol/day still prevents a double). A CONFIRMED entry must be
                # REST-validated (never a provisional WS signal the engine may retract) and still
                # fresh — otherwise we'd open on a stale breakout at a stale price.
                if state not in ('CONFIRMED', 'RETEST_READY'):
                    continue
                if state == 'CONFIRMED':
                    if r.get('provisional'):
                        continue
                    age = r.get('signal_age_sec')
                    if age is None or age > fresh_sec:
                        continue
            else:
                if state != 'RETEST_READY':
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
            # simulation may re-enter each cycle (after the prior position closed) so trades keep
            # flowing while you watch — but NOT after the session has ended.
            if sim_closed:
                continue
            if sym in pending_auto:
                continue
            if not u.sim_enabled and _trades_today(db, u.id, sym, today) >= int(cfg.get('max_trades_per_symbol', 4) or 4):
                continue
            rps = abs(entry - stop)
            qty = int(floor(max_risk / rps)) if (max_risk and rps) else 0
            if qty < 1:
                continue
            db.add(Order(user_id=u.id, symbol=sym, side=side, qty=qty, entry=entry, stop=stop,
                         target=target, status='pending', order_type='market', mode='paper',
                         sim=1 if u.sim_enabled else 0, source='auto',
                         note=f'Auto paper trade — algo {state} ({today}).'))
            pending_auto.add(sym)
            changed += 1
    if changed:
        db.commit()
    return changed


def _auto_trade_smc(db: Session) -> int:
    """Per-user auto PAPER trading on SMC opportunities — opt-in, separate from the ORB auto-trade.
    For each user who has auto-trade ON (admin master switch) AND opted into SMC
    (settings.auto_trade_smc), enter a fresh high-conviction setup: LONG in a discount zone / SHORT
    in a premium zone, ONLY when price is inside a fresh order block and the net R:R clears the 2:1
    gate. Sized by the user's risk; one entry per symbol/day shared with the ORB strategy. Paper
    only — live never auto-fires. Stop/target exits and the session square-off run through the same
    machinery as every other paper order. Returns the number of entries made."""
    from radar.utils import load_config, now_ist
    users = db.query(User).filter(User.auto_paper_trade == 1).all()
    if not users:
        return 0
    cfg = load_config()
    today = now_ist().date().isoformat()
    min_rr = float(cfg.get('min_net_reward_risk', 2.0) or 2.0)
    changed = 0
    for u in users:
        sdata = (u.settings.data if u.settings else {}) or {}
        if not bool(sdata.get('auto_trade_smc', cfg.get('auto_trade_smc', False))):
            continue
        try:
            st = scanners.radar_state(db, u)
        except Exception:
            continue
        if st.get('data_mode') != 'live':
            continue
        if u.sim_enabled and st.get('session_closed'):
            continue   # frozen one-pass sim — stop re-entering
        try:
            min_score = int(sdata.get('auto_trade_smc_min_score',
                                      cfg.get('auto_trade_smc_min_score', 80)) or 80)
        except (TypeError, ValueError):
            min_score = 80
        capital = float(sdata.get('capital_inr', cfg.get('capital_inr', 0)) or 0)
        risk_pct = float(sdata.get('risk_pct', cfg.get('risk_pct', 0)) or 0)
        max_risk = capital * risk_pct / 100 if (capital and risk_pct) else 0
        if not max_risk:
            continue
        try:
            opps = (scanners.smc_state(db, u).get('opportunities')) or []
        except Exception:
            continue
        # Symbols already held by EITHER auto strategy — never stack the same stock.
        held = {watchpins.bare(o.symbol) for o in db.query(Order)
                .filter(Order.user_id == u.id, Order.source.in_(('auto', 'auto_smc')),
                        Order.status.in_(('pending', 'open'))).all()}
        for o in opps:
            try:
                score = int(o.get('score') or 0)
            except (TypeError, ValueError):
                continue
            if score < min_score:
                continue
            plan = o.get('trade') or {}
            side = plan.get('side')
            entry, stop, target, rr = (plan.get('entry'), plan.get('stop'),
                                       plan.get('target'), plan.get('rr'))
            # Let-winners-run: when on, don't cap the position at a fixed target — it rides until the
            # stop or the session square-off (15:15), the way the trader actually exits. The target is
            # still computed above for the R:R shown in the note. Default off (fixed target).
            runner = bool(sdata.get('smc_runner_target', cfg.get('smc_runner_target', False)))
            if side not in ('LONG', 'SHORT') or not entry or not stop or (not target and not runner):
                continue
            # The hard 2:1 reward:risk reject throws away otherwise-valid setups and is foreign to how
            # the trader sizes risk. Keep it by default, but allow turning it off (R:R stays visible).
            enforce_rr = bool(sdata.get('smc_enforce_min_rr', cfg.get('smc_enforce_min_rr', True)))
            if enforce_rr and (rr is None or rr < min_rr):
                continue   # fails the 2:1 net reward:risk gate
            sym = watchpins.bare(o.get('symbol') or '')
            if not sym or sym in held:
                continue
            if not u.sim_enabled and _trades_today(db, u.id, sym, today) >= int(cfg.get('max_trades_per_symbol', 4) or 4):
                continue
            rps = abs(entry - stop)
            qty = int(floor(max_risk / rps)) if rps else 0
            if qty < 1:
                continue
            stop_src = ('OB stop' if plan.get('in_fresh_ob')
                        else 'structure stop' if str(cfg.get('smc_stop_mode', 'ob_atr')) == 'structure'
                        else 'ATR stop')
            order_target = None if runner else target
            exit_note = 'let-run (stop/square-off)' if runner else f'target {target}'
            smc_order = Order(user_id=u.id, symbol=sym, side=side, qty=qty, entry=entry, stop=stop,
                              target=order_target, status='pending', order_type='market', mode='paper',
                              sim=1 if u.sim_enabled else 0, source='auto_smc',
                              note=f'Auto SMC trade — {side} score {score}, R:R {rr}, {stop_src}, {exit_note} ({today}).')
            try:   # log the confluence snapshot at entry (training data for the auto-trade path)
                from . import trade_features
                if o.get('confluence'):
                    trade_features.record_features(smc_order, {'confluence': o.get('confluence'),
                                                               'side': side, 'score': score})
            except Exception:
                pass
            db.add(smc_order)
            held.add(sym)
            changed += 1
    if changed:
        db.commit()
    return changed


def _square_off_paper(db: Session) -> int:
    """Intraday safety at session end (15:15 live, or when the feed's session closes): force-close any
    still-open real PAPER position whose stop/target didn't trigger, AND cancel any still-WORKING
    (pending, unfilled) order — a working order must never carry past the square-off into the next day.
    Simulation orders are EXCLUDED: they live in accelerated sim-time (real 15:15 is irrelevant) and are
    handled by _square_off_sim."""
    from radar.utils import now_ist
    orders = (db.query(Order).filter_by(mode='paper').filter(Order.sim == 0)
              .filter(Order.status.in_(('open', 'pending'))).all())
    if not orders:
        return 0
    live_cutoff = now_ist().strftime('%H:%M') >= '15:15'
    by_user: dict[int, list[Order]] = {}
    for o in orders:
        by_user.setdefault(o.user_id, []).append(o)
    changed = 0
    for uid, uorders in by_user.items():
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
        for o in uorders:
            if o.status == 'pending':
                o.status = 'cancelled'
                o.closed_at = datetime.utcnow()
                o.note = 'Auto-cancelled: working order unfilled at session end (intraday rule).'
            else:
                exit_px = pm.get(watchpins.bare(o.symbol)) or o.target or o.fill_price or o.entry
                mark_closed(o, exit_px, note='Auto square-off at session end (intraday rule).')
            changed += 1
    if changed:
        db.commit()
    return changed


def _square_off_sim(db: Session) -> int:
    """Flat-by-close for the simulation: when a user's one-pass sim session has ENDED (the sim feed
    reports session_closed, i.e. sim-time passed sim_end), force-close any still-open SIM positions at
    the last sim price AND cancel any unfilled (pending) SIM orders — the practice equivalent of the
    intraday square-off. While the session is still playing, session_closed is False so trades exit
    normally via stop/target."""
    sim_orders = (db.query(Order).filter_by(mode='paper').filter(Order.sim == 1)
                  .filter(Order.status.in_(('open', 'pending'))).all())
    if not sim_orders:
        return 0
    by_user: dict[int, list[Order]] = {}
    for o in sim_orders:
        by_user.setdefault(o.user_id, []).append(o)
    changed = 0
    for uid, orders in by_user.items():
        user = db.get(User, uid)
        if user is None or not user.sim_enabled:
            continue
        try:
            st = scanners.radar_state(db, user)
        except Exception:
            st = {}
        if not bool(st.get('session_closed')):
            continue   # sim session still playing — let stop/target run
        pm = {watchpins.bare(r['symbol']): r.get('price') for r in (st.get('all') or []) if r.get('symbol')}
        for o in orders:
            if o.status == 'pending':
                o.status = 'cancelled'
                o.closed_at = datetime.utcnow()
                o.note = 'Sim — unfilled at session end, cancelled.'
            else:
                exit_px = pm.get(watchpins.bare(o.symbol)) or o.target or o.fill_price or o.entry
                mark_closed(o, exit_px, note='Sim square-off at session end.')
            changed += 1
    if changed:
        db.commit()
    return changed


def tick(db: Session, live_sync: bool = True) -> int:
    """One processing pass: auto-trade, fills/exits, live sync, end-of-day square-off."""
    created = _auto_trade(db)
    created += _auto_trade_smc(db)   # SMC opt-in strategy, entered the same pass
    from radar.utils import load_config, now_ist
    _cfg = load_config()             # exit-engine knobs (breakeven/partial/velocity)
    _now_i = now_ist()               # IST clock for the velocity-governor cutoff
    active = (db.query(Order)
              .filter(Order.status.in_(('pending', 'open')))
              .all())
    if not active:
        return created + _square_off_paper(db) + _square_off_sim(db)
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
                    if process_paper(o, pm.get(watchpins.bare(o.symbol)), _cfg, _now_i):
                        changed += 1
        if live and live_sync:
            try:
                changed += _sync_live(db, user, live)
            except Exception as e:
                print(f'live order sync skipped (user {user_id}): {e}')
    if changed:
        db.commit()
    return created + changed + _square_off_paper(db) + _square_off_sim(db)


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
