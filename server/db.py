"""Database layer — SQLAlchemy. SQLite for dev/single-VM, Postgres-ready via DATABASE_URL."""
from __future__ import annotations
import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

ROOT = Path(__file__).resolve().parent.parent
DB_URL = os.environ.get('DATABASE_URL', f'sqlite:///{ROOT / "data" / "radar.db"}')

_connect_args = {'check_same_thread': False} if DB_URL.startswith('sqlite') else {}
engine = create_engine(DB_URL, connect_args=_connect_args, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


# Lightweight additive migrations: columns added to models after a table already exists.
# (SQLAlchemy create_all never ALTERs existing tables.) table -> {column: SQL type}.
_ADDED_COLUMNS = {
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
    },
}


def _apply_additive_migrations() -> None:
    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    with engine.begin() as conn:
        for table, cols in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue  # create_all will build it fresh with all columns
            have = {c['name'] for c in insp.get_columns(table)}
            for col, sqltype in cols.items():
                if col not in have:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {col} {sqltype}'))


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
