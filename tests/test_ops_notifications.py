"""Two ops fixes (2026-11-25):

1. SMC opportunities must NOT be hard-gated by the ORB-style RVOL prerequisite. SMC is structural;
   its only volume figure is a cumulative-since-open RVOL that a mid-session scanner restart resets to
   ~0, which silently emptied the SMC radar for the rest of the day. ORB keeps the RVOL gate.
2. The reconnect reminder must use the user's OWN registered per-user Telegram bot (AlertConfig), not
   the shared SUPPORT_TELEGRAM_BOT_TOKEN (never provisioned on OKE).
"""
import types
import unittest
from unittest import mock

from server import notifications
from server.journaling import apply_prerequisite_filters


def _user(min_rvol=1.0, rvol_enabled=True):
    s = types.SimpleNamespace(
        prereq_min_rvol=min_rvol, prereq_rvol_enabled=1 if rvol_enabled else 0,
        prereq_min_liquidity_cr=None, prereq_min_price=None, prereq_max_price=None,
        prereq_allowed_sectors=None, prereq_blocked_symbols=None)
    return types.SimpleNamespace(settings=s, email='t@x.com', id=1)


class SmcRvolGateTest(unittest.TestCase):
    def test_smc_low_cumulative_rvol_is_kept(self):
        # rvol_cum 0.1 (e.g. reset by a mid-session restart) must NOT drop the SMC opportunity.
        opps = [{'symbol': 'NSE:PFC-EQ', 'price': 333.0, 'confluence': {'rvol_cum': 0.1}}]
        kept, rejected = apply_prerequisite_filters(opps, _user(min_rvol=1.0), strategy='SMC')
        self.assertEqual(len(kept), 1)
        self.assertEqual(rejected, 0)

    def test_smc_still_respects_price_bounds(self):
        # Decoupling RVOL must not disable the OTHER prereqs for SMC.
        u = _user(min_rvol=1.0)
        u.settings.prereq_min_price = 500.0   # price 333 < 500 -> real breach -> rejected
        opps = [{'symbol': 'NSE:PFC-EQ', 'price': 333.0, 'confluence': {'rvol_cum': 0.1}}]
        kept, rejected = apply_prerequisite_filters(opps, u, strategy='SMC')
        self.assertEqual(len(kept), 0)
        self.assertEqual(rejected, 1)

    def test_orb_low_rvol_still_rejected(self):
        opps = [{'symbol': 'NSE:X-EQ', 'price': 100.0, 'rvol': 0.1}]
        kept, rejected = apply_prerequisite_filters(opps, _user(min_rvol=1.0), strategy='ORB')
        self.assertEqual(len(kept), 0)
        self.assertEqual(rejected, 1)

    def test_orb_sufficient_rvol_kept(self):
        opps = [{'symbol': 'NSE:X-EQ', 'price': 100.0, 'rvol': 1.5}]
        kept, rejected = apply_prerequisite_filters(opps, _user(min_rvol=1.0), strategy='ORB')
        self.assertEqual(len(kept), 1)


class RemindReconnectTest(unittest.TestCase):
    def _db_returning(self, cfg):
        db = mock.MagicMock()
        db.query.return_value.filter_by.return_value.first.return_value = cfg
        return db

    def test_uses_per_user_bot_not_support_token(self):
        cfg = types.SimpleNamespace(telegram_token_enc=b'enc', telegram_chat_id='555')
        conn = types.SimpleNamespace(user=types.SimpleNamespace(id=1, email='t@x.com'))
        db = self._db_returning(cfg)
        with mock.patch('server.crypto.decrypt', return_value='PERUSERTOKEN') as dec, \
             mock.patch.object(notifications, 'send_telegram', return_value={'ok': True}) as send, \
             mock.patch.object(notifications, '_support_token', return_value='SHOULD_NOT_BE_USED'):
            sent = notifications.remind_reconnect(db, [conn])
        self.assertEqual(sent, 1)
        dec.assert_called_once_with(b'enc')
        _, kwargs = send.call_args
        self.assertEqual(kwargs['token'], 'PERUSERTOKEN')   # per-user bot token, not support
        self.assertEqual(kwargs['chat_id'], '555')

    def test_no_per_user_bot_means_no_send(self):
        cfg = types.SimpleNamespace(telegram_token_enc=None, telegram_chat_id=None)
        conn = types.SimpleNamespace(user=types.SimpleNamespace(id=1, email='t@x.com'))
        db = self._db_returning(cfg)
        with mock.patch('server.crypto.decrypt', return_value=''), \
             mock.patch.object(notifications, 'send_telegram') as send:
            sent = notifications.remind_reconnect(db, [conn])
        self.assertEqual(sent, 0)
        send.assert_not_called()


if __name__ == '__main__':
    unittest.main()
