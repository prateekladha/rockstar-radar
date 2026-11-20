"""SMC auto-trade plan derivation (radar.smc_engine.derive_smc_trade_plan).

Covers the product rules: LONG in discount / SHORT in premium, only inside a fresh (unmitigated)
order block, with the stop beyond the block, a swing/extreme target, and net reward:risk after
costs. The order engine then enforces the 2:1 R:R gate and sizing.
"""
import unittest
from datetime import datetime
from types import SimpleNamespace

from radar.models import SMCOrderBlock, SMCPivot, SMCZone
from radar.smc_engine import derive_smc_trade_plan

CFG = {'estimated_roundtrip_cost_pct': 0.15, 'min_net_reward_risk': 2.0}
T = datetime(2026, 11, 20, 10, 0)


def ob(bias, low, high, mitigated=False):
    return SMCOrderBlock(high=high, low=low, time=T, bias=bias, block_type='SWING',
                         body_high=high, body_low=low, strength=0.8, mitigated=mitigated)


def pivot(level, typ):
    return SMCPivot(level=level, time=T, bar_index=0, pivot_type=typ, is_strong=True)


def state(obs, atr=1.0, sh=None, sl=None, th=None, tl=None):
    return SimpleNamespace(order_blocks=obs, atr=atr, swing_high=sh, swing_low=sl,
                           trailing_high=th, trailing_low=tl)


class SmcTradePlanTests(unittest.TestCase):
    def test_discount_long_in_fresh_ob(self):
        z = SMCZone('DISCOUNT', high=110, low=90)
        s = state([ob('BULLISH', 99, 101)], sh=pivot(120, 'HIGH'), th=120)
        p = derive_smc_trade_plan(s, z, 100.0, CFG)
        self.assertEqual(p['side'], 'LONG')
        self.assertTrue(p['in_fresh_ob'])
        self.assertEqual(p['entry'], 100.0)
        self.assertLess(p['stop'], 100.0)       # stop sits below the OB low
        self.assertEqual(p['target'], 120)       # strong high above
        self.assertGreater(p['rr'], 2.0)

    def test_premium_short_in_fresh_ob(self):
        z = SMCZone('PREMIUM', high=110, low=90)
        s = state([ob('BEARISH', 99, 101)], sl=pivot(80, 'LOW'), tl=80)
        p = derive_smc_trade_plan(s, z, 100.0, CFG)
        self.assertEqual(p['side'], 'SHORT')
        self.assertTrue(p['in_fresh_ob'])
        self.assertGreater(p['stop'], 100.0)     # stop sits above the OB high
        self.assertEqual(p['target'], 80)
        self.assertGreater(p['rr'], 2.0)

    def test_equilibrium_is_never_traded(self):
        z = SMCZone('EQUILIBRIUM', high=110, low=90)
        self.assertIsNone(derive_smc_trade_plan(state([]), z, 100.0, CFG))

    def test_price_outside_any_fresh_ob(self):
        z = SMCZone('DISCOUNT', high=110, low=90)
        s = state([ob('BULLISH', 95, 97)], sh=pivot(120, 'HIGH'), th=120)  # price 100 not inside
        self.assertEqual(derive_smc_trade_plan(s, z, 100.0, CFG), {'side': 'LONG', 'in_fresh_ob': False})

    def test_mitigated_ob_is_ignored(self):
        z = SMCZone('DISCOUNT', high=110, low=90)
        s = state([ob('BULLISH', 99, 101, mitigated=True)], sh=pivot(120, 'HIGH'), th=120)
        self.assertFalse(derive_smc_trade_plan(s, z, 100.0, CFG)['in_fresh_ob'])

    def test_wrong_bias_ob_does_not_qualify(self):
        # Discount wants a BULLISH OB; a bearish one at the price must not trigger a long.
        z = SMCZone('DISCOUNT', high=110, low=90)
        s = state([ob('BEARISH', 99, 101)], sh=pivot(120, 'HIGH'), th=120)
        self.assertFalse(derive_smc_trade_plan(s, z, 100.0, CFG)['in_fresh_ob'])

    def test_thin_reward_reports_low_rr(self):
        # Target barely above entry -> rr well under the 2:1 gate (order engine would reject).
        z = SMCZone('DISCOUNT', high=110, low=90)
        s = state([ob('BULLISH', 99, 101)], sh=pivot(100.5, 'HIGH'), th=100.5)
        p = derive_smc_trade_plan(s, z, 100.0, CFG)
        self.assertTrue(p['in_fresh_ob'])
        self.assertLess(p['rr'], 2.0)


if __name__ == '__main__':
    unittest.main()
