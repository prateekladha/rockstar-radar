import unittest
from datetime import date
from radar.fyers import FyersAdapter
from radar.models import Candle
from radar.utils import market_dt


class FakeLimiter:
    def acquire(self):
        pass


class FakeClient:
    def __init__(self):
        self.quote_batches = []
        self.history_calls = []
    def quotes(self, data):
        symbols = data['symbols'].split(',')
        self.quote_batches.append(symbols)
        return {'s':'ok', 'code':200, 'd':[
            {'s':'ok','n':s,'v':{'lp':325.3,'prev_close_price':320}}
            for s in symbols]}
    def history(self, data):
        self.history_calls.append(data)
        at=int(market_dt(date(2026,11,4),'09:15').timestamp())
        return {'s':'ok','code':200, 'candles':[[at, 325, 328, 324, 327, 450000]]}


class AdapterTests(unittest.TestCase):
    def test_quote_batches_no_more_than_50(self):
        adapter=FyersAdapter.__new__(FyersAdapter)
        adapter.limit=FakeLimiter();adapter.client=FakeClient()
        symbols=[f'NSE:ABC{i}-EQ' for i in range(100)]
        result=adapter.quotes(symbols)
        self.assertEqual(len(result),100)
        self.assertEqual(list(map(len,adapter.client.quote_batches)),[50,50])

    def test_historical_candle_data_shape(self):
        adapter=FyersAdapter.__new__(FyersAdapter)
        adapter.limit=FakeLimiter();adapter.client=FakeClient()
        result=adapter.history('NSE:SBIN-EQ','5',100,200)
        self.assertEqual(len(result),1)
        self.assertIsInstance(result[0],Candle)
        self.assertEqual(result[0].at.hour,9)
        self.assertEqual(result[0].volume,450000)
        self.assertEqual(adapter.client.history_calls[0]['resolution'],'5')

if __name__=='__main__':
    unittest.main()
