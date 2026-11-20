"""SMC history bootstrap must survive a poisoned / empty cache.

Regression for the 2026-11-20 prod incident: a mid-session scanner restart reloaded an
SMC history cache that listed every symbol with an empty candle array. `load_smc_history`
trusted it and returned early, so the SMC engine had zero historical context and the radar
showed no opportunities for the rest of the session. The fetch/warmup paths also persisted
empty per-symbol entries, which is what poisoned the cache in the first place.
"""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from radar.models import Candle
from radar.service import (cache_smc_history, load_smc_history,
                           smc_cache_path)
from radar.utils import load_config, market_dt

DAY = date(2026, 11, 20)
SYMS = ['NSE:AAA-EQ', 'NSE:BBB-EQ', 'NSE:CCC-EQ', 'NSE:DDD-EQ']


def make_candles(n: int) -> list[Candle]:
    """n sequential 5-minute candles starting at the session open."""
    start = market_dt(DAY, '09:15')
    out = []
    for i in range(n):
        out.append(Candle(start + timedelta(minutes=5 * i), 100, 101, 99, 100, 1000))
    return out


class FakeSMCEngine:
    def __init__(self, symbols):
        self.states = {s: object() for s in symbols}
        self.loaded: dict[str, list] = {}

    def load_historical_candles(self, symbol, candles):
        self.loaded[symbol] = candles


class SmcHistoryCacheTests(unittest.TestCase):
    def setUp(self):
        self.cfg = dict(load_config(), use_one_minute_candles=False)  # 5-minute bars

    def _cache_path(self, tmp: str) -> Path:
        # smc_cache_path resolves against radar.service.ROOT, which we patch.
        return smc_cache_path(DAY, 5)

    def test_poisoned_cache_falls_back_to_broker_fetch(self):
        """An all-empty cache must NOT be trusted; the engine must re-fetch history."""
        with tempfile.TemporaryDirectory() as tmp, patch('radar.service.ROOT', Path(tmp)):
            path = self._cache_path(tmp)
            path.parent.mkdir(parents=True, exist_ok=True)
            # Every symbol present but with ZERO candles — the exact poison from prod.
            path.write_text(json.dumps({s: [] for s in SYMS}), encoding='utf-8')

            engine = FakeSMCEngine(SYMS)
            with patch('radar.service.baseline_history', return_value=make_candles(120)) as bh:
                loaded = load_smc_history(adapter=None, smc_engine=engine,
                                          today=DAY, config=self.cfg)

            self.assertEqual(loaded, len(SYMS))            # fell back and fetched all
            self.assertTrue(bh.called)                     # broker was actually hit
            self.assertEqual(set(engine.loaded), set(SYMS))
            # The poisoned cache was overwritten with real, non-empty data.
            rewritten = json.loads(path.read_text(encoding='utf-8'))
            self.assertTrue(all(len(v) == 120 for v in rewritten.values()))

    def test_healthy_cache_is_used_without_broker_fetch(self):
        """A good cache loads instantly and must not touch the broker."""
        with tempfile.TemporaryDirectory() as tmp, patch('radar.service.ROOT', Path(tmp)):
            path = self._cache_path(tmp)
            path.parent.mkdir(parents=True, exist_ok=True)
            good = {s: [{'at': c.at.isoformat(), 'open': c.open, 'high': c.high,
                         'low': c.low, 'close': c.close, 'volume': c.volume}
                        for c in make_candles(120)] for s in SYMS}
            path.write_text(json.dumps(good), encoding='utf-8')

            engine = FakeSMCEngine(SYMS)

            def boom(*a, **k):
                raise AssertionError('broker must not be called when cache is healthy')

            with patch('radar.service.baseline_history', side_effect=boom):
                loaded = load_smc_history(adapter=None, smc_engine=engine,
                                          today=DAY, config=self.cfg)

            self.assertEqual(loaded, len(SYMS))
            self.assertEqual(set(engine.loaded), set(SYMS))

    def test_cache_smc_history_never_persists_empty_symbols(self):
        """Warmup must leave failed symbols ABSENT, never cache them as []."""
        with tempfile.TemporaryDirectory() as tmp, patch('radar.service.ROOT', Path(tmp)):
            path = self._cache_path(tmp)
            path.parent.mkdir(parents=True, exist_ok=True)

            good = {SYMS[0], SYMS[2]}

            def fake_history(adapter, symbol, resolution, from_dt, to_dt, *a, **k):
                return make_candles(120) if symbol in good else []

            with patch('radar.service.baseline_history', side_effect=fake_history):
                result = cache_smc_history(adapter=None, symbols=SYMS, day=DAY,
                                           config=self.cfg, force=True)

            stored = json.loads(path.read_text(encoding='utf-8'))
            # Only the symbols that returned candles are persisted; no empty arrays.
            self.assertEqual(set(stored), good)
            self.assertNotIn(SYMS[1], stored)
            self.assertTrue(all(v for v in stored.values()))
            self.assertEqual({s for s, ok in result.items() if ok}, good)


if __name__ == '__main__':
    unittest.main()
