"""The intraday square-off time is a configurable, per-user setting (default 15:00), not a hardcoded
15:15. It must be an editable config key (so PATCH /api/settings accepts it) and validate as HH:MM,
and the shipped default must be 15:00."""
import json
import os
import unittest

from radar.control import ControlError, validate_config_patch


class SquareOffConfigTest(unittest.TestCase):
    def test_square_off_time_is_editable_and_time_validated(self):
        self.assertEqual(validate_config_patch({'square_off_time': '15:00'}), {'square_off_time': '15:00'})
        self.assertEqual(validate_config_patch({'square_off_time': '14:45'}), {'square_off_time': '14:45'})

    def test_bad_square_off_time_rejected(self):
        with self.assertRaises(ControlError):
            validate_config_patch({'square_off_time': '25:99'})      # not a valid HH:MM
        with self.assertRaises(ControlError):
            validate_config_patch({'square_off_time': 'later'})

    def test_shipped_default_is_1500(self):
        cfg = json.loads(open(os.path.join(os.path.dirname(__file__), '..', 'config.json'),
                              encoding='utf-8').read())
        self.assertEqual(cfg.get('square_off_time'), '15:00')


if __name__ == '__main__':
    unittest.main()
