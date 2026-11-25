"""/api/activity returns the latest Order id and SignalLog id per user — the signal the nav uses to show
a 'new' dot on the Trades / Journal tabs (client compares to last-seen in localStorage)."""
import types
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from server.db import Base
from server.main import api_activity
from server.models import Order, SignalLog


class ActivityEndpointTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                                    poolclass=StaticPool, future=True)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, future=True)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    @staticmethod
    def _u(uid):
        return types.SimpleNamespace(id=uid)

    def test_latest_ids_per_user(self):
        self.db.add_all([Order(user_id=1), Order(user_id=1), Order(user_id=2), SignalLog(user_id=1)])
        self.db.commit()
        out1 = api_activity(user=self._u(1), db=self.db)
        self.assertEqual(out1['trades'], 2)   # user1's 2nd order
        self.assertEqual(out1['journal'], 1)  # user1's only journal row
        out2 = api_activity(user=self._u(2), db=self.db)
        self.assertEqual(out2['trades'], 3)   # user2's order
        self.assertEqual(out2['journal'], 0)  # user2 has no journal rows

    def test_empty_is_zero(self):
        self.assertEqual(api_activity(user=self._u(99), db=self.db), {'trades': 0, 'journal': 0})


if __name__ == '__main__':
    unittest.main()
