"""Realtime provisional confirmation + authoritative reconciliation (Phase 1 wiring)."""
import unittest
from datetime import date, timedelta

from radar.aggregator import LiveCandleBuilder
from radar.engine import RadarEngine
from radar.models import Candle, Instrument, Tick
from radar.utils import load_config, market_dt

DAY = date(2026, 11, 5)
SYM = 'NSE:BHARTIARTL-EQ'


def c(hhmm, o, h, l, cl, v):
    return Candle(market_dt(DAY, hhmm), o, h, l, cl, v)


def base_engine(mode='LIVE'):
    """Engine with an authoritative opening range, baseline and a non-breakout prev bar."""
    cfg = load_config()
    inst = Instrument(SYM, 'Telecom', median_turnover_cr=150, daily_atr_pct=1.5,
                      previous_close=101, resistance=[105.0], support=[95.0])
    e = RadarEngine([inst], cfg, DAY, mode=mode)
    e.ingest_closed_bar(SYM, c('09:15', 100, 101, 99.5, 100.5, 20000),
                        observed_at=market_dt(DAY, '09:20'))          # OR: ORH=101, width 1.5%
    e.set_baseline(SYM, {k: 10000 for k in ('09:15', '09:20', '09:25', '09:30', '09:35')})
    e.ingest_closed_bar(SYM, c('09:20', 100.5, 100.9, 100.1, 100.7, 12000),
                        observed_at=market_dt(DAY, '09:25'))          # prev bar, no breakout
    return e


def set_fresh_tick(e, when, price=101.3):
    e.states[SYM].last_tick = Tick(SYM, price, when - timedelta(seconds=5))


# A clean LONG breakout bar at 09:25: close 101.3 > ORH 101, small extension (0.30%),
# volume 30000 -> RVOL 3.0 and turnover ~0.30cr, close above the candle VWAP proxy.
CONFIRM_BAR = c('09:25', 100.8, 101.4, 100.7, 101.3, 30000)
CONFIRM_OBS = market_dt(DAY, '09:30') + timedelta(seconds=5)


class RealtimeTests(unittest.TestCase):
    def test_live_bar_fires_provisional_confirmation(self):
        e = base_engine()
        set_fresh_tick(e, CONFIRM_OBS)
        e.ingest_live_bar(SYM, CONFIRM_BAR, observed_at=CONFIRM_OBS)
        st = e.states[SYM]
        self.assertEqual(st.state, 'CONFIRMED')
        self.assertTrue(st.confirm_provisional)
        self.assertIn(int(market_dt(DAY, '09:25').timestamp()), st.provisional_ts)
        self.assertEqual(len(e.events), 1)
        self.assertTrue(e.events[0].provisional)
        self.assertIn('PROVISIONAL', e.events[0].note)

    def test_authoritative_bar_validates_provisional_confirmation(self):
        e = base_engine()
        set_fresh_tick(e, CONFIRM_OBS)
        e.ingest_live_bar(SYM, CONFIRM_BAR, observed_at=CONFIRM_OBS)
        # Same bar now arrives authoritatively from REST history -> validate.
        set_fresh_tick(e, CONFIRM_OBS)
        e.ingest_closed_bar(SYM, CONFIRM_BAR, observed_at=CONFIRM_OBS, provisional=False)
        st = e.states[SYM]
        self.assertEqual(st.state, 'CONFIRMED')
        self.assertFalse(st.confirm_provisional)                  # upgraded to authoritative
        self.assertNotIn(int(market_dt(DAY, '09:25').timestamp()), st.provisional_ts)
        self.assertFalse(any(ev.state == 'RETRACTED' for ev in e.events))

    def test_authoritative_bar_retracts_false_provisional_confirmation(self):
        e = base_engine()
        set_fresh_tick(e, CONFIRM_OBS)
        e.ingest_live_bar(SYM, CONFIRM_BAR, observed_at=CONFIRM_OBS)
        self.assertEqual(e.states[SYM].state, 'CONFIRMED')
        # Authoritative truth: the bar actually closed BELOW ORH (no breakout) -> retract.
        truth = c('09:25', 100.8, 101.0, 100.6, 100.9, 30000)
        set_fresh_tick(e, CONFIRM_OBS)
        e.ingest_closed_bar(SYM, truth, observed_at=CONFIRM_OBS, provisional=False)
        st = e.states[SYM]
        self.assertEqual(st.state, 'RETRACTED')
        self.assertIsNone(st.confirmed_at)
        self.assertFalse(st.confirm_provisional)
        self.assertTrue(any(ev.state == 'RETRACTED' for ev in e.events))

    def test_opening_range_never_anchored_from_provisional_bar(self):
        cfg = load_config()
        inst = Instrument(SYM, 'Telecom', 150, 1.5, 101)
        e = RadarEngine([inst], cfg, DAY, mode='LIVE')
        e.ingest_live_bar(SYM, c('09:15', 100, 102, 99, 101, 20000),
                          observed_at=market_dt(DAY, '09:20'))
        self.assertIsNone(e.states[SYM].opening)                  # OR must be authoritative

    def test_provisional_bar_does_not_overwrite_authoritative(self):
        e = base_engine()
        set_fresh_tick(e, CONFIRM_OBS)
        e.ingest_closed_bar(SYM, CONFIRM_BAR, observed_at=CONFIRM_OBS, provisional=False)
        self.assertFalse(e.states[SYM].confirm_provisional)
        n_events = len(e.events)
        # A late provisional copy of an already-authoritative bar must be ignored.
        e.ingest_live_bar(SYM, CONFIRM_BAR, observed_at=CONFIRM_OBS)
        self.assertFalse(e.states[SYM].confirm_provisional)
        self.assertEqual(len(e.events), n_events)

    def test_provisional_retest_fires_then_authoritative_validates(self):
        e = base_engine()
        set_fresh_tick(e, CONFIRM_OBS)
        e.ingest_live_bar(SYM, CONFIRM_BAR, observed_at=CONFIRM_OBS)
        retest = c('09:30', 101.2, 101.5, 100.9, 101.2, 16000)    # pulls back to ORH, holds
        retest_obs = market_dt(DAY, '09:35') + timedelta(seconds=5)
        set_fresh_tick(e, retest_obs, price=101.2)
        e.ingest_live_bar(SYM, retest, observed_at=retest_obs)
        st = e.states[SYM]
        self.assertEqual(st.state, 'RETEST_READY')
        self.assertTrue(st.retest_provisional)
        self.assertIsNotNone(st.entry)
        # Authoritative retest bar reconciles -> stays RETEST_READY, no longer provisional.
        set_fresh_tick(e, retest_obs, price=101.2)
        e.ingest_closed_bar(SYM, retest, observed_at=retest_obs, provisional=False)
        self.assertEqual(st.state, 'RETEST_READY')
        self.assertFalse(st.retest_provisional)

    def test_aggregator_to_engine_end_to_end(self):
        # SIMULATION mode decouples the engine from wall-clock staleness checks so we can
        # drive the full tick -> LiveCandleBuilder -> ingest_live_bar -> signal chain.
        e = base_engine(mode='SIMULATION')
        # Observe each completed bar just after its close (as the live flush loop does
        # during market hours), instead of depending on the real wall clock.
        builder = LiveCandleBuilder(on_bar=lambda s, cd: e.ingest_live_bar(
            s, cd, observed_at=cd.at + timedelta(minutes=5, seconds=5)))
        builder.seed_prev_cumulative(SYM, 100000)                 # authoritative volume baseline
        def tick(hhmm, secs, price, cum):
            builder.add_tick(Tick(SYM, price, market_dt(DAY, hhmm) + timedelta(seconds=secs),
                                  daily_volume=cum))
        tick('09:25', 1, 100.8, 100000)      # open of the breakout bar
        tick('09:25', 120, 101.4, 118000)    # high
        tick('09:25', 299, 101.3, 130000)    # close -> bar volume 30000
        self.assertEqual(e.states[SYM].state, 'NO_SETUP')         # bar not closed yet
        tick('09:30', 2, 101.3, 131000)      # next-bar tick rolls 09:25 over -> provisional confirm
        st = e.states[SYM]
        self.assertEqual(st.state, 'CONFIRMED')
        self.assertTrue(st.confirm_provisional)


if __name__ == '__main__':
    unittest.main()
