"""Unit tests for server.trade_features (feature logging extractor)."""
import unittest
from types import SimpleNamespace

from server.trade_features import record_features, feature_row


def order(**kw):
    base = dict(features=None, status='closed', pnl=None, result_r=None,
                symbol='NSE:X-EQ', side='LONG', source='auto_smc')
    base.update(kw)
    return SimpleNamespace(**base)


class TradeFeatureTests(unittest.TestCase):
    def test_record_then_extract_winner(self):
        o = order(status='open')
        record_features(o, {'score': 84.0, 'components': {'zone': 20}})
        self.assertIn('"score"', o.features)
        o.status, o.pnl, o.result_r = 'closed', 320.0, 1.8
        row = feature_row(o)
        self.assertEqual(row['score'], 84.0)
        self.assertEqual(row['pnl'], 320.0)
        self.assertTrue(row['won'])
        self.assertEqual(row['side'], 'LONG')

    def test_loser_flagged(self):
        o = order(pnl=-150.0)
        record_features(o, {'score': 81})
        row = feature_row(o)
        self.assertFalse(row['won'])

    def test_open_order_not_exported(self):
        o = order(status='open')
        record_features(o, {'score': 81})
        self.assertIsNone(feature_row(o))

    def test_no_features_returns_none(self):
        self.assertIsNone(feature_row(order(features=None)))

    def test_bad_json_returns_none(self):
        self.assertIsNone(feature_row(order(features='{not json')))


if __name__ == '__main__':
    unittest.main()
