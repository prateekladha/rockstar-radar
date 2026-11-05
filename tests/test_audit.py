import unittest
from datetime import date
from radar.models import Candle
from radar.audit import eval_after_signal
from radar.utils import market_dt

DAY=date(2026,11,4)

class AuditTests(unittest.TestCase):
    def test_long_target_first(self):
        start=market_dt(DAY,'09:30')
        c=[Candle(start,1005,1020,1004,1012,40000)]
        status,price,r=eval_after_signal('LONG',1005,1002,1016,start,c,.15,market_dt(DAY,'15:15'))
        self.assertEqual(status,'TARGET_FIRST')
        self.assertGreater(r,2)

    def test_stop_first_when_both_touch(self):
        start=market_dt(DAY,'09:30')
        c=[Candle(start,1005,1020,1000,1010,40000)]
        status,_,r=eval_after_signal('LONG',1005,1002,1015,start,c,.15,market_dt(DAY,'15:15'))
        self.assertEqual(status,'STOP_FIRST')
        self.assertLess(r,0)

    def test_short_stop_first(self):
        start=market_dt(DAY,'09:30')
        c=[Candle(start,556,559,553,557,60000)]
        status,price,r=eval_after_signal('SHORT',556,558,548,start,c,.15,market_dt(DAY,'15:15'))
        self.assertEqual(status,'STOP_FIRST')

    def test_no_candle_no_invented_outcome(self):
        start=market_dt(DAY,'09:30')
        status,price,r=eval_after_signal('LONG',1005,1002,1015,start,[],.15,market_dt(DAY,'15:15'))
        self.assertEqual(status,'INCOMPLETE')
        self.assertIsNone(r)

if __name__ == '__main__':
    unittest.main()
