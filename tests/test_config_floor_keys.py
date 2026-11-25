"""The SMC stop-floor keys must be editable config, so the live settings UI (AutoTrade.jsx) can save
them via PATCH /api/settings -> validate_config_patch. Without the allowlist entry the save is rejected
('Unknown or protected config field')."""
import unittest

from radar.control import ControlError, validate_config_patch


class SmcFloorConfigKeysTest(unittest.TestCase):
    def test_floor_bool_and_mult_accepted(self):
        out = validate_config_patch({'smc_atr_stop_floor': True, 'smc_atr_stop_floor_mult': 1.0})
        self.assertEqual(out, {'smc_atr_stop_floor': True, 'smc_atr_stop_floor_mult': 1.0})

    def test_floor_coerces_bool_strings(self):
        self.assertEqual(validate_config_patch({'smc_atr_stop_floor': 'off'}), {'smc_atr_stop_floor': False})
        self.assertEqual(validate_config_patch({'smc_atr_stop_floor': 'on'}), {'smc_atr_stop_floor': True})

    def test_mult_range_enforced(self):
        with self.assertRaises(ControlError):
            validate_config_patch({'smc_atr_stop_floor_mult': 9})      # > 5.0
        with self.assertRaises(ControlError):
            validate_config_patch({'smc_atr_stop_floor_mult': -1})     # < 0.0


if __name__ == '__main__':
    unittest.main()
