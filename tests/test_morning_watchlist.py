"""FYERS Standard-cap-safe premarket shortlist integration tests."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from radar.models import Instrument
from radar.engine import RadarEngine
from radar.selecting import (SelectionError, choose_top100,
                             load_morning_pins, normalize_morning_symbol)
from radar.dashboard import PAGE
from radar.utils import load_config, now_ist

CFG = load_config()


class MorningWatchlistTests(unittest.TestCase):
    def test_symbols_normalize(self):
        self.assertEqual(normalize_morning_symbol(' bhartiartl '), 'NSE:BHARTIARTL-EQ')
        self.assertEqual(normalize_morning_symbol('NSE:MCX-EQ'), 'NSE:MCX-EQ')
        self.assertEqual(normalize_morning_symbol('m&m'), 'NSE:M&M-EQ')
        with self.assertRaises(SelectionError):
            normalize_morning_symbol('BSE:SENSEX')
        with self.assertRaises(SelectionError):
            normalize_morning_symbol('NSE:SBIN-FUT')

    def test_manual_file_merges_config_dedupes_and_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'morning.txt'
            f.write_text('# comments\nBHARTIARTL, SBIN\n NSE:SBIN-EQ\nMCX  # catalyst\n')
            self.assertEqual(load_morning_pins(dict(CFG, morning_pins=['ITC', 'SBIN']), f),
                             ['NSE:ITC-EQ', 'NSE:SBIN-EQ', 'NSE:BHARTIARTL-EQ', 'NSE:MCX-EQ'])

    def test_missing_file_keeps_config_pins(self):
        self.assertEqual(load_morning_pins(dict(CFG, morning_pins=['ITC']), Path('/nonexistent/a.txt')),
                         ['NSE:ITC-EQ'])

    def test_excess_pins_rejected_above_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / 'morning.txt'
            f.write_text('\n'.join('STOCK' + str(x) for x in range(101)))
            with self.assertRaisesRegex(SelectionError, '100-symbol'):
                load_morning_pins(CFG, f)

    def test_100_total_and_morning_source_does_not_alter_trade_scoring(self):
        profiles = [Instrument(f'NSE:TEST{i}-EQ', f'Sector{i%8}', 50, 1.1, 300,
                               selection_score=1000-i) for i in range(140)]
        profiles.append(Instrument('NSE:SPECIAL-EQ', 'Special', 25, 1.0, 300,
                                   selection_score=1))
        original = profiles[-1].selection_score
        result = choose_top100(profiles, CFG, ['NSE:SPECIAL-EQ'])
        self.assertEqual(len(result), 100)
        self.assertEqual(result[0].symbol, 'NSE:SPECIAL-EQ')
        self.assertEqual(result[0].source, 'MORNING')
        self.assertEqual(result[0].selection_score, original)
        self.assertEqual(sum(s.source == 'MORNING' for s in result), 1)
        self.assertEqual(sum(s.source == 'AUTO' for s in result), 99)
        snapshot = RadarEngine(result, CFG, now_ist().date(), mode='SIMULATION').snapshot()
        self.assertEqual(snapshot['monitored'], 100)
        self.assertEqual(snapshot['morning_monitored'], 1)
        self.assertEqual(next(s for s in snapshot['all'] if s['symbol'] == 'NSE:SPECIAL-EQ')['source'], 'MORNING')

    def test_pinned_still_must_pass_price_and_liquidity(self):
        bad = Instrument('NSE:BAD-EQ', 'Industry1', 1, 1.2, 300, selection_score=9999)
        others = [Instrument('NSE:T' + str(i) + '-EQ', f'Sector{i%10}', 50, 1.7, 300,
                             selection_score=100-i) for i in range(105)]
        result = choose_top100(others + [bad], CFG, ['NSE:BAD-EQ'])
        self.assertNotIn('NSE:BAD-EQ', [s.symbol for s in result])

    def test_dashboard_has_source_filter_and_tags(self):
        self.assertIn('id="source"', PAGE)
        self.assertIn('s.source||\'AUTO\'', PAGE)
        self.assertIn('id="morningcount"', PAGE)


if __name__ == '__main__':
    unittest.main()
