"""Data model (v1). Designed for multi-tenancy + RBAC/family from the start.

Household = tenant (a family or firm). Users belong to a household with a role. Watchlist
and Settings are per-user now, shareable within a household later. BrokerConnection stores
per-user, per-capability broker credentials (encrypted) for the data-vs-orders split.
"""
from __future__ import annotations
import json
from datetime import datetime

from sqlalchemy import (JSON, Column, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import relationship

from .db import Base

ROLES = ('admin', 'trader')   # admin manages org + members + strategy; trader trades


def _now():
    return datetime.utcnow()


class Household(Base):
    __tablename__ = 'households'
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False, default='My Household')
    created_at = Column(DateTime, default=_now)
    users = relationship('User', back_populates='household', cascade='all, delete-orphan')


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    household_id = Column(Integer, ForeignKey('households.id'), nullable=False)
    google_sub = Column(String(64), unique=True, index=True)   # Google account id
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(160))
    first_name = Column(String(80))
    last_name = Column(String(80))
    picture = Column(String(512))
    role = Column(String(16), default='admin')                 # admin | trader
    onboarded = Column(Integer, default=0)                      # completed name step?
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
                'household_id': self.household_id}


class Watchlist(Base):
    __tablename__ = 'watchlists'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False)
    symbols_text = Column(Text, default='')
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    user = relationship('User', back_populates='watchlist')


class Settings(Base):
    __tablename__ = 'settings'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False)
    data = Column(JSON, default=dict)          # strategy/risk config overrides
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    user = relationship('User', back_populates='settings')


class AlertConfig(Base):
    """Per-user alert rules + channel config (Telegram token encrypted)."""
    __tablename__ = 'alert_configs'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), unique=True, nullable=False)
    enabled = Column(Integer, default=1)
    states = Column(JSON, default=lambda: ['RETEST_READY', 'CONFIRMED'])
    min_score = Column(Integer, default=0)
    channels = Column(JSON, default=lambda: {'telegram': True, 'inapp': True, 'email': False})
    telegram_token_enc = Column(Text)
    telegram_chat_id = Column(String(64))
    quiet_from = Column(String(5))     # HH:MM
    quiet_to = Column(String(5))
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    user = relationship('User')


class SignalLog(Base):
    """Every signal/trade a user saw — backbone of audit, insights, journal, debugger."""
    __tablename__ = 'signal_logs'
    id = Column(Integer, primary_key=True)
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
    id = Column(Integer, primary_key=True)
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
    status = Column(String(12), default='open', index=True)   # open | closed | cancelled
    mode = Column(String(8), default='paper')                  # paper | live
    source = Column(String(16), default='manual')              # signal | manual
    pnl = Column(Float)                      # realised ₹ when closed
    result_r = Column(Float)                 # realised R multiple when closed
    note = Column(Text)

    def risk_per_share(self):
        if self.entry and self.stop:
            return abs(self.entry - self.stop)
        return None

    def public(self, last_price=None):
        rps = self.risk_per_share()
        unreal = None
        if self.status == 'open' and last_price and self.qty:
            unreal = round((last_price - self.entry) * self.qty * (1 if self.side == 'LONG' else -1), 2)
        return {
            'id': self.id, 'created_at': self.created_at.isoformat() if self.created_at else None,
            'closed_at': self.closed_at.isoformat() if self.closed_at else None,
            'symbol': self.symbol, 'side': self.side, 'qty': self.qty,
            'entry': self.entry, 'stop': self.stop, 'target': self.target,
            'exit_price': self.exit_price, 'status': self.status, 'mode': self.mode,
            'source': self.source, 'pnl': self.pnl, 'result_r': self.result_r,
            'unrealized': unreal, 'note': self.note,
        }


class SmartPick(Base):
    """A daily smart-watchlist idea: one stock, with long and/or short plans + levels."""
    __tablename__ = 'smart_picks'
    id = Column(Integer, primary_key=True)
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
                'bias': self.bias, 'focus': bool(self.focus),
                'long_plan': self.long_plan, 'short_plan': self.short_plan, 'note': self.note}


class BrokerConnection(Base):
    """Per-user broker credentials. capability = 'data' or 'orders'; secret is encrypted."""
    __tablename__ = 'broker_connections'
    __table_args__ = (UniqueConstraint('user_id', 'broker', 'capability',
                                       name='uq_user_broker_capability'),)
    id = Column(Integer, primary_key=True)
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
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), index=True)
    kind = Column(String(16), default='question')   # question | issue | feature
    message = Column(Text)
    delivered = Column(Integer, default=0)          # 1 if Telegram delivery succeeded
    created_at = Column(DateTime, default=_now, index=True)
