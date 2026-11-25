"""/api/settings must only expose EDITABLE_CONFIG keys.

A non-editable key that happens to live in settings.data (e.g. sim_speed, which the Preferences page
manages via /api/me) used to be echoed back verbatim, and the settings-grid Save then re-sent it to
PATCH /api/settings -> validate_config_patch -> "Unknown or protected config field: sim_speed", which
blocked saving any strategy/risk setting.
"""
import types
import unittest

from radar.control import EDITABLE_CONFIG
from server.main import api_get_settings


class SettingsLeakTest(unittest.TestCase):
    def test_non_editable_key_filtered_out(self):
        user = types.SimpleNamespace(settings=types.SimpleNamespace(
            data={'sim_speed': 10.0, 'capital_inr': 196000.0, 'risk_pct': 1.0}))
        out = api_get_settings(user)
        self.assertNotIn('sim_speed', out)                        # the leaked sim key is gone
        self.assertEqual(out['capital_inr'], 196000.0)            # editable overrides preserved
        self.assertEqual(out['risk_pct'], 1.0)
        self.assertTrue(set(out).issubset(set(EDITABLE_CONFIG)))  # nothing outside the allowlist

    def test_no_settings_row(self):
        user = types.SimpleNamespace(settings=None)
        out = api_get_settings(user)
        self.assertTrue(set(out).issubset(set(EDITABLE_CONFIG)))


if __name__ == '__main__':
    unittest.main()
