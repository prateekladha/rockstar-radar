"""Data model (v1). Designed for multi-tenancy + RBAC/family from the start.

Household = tenant (a family or firm). Users belong to a household with a role. Watchlist
and Settings are per-user now, shareable within a household later. BrokerConnection stores
per-user, per-capability broker credentials (encrypted) for the data-vs-orders split.
"""
from __future__ import annotations
import json
from datetime import datetime

from sqlalchemy import (JSON, Column, DateTime, Float, ForeignKey, Identity, Integer, String,
                        Text, UniqueConstraint)
from sqlalchemy.orm import relationship

from .db import Base

ROLES = ('admin', 'trader')   # admin manages org + members + strategy; trader trades


def _now():
    return datetime.utcnow()


class Household(Base):
    __tablename__ = 'households'
    id = Column(Integer, Identity(), primary_key=True)
    name = Column(String(120), nullable=False, default='My Household')
    owner_user_id = Column(Integer)   # the creator; protected from role change / removal by others
    created_at = Column(DateTime, default=_now)
    users = relationship('User', back_populates='household', cascade='all, delete-orphan')


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, Identity(), primary_key=True)
    household_id = Column(Integer, ForeignKey('households.id'), nullable=False)
    google_sub = Column(String(64), unique=True, index=True)   # Google account id
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(160))
    first_name = Column(String(80))
    last_name = Column(String(80))
    picture = Column(String(512))
    role = Column(String(16), default='admin')                 # admin | trader
    onboarded = Column(Integer, default=0)                      # completed name step?
    # Per-user, set by an admin on the team page. Default: paper ON, auto OFF.
    trading_mode = Column(String(8), default='paper')          # paper | live
    auto_paper_trade = Column(Integer, default=0)              # algo auto-trades on paper
    telegram_chat_id = Column(String(64))                      # for daily reconnect reminders
    # Practice/testing feed simulation (per-user, no admin needed, no broker needed).
    sim_enabled = Column(Integer, default=0)
    sim_start = Column(String(5), default='09:15')             # HH:MM — sim session open (real clock)
    sim_end = Column(String(5), default='15:30')               # HH:MM — sim session close
    created_at = Column(DateTime, default=_now)
    last_login = Column(DateTime, default=_now)

    household = relationship('Household', back_populates='users')
    watchlist = relationship('Watchlist', back_populates='user', uselist=False,
                             cascade='all, delete-orphan')
    settings = relationship('Settings', back_populates='user', uselist=False,
                            cascade='all, delete-orphan')
    broker_connections = relationship('BrokerConnection', back_populates='user',
                                      cascade='all, delete-orphan')

    @property
    def initials(self) -> str:
        fn, ln = (self.first_name or '').strip(), (self.last_name or '').strip()
        if fn or ln:
            return ((fn[:1] + ln[:1]) or fn[:1]).upper()
        return (self.name or self.email or '?')[:1].upper()

    @property
    def display_name(self) -> str:
        full = f'{self.first_name or ""} {self.last_name or ""}'.strip()
        return full or self.name or self.email

    def public(self) -> dict:
        return {'id': self.id, 'email': self.email, 'name': self.display_name,
                'first_name': self.first_name, 'last_name': self.last_name,
                'initials': self.initials, 'picture': self.picture, 'role': self.role,
                'is_admin': self.role == 'admin', 'onboarded': bool(self.onboarded),
                'household_id': self.household_id,
                'trading_mode': self.trading_mode or 'paper',
                'auto_paper_trade': bool(self.auto_paper_trade)}


class Watchlist(Base):
    __tablename__ = 'watchlists'
    id = Column(Integer, Identity(), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False)
    symbols_text = Column(Text, default='')
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    user = relationship('User', back_populates='watchlist')


class Settings(Base):
    __tablename__ = 'settings'
    id = Column(Integer, Identity(), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False)
    data = Column(JSON, default=dict)          # strategy/risk config overrides
    # Prerequisite checks (mandatory before strategy evaluation)
    prereq_min_rvol = Column(Float, default=1.0)
    prereq_rvol_enabled = Column(Integer, default=1)
    prereq_min_liquidity_cr = Column(Float)
    prereq_min_price = Column(Float)
    prereq_max_price = Column(Float)
    prereq_allowed_sectors = Column(Text)      # JSON array
    prereq_blocked_symbols = Column(Text)      # JSON array
    # RVOL calculation settings
    rvol_anchor_timeframe = Column(String(16), default='day')
    rvol_length = Column(Integer, default=10)
    rvol_calculation_mode = Column(String(16), default='cumulative')
    # EMA crossover strategy settings (EMA fast/slow — defaults 5/20, close, no offset)
    ema_fast_length = Column(Integer, default=5)
    ema_slow_length = Column(Integer, default=20)
    ema_source = Column(String(8), default='close')
    ema_offset = Column(Integer, default=0)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    user = relationship('User', back_populates='settings')


class AlertConfig(Base):
    """Per-user alert rules + channel config (Telegram token encrypted)."""
    __tablename__ = 'alert_configs'
    id = Column(Integer, Identity(), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False)
    enabled = Column(Integer, default=1)
    states = Column(JSON, default=lambda: ['RETEST_READY', 'CONFIRMED'])
    min_score = Column(Integer, default=0)
    # SMC (Smart Money Concepts) alert settings
    smc_alerts_enabled = Column(Integer, default=0)
    smc_min_score = Column(Integer, default=70)
    channels = Column(JSON, default=lambda: {'telegram': True, 'inapp': True, 'email': False})
    telegram_token_enc = Column(Text)
    telegram_chat_id = Column(String(64))
    quiet_from = Column(String(5))     # HH:MM
    quiet_to = Column(String(5))
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    user = relationship('User')


class AlertDelivery(Base):
    """One row per alert pushed — both the dedup key and the audit trail.

    Persisted rather than held in memory because the sweep re-reads the same radar state every
    few seconds: without a durable record, a server restart mid-session would re-announce every
    signal that already fired today. The unique constraint is the real guard — two workers racing
    on the same signal means one insert fails rather than two messages going out.
    """
    __tablename__ = 'alert_deliveries'
    id = Column(Integer, Identity(), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), index=True, nullable=False)
    day = Column(String(10), index=True)           # YYYY-MM-DD (IST trading day)
    symbol = Column(String(40))
    side = Column(String(8))
    state = Column(String(24))
    sent_at = Column(DateTime, default=_now)
    ok = Column(Integer, default=0)
    detail = Column(Text)
    __table_args__ = (UniqueConstraint('user_id', 'day', 'symbol', 'side', 'state',
                                       name='uq_alert_once_per_day'),)


class SignalLog(Base):
    """Every signal/trade a user saw — backbone of audit, insights, journal, debugger."""
    __tablename__ = 'signal_logs'
    id = Column(Integer, Identity(), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), index=True, nullable=False)
    ts = Column(DateTime, default=_now, index=True)
    day = Column(String(10), index=True)           # YYYY-MM-DD (IST trading day)
    symbol = Column(String(40))
    side = Column(String(8))
    state = Column(String(24))
    score = Column(Integer, default=0)
    entry = Column(String(16))
    stop = Column(String(16))
    target = Column(String(16))
    net_rr = Column(String(16))
    rvol = Column(String(16))
    qty = Column(Integer)
    risk_amount = Column(String(16))
    provisional = Column(Integer, default=0)
    note = Column(Text)
    outcome = Column(String(16), default='open')   # target | stop | open | expired
    result_r = Column(String(16))                  # realised R multiple
    timeline = Column(JSON, default=list)          # list of {t, event, detail} for the debugger


class Order(Base):
    """A trade the user took (paper or live). Source of truth for Journal, Positions, P&L."""
    __tablename__ = 'orders'
    id = Column(Integer, Identity(), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), index=True, nullable=False)
    created_at = Column(DateTime, default=_now, index=True)
    closed_at = Column(DateTime)
    symbol = Column(String(40), index=True)
    side = Column(String(8))                 # LONG | SHORT
    qty = Column(Integer, default=0)
    entry = Column(Float)
    stop = Column(Float)
    target = Column(Float)
    exit_price = Column(Float)
    # Lifecycle: pending (working/unfilled -> Cancel) -> open (filled position -> Close)
    #            -> closed. Or pending -> cancelled / rejected. Only `closed` counts toward P&L.
    status = Column(String(12), default='pending', index=True)
    order_type = Column(String(8), default='limit')            # market | limit (entry trigger)
    mode = Column(String(8), default='paper')                  # paper | live
    sim = Column(Integer, default=0)                           # placed in the practice simulation?
    source = Column(String(16), default='manual')              # signal | manual
    broker_order_id = Column(String(64))                        # broker's order id (live orders)
    fill_price = Column(Float)               # actual entry fill price (set when it fills -> open)
    filled_at = Column(DateTime)             # when it filled
    pnl = Column(Float)                      # realised ₹ when closed
    result_r = Column(Float)                 # realised R multiple when closed
    note = Column(Text)
    # Adaptive paper-exit state (Phase 0 exit engine). init_stop preserves the ORIGINAL stop so 1R is
    # still measurable after the live stop is moved to breakeven. booked_* track the partial book-half.
    init_stop = Column(Float)                # original stop captured at fill
    be_moved = Column(Integer, default=0)    # live stop moved to breakeven?
    booked_qty = Column(Integer, default=0)  # shares booked in the partial (runner = qty - booked_qty)
    booked_pnl = Column(Float, default=0.0)  # realised ₹ from the partial book
    # Phase 2 learning: the confluence signals/score captured at entry (JSON). Paired with the
    # realised pnl/result_r at exit, these rows are the training data for re-weighting (NO per-tick ML).
    features = Column(Text)
    # Paper→live parity (docs/PAPER_LIVE_PARITY.md). gross_pnl = realised ₹ BEFORE costs; charges =
    # modelled round-trip brokerage+statutory costs (paper only; live books real charges at the broker);
    # `pnl` is NET of charges. margin_used = real broker INTRADAY margin blocked at entry (margin API).
    # exit_reason tags how it closed: stop | target | velocity | square_off | reversal | manual.
    gross_pnl = Column(Float)
    charges = Column(Float, default=0.0)
    margin_used = Column(Float)
    exit_reason = Column(String(16))

    def risk_per_share(self):
        if self.entry and self.stop:
            return abs(self.entry - self.stop)
        return None

    def public(self, last_price=None):
        unreal = None
        basis = self.fill_price if self.fill_price is not None else self.entry
        if self.status == 'open' and last_price and self.qty and basis is not None:
            unreal = round((last_price - basis) * self.qty * (1 if self.side == 'LONG' else -1), 2)
        return {
            'id': self.id, 'created_at': self.created_at.isoformat() if self.created_at else None,
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'filled_at': self.filled_at.isoformat() if self.filled_at else None,
            'symbol': self.symbol, 'side': self.side, 'qty': self.qty,
            'entry': self.entry, 'stop': self.stop, 'target': self.target,
            'fill_price': self.fill_price, 'exit_price': self.exit_price,
            'status': self.status, 'order_type': self.order_type, 'mode': self.mode,
            'working': self.status == 'pending', 'source': self.source,
            'pnl': self.pnl, 'result_r': self.result_r, 'unrealized': unreal, 'note': self.note,
            'gross_pnl': self.gross_pnl, 'charges': self.charges, 'exit_reason': self.exit_reason,
        }


class SmartPick(Base):
    """A daily smart-watchlist idea: one stock, with long and/or short plans + levels."""
    __tablename__ = 'smart_picks'
    id = Column(Integer, Identity(), primary_key=True)
    household_id = Column(Integer, ForeignKey('households.id'), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), index=True)   # whose feed produced this pick
    day = Column(String(10), index=True)     # YYYY-MM-DD
    symbol = Column(String(40))
    name = Column(String(120))
    bias = Column(String(10))                # long | short | both | avoid
    focus = Column(Integer, default=0)       # top focus of the day
    long_plan = Column(JSON)                 # {entry, sl, invalidation, targets:[], note}
    short_plan = Column(JSON)
    note = Column(Text)
    source = Column(String(10), default='auto')   # auto (from scanner) | manual (admin-added)
    created_at = Column(DateTime, default=_now)

    def public(self):
        return {'id': self.id, 'day': self.day, 'symbol': self.symbol, 'name': self.name,
                'bias': self.bias, 'focus': bool(self.focus), 'source': self.source,
                'pinned': self.source == 'pinned',
                'long_plan': self.long_plan, 'short_plan': self.short_plan, 'note': self.note}


class BrokerConnection(Base):
    """Per-user broker credentials. capability = 'data' or 'orders'; secret is encrypted."""
    __tablename__ = 'broker_connections'
    __table_args__ = (UniqueConstraint('user_id', 'broker', 'capability',
                                       name='uq_user_broker_capability'),)
    id = Column(Integer, Identity(), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    broker = Column(String(32), default='fyers')      # fyers | zerodha | ...
    capability = Column(String(16), default='data')   # data | orders
    app_id = Column(String(128))
    secret_enc = Column(Text)                          # encrypted app secret
    token_enc = Column(Text)                           # encrypted access token (daily)
    refresh_enc = Column(Text)                          # encrypted refresh token (~15 days)
    pin_enc = Column(Text)                              # encrypted trading PIN (for auto-refresh)
    token_refreshed_at = Column(DateTime)              # when the access token was last minted
    redirect_uri = Column(String(512))
    status = Column(String(16), default='disconnected')
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    user = relationship('User', back_populates='broker_connections')


class SupportMessage(Base):
    """A query/issue/feature-request raised by a user from inside the product.
    Stored durably here AND delivered to the owner's Telegram (best-effort)."""
    __tablename__ = 'support_messages'
    id = Column(Integer, Identity(), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), index=True)
    kind = Column(String(16), default='question')   # question | issue | feature
    message = Column(Text)
    delivered = Column(Integer, default=0)          # 1 if Telegram delivery succeeded
    created_at = Column(DateTime, default=_now, index=True)


# ============================================================================
# Simulation / Backtesting Models
# ============================================================================

class SimRun(Base):
    """A simulation/backtest run with specific configuration on historical data."""
    __tablename__ = 'sim_runs'
    id = Column(Integer, Identity(), primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    config = Column(Text, nullable=False)          # JSON config snapshot
    start_date = Column(String(10), nullable=False)  # "2024-11-15"
    start_time = Column(String(5), nullable=False)   # "09:15"
    end_date = Column(String(10), nullable=False)
    end_time = Column(String(5), nullable=False)
    bar_interval = Column(String(2), nullable=False)  # "1" or "5"
    status = Column(String(16), default='pending', index=True)  # pending, fetching_data, running, completed, failed
    progress_pct = Column(Integer, default=0)
    error_message = Column(Text)
    created_at = Column(DateTime, default=_now, index=True)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    # Liveness: the executing process stamps this as it works (fetch per-symbol, replay per-progress).
    # A reconciler fails any non-terminal run whose heartbeat goes stale — i.e. the sim-worker pod that
    # claimed and was running it died mid-run (server/sim_worker, server/sim_controller.reconcile...).
    heartbeat_at = Column(DateTime)
    # Results summary
    total_opportunities = Column(Integer)
    total_trades = Column(Integer)
    total_pnl = Column(Float)
    win_rate = Column(Float)
    expectancy_r = Column(Float)
    total_r = Column(Float)
    max_drawdown_r = Column(Float)

    user = relationship('User')


class SimHistoricalBar(Base):
    """Cached historical market data (shared across all sim runs)."""
    __tablename__ = 'sim_historical_bars'
    id = Column(Integer, Identity(), primary_key=True)
    symbol = Column(String(40), nullable=False, index=True)
    date = Column(String(10), nullable=False, index=True)
    bar_interval = Column(String(2), nullable=False, index=True)
    timestamp = Column(String(32), nullable=False)  # ISO format with timezone
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=_now)


class SimSignalLog(Base):
    """Journal entries for each sim run (opportunities flagged)."""
    __tablename__ = 'sim_signal_logs'
    id = Column(Integer, Identity(), primary_key=True)
    sim_run_id = Column(Integer, ForeignKey('sim_runs.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    day = Column(String(10), nullable=False)
    sim_time = Column(String(32), nullable=False)
    symbol = Column(String(40))
    side = Column(String(8))
    state = Column(String(24), index=True)
    score = Column(Integer, default=0)
    entry = Column(String(16))
    stop = Column(String(16))
    target = Column(String(16))
    net_rr = Column(String(16))
    rvol = Column(String(16))
    qty = Column(Integer)
    provisional = Column(Integer, default=0)
    note = Column(Text)
    timeline = Column(Text)  # JSON array

    sim_run = relationship('SimRun')
    user = relationship('User')


class SimOrder(Base):
    """Orders/trades for each sim run."""
    __tablename__ = 'sim_orders'
    id = Column(Integer, Identity(), primary_key=True)
    sim_run_id = Column(Integer, ForeignKey('sim_runs.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    symbol = Column(String(40), nullable=False)
    side = Column(String(8), nullable=False)
    qty = Column(Integer, nullable=False)
    entry = Column(Float, nullable=False)
    stop = Column(Float, nullable=False)
    target = Column(Float)
    status = Column(String(16), default='open', index=True)
    source = Column(String(16), default='auto')
    created_at = Column(String(32), nullable=False)  # ISO timestamp (sim time)
    closed_at = Column(String(32))
    close_reason = Column(String(16))
    close_price = Column(Float)
    pnl = Column(Float)
    result_r = Column(Float)

    sim_run = relationship('SimRun')
    user = relationship('User')


class SimReplayEvent(Base):
    """Replay events for visualization (optional, for replay viewer)."""
    __tablename__ = 'sim_replay_events'
    id = Column(Integer, Identity(), primary_key=True)
    sim_run_id = Column(Integer, ForeignKey('sim_runs.id', ondelete='CASCADE'), nullable=False, index=True)
    sim_time = Column(String(32), nullable=False, index=True)
    event_type = Column(String(32), nullable=False)
    symbol = Column(String(40))
    data = Column(Text)  # JSON payload

    sim_run = relationship('SimRun')
