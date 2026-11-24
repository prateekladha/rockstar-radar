"""sim-worker claim logic: the dedicated worker pod claims 'pending' SimRun rows atomically and runs
them off the web pod. These tests pin the claim contract — oldest-first, exactly-once, idempotent when
the queue is empty — which is what makes the worker safe to restart (it just re-claims) and safe even if
more than one ever runs."""
import time
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.db import Base
from server.models import SimRun
from server.sim_worker import claim_next


def _mk(**kw):
    base = dict(user_id=1, name='t', config='{}', start_date='2024-11-15', start_time='09:15',
                end_date='2024-11-15', end_time='15:30', bar_interval='5', status='pending')
    base.update(kw)
    return SimRun(**base)


class SimWorkerClaimTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                                    poolclass=StaticPool, future=True)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, future=True)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_empty_queue_returns_none(self):
        self.assertIsNone(claim_next(self.db))

    def test_claims_and_flips_status(self):
        r = _mk()
        self.db.add(r); self.db.commit()
        claim = claim_next(self.db)
        self.assertEqual(claim, (r.id, 1))
        self.db.expire_all()
        got = self.db.query(SimRun).get(r.id)
        self.assertEqual(got.status, 'fetching_data')          # no longer claimable as pending
        self.assertIsNotNone(got.heartbeat_at)                 # fresh heartbeat so it isn't seen orphaned
        self.assertIsNotNone(got.started_at)

    def test_only_pending_is_claimed(self):
        self.db.add_all([_mk(status='running'), _mk(status='completed'), _mk(status='failed')])
        self.db.commit()
        self.assertIsNone(claim_next(self.db))                 # nothing 'pending'

    def test_oldest_first_and_exactly_once(self):
        first = _mk(name='first'); self.db.add(first); self.db.commit()
        time.sleep(0.01)                                        # distinct created_at ordering
        second = _mk(name='second'); self.db.add(second); self.db.commit()
        c1 = claim_next(self.db)
        c2 = claim_next(self.db)
        c3 = claim_next(self.db)
        self.assertEqual(c1, (first.id, 1))                    # oldest first
        self.assertEqual(c2, (second.id, 1))                   # then the next — never the same row twice
        self.assertIsNone(c3)                                   # queue drained


if __name__ == '__main__':
    unittest.main()
