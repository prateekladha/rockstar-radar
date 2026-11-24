"""Additive-migration DDL race hardening (server/db._add_column_with_retry).

Rolling deploys start several pods at once and they all run the same `ALTER TABLE ... ADD COLUMN`.
A DB may reject concurrent DDL (Oracle ORA-14411) or the column may already exist (ORA-01430). Those
used to crash startup and crash-loop the pod. These tests pin the contract: idempotent, retries through
a transient race, treats a sibling-added column as success, and still RAISES a genuine failure (so we
never silently run without a column the app needs).
"""
import unittest
from unittest import mock

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from sqlalchemy.pool import StaticPool

from server import db as dbmod


class AddColumnWithRetryTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                                    poolclass=StaticPool, future=True)
        with self.engine.begin() as c:
            c.execute(text('CREATE TABLE t (a INTEGER)'))

    def tearDown(self):
        self.engine.dispose()

    def _cols(self):
        return {c['name'].lower() for c in inspect(self.engine).get_columns('t')}

    def test_adds_missing_column(self):
        dbmod._add_column_with_retry(self.engine, 'sqlite', 't', 'newcol', 'INTEGER', backoff=0)
        self.assertIn('newcol', self._cols())

    def test_idempotent_when_present(self):
        dbmod._add_column_with_retry(self.engine, 'sqlite', 't', 'a', 'INTEGER', backoff=0)  # already there
        self.assertEqual(sum(1 for c in self._cols() if c == 'a'), 1)  # not duplicated, no raise

    def test_retries_then_succeeds(self):
        real = dbmod._execute_ddl
        calls = {'n': 0}

        def flaky(eng, ddl):
            calls['n'] += 1
            if calls['n'] < 3:                       # first two attempts hit the "concurrent DDL" race
                raise OperationalError('ALTER', {}, Exception('ORA-14411: concurrent DDL'))
            real(eng, ddl)                           # third attempt wins

        with mock.patch.object(dbmod, '_execute_ddl', flaky):
            dbmod._add_column_with_retry(self.engine, 'sqlite', 't', 'c', 'INTEGER', attempts=6, backoff=0)
        self.assertIn('c', self._cols())
        self.assertEqual(calls['n'], 3)

    def test_sibling_added_during_our_failure(self):
        """Our ALTER errors, but the column appears (a sibling pod won) -> treat as success, don't raise."""
        real = dbmod._execute_ddl

        def loser(eng, ddl):
            real(eng, ddl)                           # actually add it (the "sibling")...
            raise OperationalError('ALTER', {}, Exception('ORA-01430: column already exists'))  # ...then error

        with mock.patch.object(dbmod, '_execute_ddl', loser):
            # Must NOT raise: after the error, _column_exists is True on the next iteration.
            dbmod._add_column_with_retry(self.engine, 'sqlite', 't', 'c', 'INTEGER', attempts=3, backoff=0)
        self.assertIn('c', self._cols())

    def test_genuine_failure_reraises(self):
        """A real, persistent failure (column never appears) must surface, not be swallowed."""
        def always_fail(eng, ddl):
            raise OperationalError('ALTER', {}, Exception('ORA-00902: invalid datatype'))

        with mock.patch.object(dbmod, '_execute_ddl', always_fail):
            with self.assertRaises(SQLAlchemyError):
                dbmod._add_column_with_retry(self.engine, 'sqlite', 't', 'c', 'INTEGER', attempts=3, backoff=0)
        self.assertNotIn('c', self._cols())


if __name__ == '__main__':
    unittest.main()
