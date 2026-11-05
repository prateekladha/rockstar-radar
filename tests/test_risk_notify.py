"""Position sizing, Telegram ticket formatting, and snapshot risk fields (Phase 2)."""
import os
import unittest
from datetime import date
from unittest.mock import patch

from radar import notify
from radar.engine import RadarEngine
from radar.models import Instrument, Signal, Tick
from radar.risk import position_size
from radar.utils import load_config, market_dt


class PositionSizeTests(unittest.TestCase):
    def test_basic_sizing(self):
        s = position_size(101.0, 100.0, 600000, 1.0)
        self.assertEqual(s['risk_budget'], 6000.0)
        self.assertEqual(s['qty'], 6000)          # 6000 budget / ₹1 per-share risk
        self.assertEqual(s['actual_risk'], 6000.0)

    def test_tighter_stop_more_qty(self):
        s = position_size(100.0, 99.5, 600000, 1.0)
        self.assertEqual(s['qty'], 12000)         # 6000 / 0.5
        self.assertEqual(s['actual_risk'], 6000.0)

    def test_zero_stop_distance_sizes_zero(self):
        s = position_size(100.0, 100.0, 600000, 1.0)
        self.assertEqual(s['qty'], 0)

    def test_missing_prices_sizes_zero_but_keeps_budget(self):
        s = position_size(None, None, 600000, 1.0)
        self.assertEqual(s['qty'], 0)
        self.assertEqual(s['risk_budget'], 6000.0)

    def test_half_percent_risk(self):
        s = position_size(200.0, 198.0, 600000, 0.5)
        self.assertEqual(s['risk_budget'], 3000.0)
        self.assertEqual(s['qty'], 1500)          # 3000 / 2.0


def _sig(state, **kw):
    base = dict(time='2026-11-05 10:00:00', symbol='NSE:BHARTIARTL-EQ', side='LONG',
                state=state, score=80, price=101.2, rvol=2.0, note='x', level=101.0)
    base.update(kw)
    return Signal(**base)


class NotifyTests(unittest.TestCase):
    CFG = {'capital_inr': 600000, 'risk_pct': 1.0}

    def test_ticket_has_qty_and_rupee_risk(self):
        msg = notify.format_ticket(
            _sig('RETEST_READY', entry=101.0, stop=100.0, target=105.0, net_rr=3.6), self.CFG)
        self.assertIn('RETEST READY', msg)
        self.assertIn('Qty', msg)
        self.assertIn('6000', msg)                # qty
        self.assertIn('₹', msg)

    def test_provisional_tag_in_ticket(self):
        msg = notify.format_ticket(
            _sig('RETEST_READY', entry=101.0, stop=100.0, target=105.0, net_rr=3.6,
                 provisional=True), self.CFG)
        self.assertIn('PROVISIONAL', msg)

    def test_notify_noop_when_unconfigured(self):
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(notify, 'send_telegram') as spy:
            notify.notify_signal(_sig('RETEST_READY', entry=101, stop=100, target=105), self.CFG)
            spy.assert_not_called()

    def test_notify_sends_when_configured_and_actionable(self):
        env = {'TELEGRAM_BOT_TOKEN': 't', 'TELEGRAM_CHAT_ID': '42'}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(notify, 'send_telegram', return_value={'ok': True}) as spy:
            notify.notify_signal(_sig('RETEST_READY', entry=101, stop=100, target=105), self.CFG)
            spy.assert_called_once()

    def test_notify_skips_noisy_states(self):
        env = {'TELEGRAM_BOT_TOKEN': 't', 'TELEGRAM_CHAT_ID': '42'}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(notify, 'send_telegram') as spy:
            notify.notify_signal(_sig('WATCH'), self.CFG)
            spy.assert_not_called()


class SnapshotRiskTests(unittest.TestCase):
    def test_snapshot_row_includes_qty_and_risk(self):
        cfg = dict(load_config(), capital_inr=600000, risk_pct=1.0)
        e = RadarEngine([Instrument('NSE:SBIN-EQ', 'Banks', 150, 1.5, 100)], cfg,
                        date(2026, 11, 5), mode='SIMULATION')
        st = e.states['NSE:SBIN-EQ']
        st.state = 'RETEST_READY'; st.entry = 101.0; st.stop = 100.0; st.target = 105.0
        st.last_tick = Tick('NSE:SBIN-EQ', 101.2, market_dt(date(2026, 11, 5), '10:00'))
        row = [r for r in e.snapshot(market_dt(date(2026, 11, 5), '10:00'))['all']
               if r['symbol'] == 'NSE:SBIN-EQ'][0]
        self.assertEqual(row['qty'], 6000)
        self.assertEqual(row['risk_amount'], 6000.0)


if __name__ == '__main__':
    unittest.main()
