"""Orphaned-simulation reconciler: a sim whose executor pod dies must not hang 'running' forever.

Sims run as in-process FastAPI BackgroundTasks in the (multi-replica, often-redeployed) web pod, so a
restart silently orphans one. reconcile_orphaned_runs() fails a non-terminal run only when its liveness
heartbeat has gone stale (or it never started and is past grace) — never one still ticking on a sibling
replica. These tests also pin the mixed-timezone handling: heartbeat/started_at are written aware-IST
(now_ist()) while created_at is naive-UTC (models._now), and the reconciler must read both correctly.
"""
import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from radar.utils import IST, now_ist
from server.db import Base
from server.models import SimRun
from server.sim_controller import (reconcile_orphaned_runs, _SIM_HEARTBEAT_STALE_SECONDS,
                                    _SIM_PENDING_GRACE_SECONDS)


def _mk(**kw):
    base = dict(user_id=1, name='t', config='{}', start_date='2024-11-15', start_time='09:15',
                end_date='2024-11-15', end_time='15:30', bar_interval='5')
    base.update(kw)
    return SimRun(**base)


class SimReconcileTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                                    poolclass=StaticPool, future=True)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, future=True)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _get(self, rid):
        self.db.expire_all()
        return self.db.query(SimRun).get(rid)

    def test_fresh_heartbeat_survives(self):
        """A run actively stamping its heartbeat (aware-IST) is left alone."""
        r = _mk(status='running', heartbeat_at=now_ist(), progress_pct=30)
        self.db.add(r); self.db.commit()
        self.assertEqual(reconcile_orphaned_runs(self.db), 0)
        self.assertEqual(self._get(r.id).status, 'running')

    def test_stale_heartbeat_failed(self):
        """A 'running' run whose heartbeat went stale (pod died mid-replay) is failed."""
        stale = now_ist() - timedelta(seconds=_SIM_HEARTBEAT_STALE_SECONDS + 60)
        r = _mk(status='running', heartbeat_at=stale, progress_pct=40)
        self.db.add(r); self.db.commit()
        self.assertEqual(reconcile_orphaned_runs(self.db), 1)
        got = self._get(r.id)
        self.assertEqual(got.status, 'failed')
        self.assertIn('restart', got.error_message.lower())

    def test_pending_within_grace_survives(self):
        """Just-created run whose BackgroundTask hasn't stamped a heartbeat yet is not failed early."""
        r = _mk(status='pending', created_at=datetime.utcnow())  # naive UTC, like models._now
        self.db.add(r); self.db.commit()
        self.assertEqual(reconcile_orphaned_runs(self.db), 0)
        self.assertEqual(self._get(r.id).status, 'pending')

    def test_pending_past_grace_failed(self):
        """A run that never started (no heartbeat) and is past the grace window is orphaned -> failed."""
        old = datetime.utcnow() - timedelta(seconds=_SIM_PENDING_GRACE_SECONDS + 60)
        r = _mk(status='pending', created_at=old)
        self.db.add(r); self.db.commit()
        self.assertEqual(reconcile_orphaned_runs(self.db), 1)
        self.assertEqual(self._get(r.id).status, 'failed')

    def test_fetching_data_stale_failed(self):
        """'fetching_data' is also non-terminal and reconciled the same way."""
        stale = now_ist() - timedelta(seconds=_SIM_HEARTBEAT_STALE_SECONDS + 60)
        r = _mk(status='fetching_data', heartbeat_at=stale)
        self.db.add(r); self.db.commit()
        self.assertEqual(reconcile_orphaned_runs(self.db), 1)
        self.assertEqual(self._get(r.id).status, 'failed')

    def test_terminal_runs_untouched(self):
        """completed/failed runs are never revived or re-touched, even with an ancient heartbeat."""
        ancient = now_ist() - timedelta(hours=5)
        done = _mk(status='completed', heartbeat_at=ancient)
        failed = _mk(status='failed', heartbeat_at=ancient, error_message='orig')
        self.db.add_all([done, failed]); self.db.commit()
        self.assertEqual(reconcile_orphaned_runs(self.db), 0)
        self.assertEqual(self._get(done.id).status, 'completed')
        self.assertEqual(self._get(failed.id).error_message, 'orig')

    def test_naive_heartbeat_read_as_ist(self):
        """If the DB returns heartbeat_at naive (tz stripped), it's read as IST — a fresh naive stamp
        must still count as alive, not be misread as hours off and failed."""
        r = _mk(status='running', heartbeat_at=now_ist().replace(tzinfo=None))
        self.db.add(r); self.db.commit()
        self.assertEqual(reconcile_orphaned_runs(self.db), 0)
        self.assertEqual(self._get(r.id).status, 'running')


if __name__ == '__main__':
    unittest.main()
