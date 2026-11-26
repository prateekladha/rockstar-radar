"""No NEW auto-trade entries after a configurable per-user cutoff (default 14:30 IST).

The cutoff gates ENTRIES only — it must not touch exits or the square-off — and it must be an
editable, HH:MM-validated config key so PATCH /api/settings accepts a per-user override. Sim mode
runs on an accelerated/arbitrary wall clock, so the real-time cutoff never applies there."""
import json
import os
import unittest
from datetime import datetime
from unittest.mock import patch

from radar.control import ControlError, validate_config_patch
from server.order_engine import _entries_cut_off


def _at(hhmm: str):
    h, m = (int(x) for x in hhmm.split(':'))
    return datetime(2026, 11, 26, h, m, 0)


class NewTradeCutoffConfigTest(unittest.TestCase):
    def test_editable_and_time_validated(self):
        self.assertEqual(validate_config_patch({'new_trade_cutoff': '14:30'}), {'new_trade_cutoff': '14:30'})
        self.assertEqual(validate_config_patch({'new_trade_cutoff': '13:15'}), {'new_trade_cutoff': '13:15'})

    def test_bad_cutoff_rejected(self):
        with self.assertRaises(ControlError):
            validate_config_patch({'new_trade_cutoff': '26:10'})
        with self.assertRaises(ControlError):
            validate_config_patch({'new_trade_cutoff': 'noon'})

    def test_shipped_default_is_1430(self):
        cfg = json.loads(open(os.path.join(os.path.dirname(__file__), '..', 'config.json'),
                              encoding='utf-8').read())
        self.assertEqual(cfg.get('new_trade_cutoff'), '14:30')


class EntriesCutOffTest(unittest.TestCase):
    CFG = {'new_trade_cutoff': '14:30'}

    def test_entries_allowed_before_cutoff(self):
        with patch('radar.utils.now_ist', return_value=_at('14:29')):
            self.assertFalse(_entries_cut_off({}, self.CFG, sim=False))

    def test_entries_blocked_at_and_after_cutoff(self):
        with patch('radar.utils.now_ist', return_value=_at('14:30')):
            self.assertTrue(_entries_cut_off({}, self.CFG, sim=False))
        with patch('radar.utils.now_ist', return_value=_at('15:05')):
            self.assertTrue(_entries_cut_off({}, self.CFG, sim=False))

    def test_per_user_override_beats_global(self):
        sdata = {'new_trade_cutoff': '13:00'}
        with patch('radar.utils.now_ist', return_value=_at('13:30')):
            self.assertTrue(_entries_cut_off(sdata, self.CFG, sim=False))   # past the user's earlier cutoff
        sdata = {'new_trade_cutoff': '15:00'}
        with patch('radar.utils.now_ist', return_value=_at('14:40')):
            self.assertFalse(_entries_cut_off(sdata, self.CFG, sim=False))  # user pushed it later

    def test_sim_always_bypasses_cutoff(self):
        with patch('radar.utils.now_ist', return_value=_at('15:30')):
            self.assertFalse(_entries_cut_off({}, self.CFG, sim=True))

    def test_falls_back_to_1430_when_unset(self):
        with patch('radar.utils.now_ist', return_value=_at('14:31')):
            self.assertTrue(_entries_cut_off({}, {}, sim=False))
        with patch('radar.utils.now_ist', return_value=_at('14:29')):
            self.assertFalse(_entries_cut_off({}, {}, sim=False))


if __name__ == '__main__':
    unittest.main()
