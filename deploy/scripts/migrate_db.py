#!/usr/bin/env python3
"""P6 cutover: copy all rows from the legacy Postgres DB into Oracle ADB, via the portable ORM models.

Because the schema is defined in portable SQLAlchemy types, `create_all` builds it on Oracle and we
copy row-by-row (not a Postgres dump, which Oracle can't load). Run once, during the cutover window,
after the ADB app user exists (see --bootstrap-user).

Env:
  SOURCE_DATABASE_URL   postgresql+psycopg://user:pw@host:5432/radar   (the current VM Postgres)
  DB_DSN                the Oracle ADB TLS connect string (terraform output / Vault db-dsn)
  DB_USER               app user (default ROCKSTAR_APP)
  DB_APP_PASSWORD       app user password (Vault db-app-password)
  DB_ADMIN_PASSWORD     ADB ADMIN password (only for --bootstrap-user)

Usage:
  python deploy/scripts/migrate_db.py --bootstrap-user   # as ADMIN: create the app user + grants
  python deploy/scripts/migrate_db.py                    # create_all on ADB + copy all rows
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import URL  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


def _tgt_engine(username: str, password: str):
    url = URL.create('oracle+oracledb', username=username, password=password)
    return create_engine(url, connect_args={'dsn': os.environ['DB_DSN']}, future=True)


def bootstrap_user():
    app_user = os.environ.get('DB_USER', 'ROCKSTAR_APP')
    app_pw = os.environ['DB_APP_PASSWORD']
    admin = _tgt_engine('ADMIN', os.environ['DB_ADMIN_PASSWORD'])
    with admin.begin() as c:
        exists = c.execute(text("SELECT 1 FROM all_users WHERE username = :u"),
                           {'u': app_user.upper()}).first()
        if not exists:
            c.execute(text(f'CREATE USER {app_user} IDENTIFIED BY "{app_pw}"'))
        c.execute(text(f'GRANT CONNECT, RESOURCE TO {app_user}'))
        c.execute(text(f'ALTER USER {app_user} QUOTA UNLIMITED ON DATA'))
    print(f'app user {app_user} ready')


def copy_rows():
    from server import models
    from server.db import Base
    src = create_engine(os.environ['SOURCE_DATABASE_URL'], future=True)
    tgt = _tgt_engine(os.environ.get('DB_USER', 'ROCKSTAR_APP'), os.environ['DB_APP_PASSWORD'])
    Base.metadata.create_all(tgt)  # build the Oracle schema from the portable models
    # FK-safe order: parents before children.
    order = [models.Household, models.User, models.BrokerConnection, models.Watchlist,
             models.Settings, models.AlertConfig, models.AlertDelivery, models.SignalLog,
             models.Order, models.SmartPick, models.SupportMessage]
    S, T = sessionmaker(bind=src, future=True)(), sessionmaker(bind=tgt, future=True)()
    try:
        for M in order:
            rows = S.query(M).all()
            for r in rows:
                T.merge(M(**{c.name: getattr(r, c.name) for c in M.__table__.columns}))
            T.commit()
            print(f'{M.__tablename__}: {len(rows)} rows')
    finally:
        S.close()
        T.close()
    print('done — verify row counts, then cut DNS over.')


if __name__ == '__main__':
    if '--bootstrap-user' in sys.argv:
        bootstrap_user()
    else:
        copy_rows()
