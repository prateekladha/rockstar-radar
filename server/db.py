"""Database layer — SQLAlchemy. Three targets, chosen by env:
  - Oracle Autonomous DB (production on OKE): when DB_DSN is set, connect as a least-privilege app
    user over the ADB TLS (wallet-less) connect string. Portable SQLAlchemy types, so the SAME schema
    also runs on SQLite/Postgres.
  - Postgres (legacy single-VM): DATABASE_URL=postgresql+psycopg://...
  - SQLite (dev/tests): the default.
"""
from __future__ import annotations
import os
import time
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError
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
        # Paper→live parity (docs/PAPER_LIVE_PARITY.md)
        'gross_pnl': 'FLOAT',
        'charges': 'FLOAT DEFAULT 0',
        'margin_used': 'FLOAT',
        'exit_reason': 'VARCHAR(16)',
    },
    'alert_configs': {
        'smc_alerts_enabled': 'INTEGER DEFAULT 0',
        'smc_min_score': 'INTEGER DEFAULT 70',
    },
    'sim_runs': {
        'heartbeat_at': 'TIMESTAMP',   # liveness for the orphaned-run reconciler
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


# Rolling deploys start several pods at once (web replicas + scanner + sim-worker), and they all run
# these same ALTERs. A DB may then reject concurrent DDL (Oracle: ORA-14411) or the column may already
# have been added by a sibling pod (ORA-01430) — neither is fatal, but either used to abort startup and
# crash-loop the pod. So each ALTER runs in its own transaction with a bounded retry.
_MIGRATION_ATTEMPTS = 6
_MIGRATION_BACKOFF_S = 1.0


def _execute_ddl(eng, ddl: str) -> None:
    """Run one DDL statement in its own transaction (seam kept small so the retry is unit-testable)."""
    with eng.begin() as conn:
        conn.execute(text(ddl))


def _column_exists(eng, table: str, col: str) -> bool:
    """Fresh reflection (new Inspector each call) so we see a column a sibling pod just added."""
    return col.lower() in {c['name'].lower() for c in inspect(eng).get_columns(table)}


def _add_column_with_retry(eng, dialect: str, table: str, col: str, sqltype: str, *,
                           attempts: int = _MIGRATION_ATTEMPTS, backoff: float = _MIGRATION_BACKOFF_S) -> None:
    """Add one column, tolerating the rolling-deploy DDL race. Returns once the column exists (whether we
    or a sibling added it); re-raises only if it is genuinely still missing after all attempts — so a
    real schema error still surfaces instead of being silently swallowed."""
    ddl = _add_column_ddl(dialect, table, col, sqltype)
    for attempt in range(attempts):
        if _column_exists(eng, table, col):
            return                                   # present (we or a sibling added it) — done
        try:
            _execute_ddl(eng, ddl)
            return                                   # we added it
        except SQLAlchemyError:
            # A concurrent DDL / duplicate-column error is expected under a rolling deploy. On the last
            # attempt, only re-raise if the column is STILL absent (i.e. a genuine failure, not a race).
            if attempt == attempts - 1:
                if _column_exists(eng, table, col):
                    return
                raise
            time.sleep(backoff)                      # let the concurrent DDL / sibling finish, then retry


def _apply_additive_migrations() -> None:
    dialect = engine.dialect.name
    existing_tables = {t.lower() for t in inspect(engine).get_table_names()}
    for table, cols in _ADDED_COLUMNS.items():
        if table.lower() not in existing_tables:
            continue  # create_all will build it fresh with all columns
        for col, sqltype in cols.items():
            _add_column_with_retry(engine, dialect, table, col, sqltype)


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
