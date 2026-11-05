"""Control Center backend logic + API smoke tests (Phase 2)."""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import radar.control as control_mod
from radar.control import ControlCenter, ControlError
from radar.selecting import SelectionError
from radar.utils import ROOT


class ControlLogicTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / 'data').mkdir()
        shutil.copy(ROOT / 'config.json', self.tmp / 'config.json')
        self.c = ControlCenter(config_path=self.tmp / 'config.json', root=self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---- config ----
    def test_update_config_valid_persists(self):
        out = self.c.update_config({'min_price_inr': 250, 'min_confirm_rvol': 1.8})
        self.assertEqual(out['min_price_inr'], 250)
        self.assertEqual(out['min_confirm_rvol'], 1.8)
        saved = json.loads((self.tmp / 'config.json').read_text())
        self.assertEqual(saved['min_price_inr'], 250)

    def test_update_config_rejects_unknown_key(self):
        with self.assertRaises(ControlError):
            self.c.update_config({'universe_url': 'http://evil'})

    def test_update_config_rejects_out_of_range(self):
        with self.assertRaises(ControlError):
            self.c.update_config({'max_symbols': 500})      # cap is 100

    def test_update_config_rejects_bad_time(self):
        with self.assertRaises(ControlError):
            self.c.update_config({'new_signals_stop': '25:99'})

    def test_update_config_accepts_valid_time(self):
        out = self.c.update_config({'new_signals_stop': '14:00'})
        self.assertEqual(out['new_signals_stop'], '14:00')

    def test_update_config_rejects_min_gt_max_atr(self):
        with self.assertRaises(ControlError):
            self.c.update_config({'min_daily_atr_pct': 7, 'max_daily_atr_pct': 6})

    # ---- watchlist ----
    def test_set_watchlist_validates_and_dedupes(self):
        out = self.c.set_watchlist(['BHARTIARTL', 'mcx', 'BHARTIARTL', '  SBIN '])
        self.assertEqual(out['resolved'],
                         ['NSE:BHARTIARTL-EQ', 'NSE:MCX-EQ', 'NSE:SBIN-EQ'])
        self.assertIn('BHARTIARTL', (self.tmp / 'data' / 'morning_rockstars.txt').read_text())

    def test_set_watchlist_rejects_invalid_symbol(self):
        with self.assertRaises(SelectionError):
            self.c.set_watchlist(['BHARTIARTL', 'not a ticker!!'])

    def test_get_watchlist_strips_comment_lines(self):
        (self.tmp / 'data' / 'morning_rockstars.txt').write_text(
            '# header comment\nBHARTIARTL\nMCX  # inline note\n')
        w = self.c.get_watchlist()
        self.assertEqual(w['symbols'], ['BHARTIARTL', 'MCX'])
        self.assertEqual(w['resolved'], ['NSE:BHARTIARTL-EQ', 'NSE:MCX-EQ'])

    # ---- login ----
    def test_auth_url_builds_and_persists_state(self):
        state_file = self.tmp / 'data' / '.state'
        with patch.dict(os.environ, {'FYERS_APP_ID': 'ABC-100', 'FYERS_APP_SECRET': 's',
                                     'FYERS_REDIRECT_URI': 'http://127.0.0.1:8765/auth/callback'}), \
             patch.object(control_mod, '_STATE_PATH', state_file):
            url = self.c.auth_url()
        self.assertIn('client_id=ABC-100', url)
        self.assertIn('callback', url)  # redirect_uri is URL-encoded (auth%2Fcallback)
        self.assertTrue(state_file.exists())

    def test_complete_login_without_pending_state_errors(self):
        state_file = self.tmp / 'data' / '.nostate'
        with patch.dict(os.environ, {'FYERS_APP_ID': 'ABC-100', 'FYERS_APP_SECRET': 's',
                                     'FYERS_REDIRECT_URI': 'http://x/cb'}), \
             patch.object(control_mod, '_STATE_PATH', state_file):
            with self.assertRaises(ControlError):
                self.c.complete_login('http://x/cb?auth_code=z&state=q')

    # ---- capital / risk config ----
    def test_update_config_capital_and_risk(self):
        out = self.c.update_config({'capital_inr': 500000, 'risk_pct': 0.5})
        self.assertEqual(out['capital_inr'], 500000)
        self.assertEqual(out['risk_pct'], 0.5)

    def test_update_config_rejects_risk_over_ceiling(self):
        with self.assertRaises(ControlError):
            self.c.update_config({'risk_pct': 25})      # ceiling is 10

    # ---- telegram ----
    def test_set_telegram_persists_and_status(self):
        with patch.dict(os.environ, {}, clear=False):
            st = self.c.set_telegram('123:ABC', '42')
            self.assertTrue(st['bot_token_present'])
            self.assertEqual(st['chat_id'], '42')
            self.assertIn('TELEGRAM_CHAT_ID=42', (self.tmp / '.env').read_text())

    # ---- scanner status ----
    def test_scanner_status_not_running_by_default(self):
        s = self.c.scanner_status()
        self.assertFalse(s['running'])
        self.assertIsNone(s['pid'])

    def test_live_state_offline_when_not_running(self):
        st = self.c.live_state()
        self.assertTrue(st['offline'])


class ApiSmokeTests(unittest.TestCase):
    """Light end-to-end via FastAPI TestClient against the real repo files (no network)."""
    def setUp(self):
        from fastapi.testclient import TestClient
        from radar.api import app
        self.client = TestClient(app)

    def test_index_serves_html(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Rockstar', r.text)
        self.assertIn('app.css', r.text)   # design-system stylesheet linked

    def test_index_is_server_side_rendered(self):
        # SSR proof: config fields + watchlist are baked into the HTML by the server,
        # not fetched client-side. The page should already contain the settings inputs
        # and the current min_price_inr value.
        r = self.client.get('/')
        self.assertIn('name="min_price_inr"', r.text)
        self.assertIn('Morning Rockstar watchlist', r.text)
        # a value from config.json must be present in the rendered input
        import json as _json
        price = _json.loads((ROOT / 'config.json').read_text())['min_price_inr']
        self.assertIn(f'value="{price}"', r.text)

    def test_status_endpoint_shape(self):
        r = self.client.get('/api/status')
        self.assertEqual(r.status_code, 200)
        j = r.json()
        self.assertIn('connection', j)
        self.assertIn('scanner', j)
        self.assertIn('running', j['scanner'])

    def test_config_endpoint_returns_editable_fields(self):
        r = self.client.get('/api/config')
        self.assertEqual(r.status_code, 200)
        self.assertIn('min_price_inr', r.json())

    def test_config_patch_rejects_unknown_key(self):
        r = self.client.patch('/api/config', json={'universe_url': 'http://evil'})
        self.assertEqual(r.json().get('error', '')[:7], 'Unknown')

    def test_state_endpoint_offline_when_scanner_down(self):
        # Scanner isn't started in tests; state should report offline, not crash.
        r = self.client.get('/api/state')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json().get('offline'))


if __name__ == '__main__':
    unittest.main()
