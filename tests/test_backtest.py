"""Smoke test for tools/backtest.py — the harness runs end-to-end without error."""
import os
import sys
import unittest
from datetime import timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from radar.utils import IST                      # noqa: E402
import backtest as bt                            # noqa: E402


def _series(n, start_px=1000.0):
    from datetime import datetime
    t = datetime(2026, 11, 17, 9, 15, tzinfo=IST)
    out, px = [], start_px
    for i in range(n):
        px += (1.0 if (i // 10) % 2 == 0 else -1.0)      # gentle oscillation
        out.append({'at': t.isoformat(), 'open': px, 'high': px + 1,
                    'low': px - 1, 'close': px, 'volume': 2000 + i})
        t += timedelta(minutes=5)
    return out


class BacktestSmoke(unittest.TestCase):
    def test_runs_end_to_end(self):
        import json, tempfile
        hist = {'NSE:AAA-EQ': _series(200), 'NSE:BBB-EQ': _series(200, 500.0)}
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
            json.dump(hist, f)
            path = f.name
        loaded = bt.load_history(path)
        self.assertEqual(set(loaded), {'NSE:AAA-EQ', 'NSE:BBB-EQ'})
        cfg = {'max_trades_per_symbol': 4, 'exit_breakeven_at_r': 0, 'exit_partial_frac': 0,
               'exit_velocity_governor': False, 'exit_mgmt_cutoff': '15:00'}
        trades = bt.run(loaded, cfg, min_score=35, max_risk=1960, use_exit_engine=True)
        self.assertIsInstance(trades, list)
        for t in trades:
            self.assertIn('pnl', t)
            self.assertIn(t['side'], ('LONG', 'SHORT'))
        os.unlink(path)


if __name__ == '__main__':
    unittest.main()
