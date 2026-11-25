"""Oracle native-JSON Decimal hardening (server.db.DecimalSafeJSON + _decimals_to_float).

Oracle 23ai returns JSON number scalars as decimal.Decimal (via python-oracledb); the rest of the app
assumes float. A stray Decimal both broke float arithmetic (radar.risk.position_size -> 500 on the
Telegram test and every live signal alert) and was not JSON-serializable on the next write (500 on
saving settings). SQLite (dev/tests) returns plain floats, so the suite never caught it. These tests
pin the contract: Decimals coerce to float on both read and write, nested, and non-numbers untouched.
"""
import json
import unittest
from decimal import Decimal

from sqlalchemy import Column, Integer, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from server.db import DecimalSafeJSON, _decimals_to_float, _json_serializer


class DecimalsToFloatTest(unittest.TestCase):
    def test_scalar(self):
        self.assertEqual(_decimals_to_float(Decimal('1.5')), 1.5)
        self.assertIsInstance(_decimals_to_float(Decimal('196000')), float)

    def test_nested(self):
        out = _decimals_to_float({'a': Decimal('1'), 'b': [Decimal('2.5'), {'c': Decimal('3')}]})
        self.assertEqual(out, {'a': 1.0, 'b': [2.5, {'c': 3.0}]})

    def test_non_numbers_untouched(self):
        payload = {'x': 'paper', 'y': True, 'z': None, 'n': 5}
        self.assertEqual(_decimals_to_float(payload), payload)

    def test_json_serializer_tolerates_decimal(self):
        # plain json.dumps raises "Object of type Decimal is not JSON serializable"; ours must not.
        self.assertEqual(json.loads(_json_serializer({'capital_inr': Decimal('196000')})),
                         {'capital_inr': 196000.0})

    def test_result_value_coerces_like_oracle(self):
        # Simulate python-oracledb handing back a dict with Decimal scalars from a native JSON column.
        t = DecimalSafeJSON()
        self.assertEqual(t.process_result_value({'risk_pct': Decimal('1')}, None), {'risk_pct': 1.0})


class DecimalSafeJSONColumnTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False},
                                    poolclass=StaticPool, future=True,
                                    json_serializer=_json_serializer)
        self.Base = declarative_base()

        class Row(self.Base):
            __tablename__ = 'r'
            id = Column(Integer, primary_key=True)
            data = Column(DecimalSafeJSON)

        self.Row = Row
        self.Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, future=True)

    def tearDown(self):
        self.engine.dispose()

    def test_write_then_read_decimals_as_float(self):
        # The exact prod shape: a config blob with Decimal values must save (no 500) and read as float.
        s = self.Session()
        s.add(self.Row(id=1, data={'capital_inr': Decimal('196000'), 'risk_pct': Decimal('1'),
                                   'nested': [Decimal('2.5')], 'mode': 'paper'}))
        s.commit()
        s.close()
        s2 = self.Session()
        got = s2.get(self.Row, 1).data
        s2.close()
        self.assertEqual(got['capital_inr'], 196000.0)
        self.assertIsInstance(got['capital_inr'], float)
        self.assertEqual(got['risk_pct'], 1.0)
        self.assertEqual(got['nested'], [2.5])
        self.assertEqual(got['mode'], 'paper')


if __name__ == '__main__':
    unittest.main()
