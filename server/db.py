"""Database layer — SQLAlchemy. Three targets, chosen by env:
  - Oracle Autonomous DB (production on OKE): when DB_DSN is set, connect as a least-privilege app
    user over the ADB TLS (wallet-less) connect string. Portable SQLAlchemy types, so the SAME schema
    also runs on SQLite/Postgres.
  - Postgres (legacy single-VM): DATABASE_URL=postgresql+psycopg://...
  - SQLite (dev/tests): the default.
"""
from __future__ import annotations
import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import declarative_base, sessionmaker

ROOT = Path(__file__).resolve().parent.parent


def _build_engine():
    dsn = os.environ.get('DB_DSN')  # Oracle ADB TLS connect string (set on OKE; see deploy/helm)
    if dsn:
        url = URL.create('oracle+oracledb',
                         username=os.environ.get('DB_USER', 'ROCKSTAR_APP'),
                         password=os.environ.get('DB_APP_PASSWORD', ''))
        return create_engine(url, connect_args={'dsn': dsn}, pool_pre_ping=True,
                             pool_size=5, max_overflow=5, pool_recycle=1800, future=True)
    db_url = os.environ.get('DATABASE_URL', f'sqlite:///{ROOT / "data" / "radar.db"}')
    connect_args = {'check_same_thread': False} if db_url.startswith('sqlite') else {}
    return create_engine(db_url, connect_args=connect_args, pool_pre_ping=True, future=True)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


# Lightweight additive migrations: columns added to models after a table already exists.
# (SQLAlchemy create_all never ALTERs existing tables.) table -> {column: SQL type}.
_ADDED_COLUMNS = {
    'households': {
        'owner_user_id': 'INTEGER',
    },
    'users': {
        "trading_mode": "VARCHAR(8) DEFAULT 'paper'",
        'auto_paper_trade': 'INTEGER DEFAULT 0',
        'telegram_chat_id': 'VARCHAR(64)',
        'sim_enabled': 'INTEGER DEFAULT 0',
        "sim_start": "VARCHAR(5) DEFAULT '09:15'",
        "sim_end": "VARCHAR(5) DEFAULT '15:30'",
    },
    'broker_connections': {
        'refresh_enc': 'TEXT',
        'pin_enc': 'TEXT',
        'token_refreshed_at': 'TIMESTAMP',   # SQLite + Postgres both accept TIMESTAMP
    },
    'smart_picks': {
        "source": "VARCHAR(10) DEFAULT 'auto'",
        'user_id': 'INTEGER',
    },
    'signal_logs': {
        'day': 'VARCHAR(10)',
    },
    'orders': {
        'broker_order_id': 'VARCHAR(64)',
        "order_type": "VARCHAR(8) DEFAULT 'limit'",
        'fill_price': 'FLOAT',
        'filled_at': 'TIMESTAMP',
        'sim': 'INTEGER DEFAULT 0',
        'init_stop': 'FLOAT',
        'be_moved': 'INTEGER DEFAULT 0',
        'booked_qty': 'INTEGER DEFAULT 0',
        'booked_pnl': 'FLOAT DEFAULT 0',
        'features': 'TEXT',
    },
    'alert_configs': {
        'smc_alerts_enabled': 'INTEGER DEFAULT 0',
        'smc_min_score': 'INTEGER DEFAULT 70',
    },
    'settings': {
        # Prerequisite checks (mandatory before strategy evaluation) — PR #36
        'prereq_min_rvol': 'FLOAT DEFAULT 1.0',
        'prereq_rvol_enabled': 'INTEGER DEFAULT 1',
        'prereq_min_liquidity_cr': 'FLOAT',
        'prereq_min_price': 'FLOAT',
        'prereq_max_price': 'FLOAT',
        'prereq_allowed_sectors': 'TEXT',
        'prereq_blocked_symbols': 'TEXT',
        # RVOL calculation settings — PR #36
        "rvol_anchor_timeframe": "VARCHAR(16) DEFAULT 'day'",
        'rvol_length': 'INTEGER DEFAULT 10',
        "rvol_calculation_mode": "VARCHAR(16) DEFAULT 'cumulative'",
        # EMA crossover strategy settings
        'ema_fast_length': 'INTEGER DEFAULT 5',
        'ema_slow_length': 'INTEGER DEFAULT 20',
        "ema_source": "VARCHAR(8) DEFAULT 'close'",
        'ema_offset': 'INTEGER DEFAULT 0',
    },
}


def _add_column_ddl(dialect: str, table: str, col: str, sqltype: str) -> str:
    """Portable 'add a column' DDL. Oracle has no TEXT (→ CLOB) and its syntax is `ADD (col type)`
    with no COLUMN keyword; SQLite/Postgres use `ADD COLUMN col type`."""
    if dialect == 'oracle':
        return f'ALTER TABLE {table} ADD ({col} {sqltype.replace("TEXT", "CLOB")})'
    return f'ALTER TABLE {table} ADD COLUMN {col} {sqltype}'


def _apply_additive_migrations() -> None:
    insp = inspect(engine)
    dialect = engine.dialect.name
    existing_tables = {t.lower() for t in insp.get_table_names()}
    with engine.begin() as conn:
        for table, cols in _ADDED_COLUMNS.items():
            if table.lower() not in existing_tables:
                continue  # create_all will build it fresh with all columns
            have = {c['name'].lower() for c in insp.get_columns(table)}
            for col, sqltype in cols.items():
                if col.lower() not in have:
                    conn.execute(text(_add_column_ddl(dialect, table, col, sqltype)))


def init_db() -> None:
    (ROOT / 'data').mkdir(parents=True, exist_ok=True)
    from . import models  # noqa: F401 — register tables
    Base.metadata.create_all(engine)
    _apply_additive_migrations()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
