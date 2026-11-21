"""Zone re-anchor: premium/discount measured against the swing leg, not trailing extremes."""
import unittest
from types import SimpleNamespace

from radar.smc_engine import zone_range, calculate_zones, get_current_zone


def piv(level):
    return SimpleNamespace(level=level)


def state(sh=None, sl=None, ih=None, il=None, th=None, tl=None):
    return SimpleNamespace(swing_high=piv(sh) if sh else None, swing_low=piv(sl) if sl else None,
                           internal_high=piv(ih) if ih else None, internal_low=piv(il) if il else None,
                           trailing_high=th, trailing_low=tl)


class ZoneRangeTests(unittest.TestCase):
    def test_prefers_swing_leg(self):
        s = state(sh=120, sl=80, th=200, tl=10)   # trailing extremes are a stale wick
        self.assertEqual(zone_range(s), (120, 80))  # uses the swing leg, not 200/10

    def test_falls_back_to_internal_when_no_swing(self):
        s = state(ih=118, il=82, th=200, tl=10)
        self.assertEqual(zone_range(s), (118, 82))

    def test_falls_back_to_trailing_when_no_pivots(self):
        s = state(th=150, tl=90)
        self.assertEqual(zone_range(s), (150, 90))

    def test_inverted_swing_falls_back(self):
        # swing low above swing high (post-cross) is invalid -> fall through to trailing
        s = state(sh=80, sl=120, th=150, tl=90)
        self.assertEqual(zone_range(s), (150, 90))


class ZoneClassificationTests(unittest.TestCase):
    def test_zones_split_25_50_25(self):
        s = state(sh=120, sl=80)
        hi, lo = zone_range(s)
        zones = calculate_zones(hi, lo)
        self.assertEqual(get_current_zone(115, zones).zone_type, 'PREMIUM')      # top 25% (110-120)
        self.assertEqual(get_current_zone(100, zones).zone_type, 'EQUILIBRIUM')  # middle (90-110)
        self.assertEqual(get_current_zone(85, zones).zone_type, 'DISCOUNT')      # bottom 25% (80-90)


if __name__ == '__main__':
    unittest.main()
