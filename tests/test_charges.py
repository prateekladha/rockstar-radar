"""Tests for the intraday equity cost model (server/charges.py).

Rates are FYERS's published INTRADAY EQUITY card (see docs/PAPER_LIVE_PARITY.md). The worked
example below is computed by hand from those rates so a regression in any single component is caught.
"""
from server.charges import round_trip_charges, trade_charges, DEFAULT_RATES


def test_worked_example_long_round_trip():
    # Buy 100 @ 1000 (= 1,00,000), sell 100 @ 1010 (= 1,01,000). Gross +1,000.
    buy_value, sell_value = 100_000.0, 101_000.0
    c = round_trip_charges(buy_value, sell_value)
    # Brokerage: min(20, 0.03% of 100000)=20 ; min(20, 0.03% of 101000)=20 -> 40
    assert c['brokerage'] == 40.0
    # STT: 0.025% of sell 101000 = 25.25
    assert c['stt'] == 25.25
    # Exchange txn: 0.00297% of turnover 201000 = 5.9697 -> 5.97
    assert c['exch_txn'] == 5.97
    # SEBI: 10/cr of 201000 = 0.201 -> 0.20
    assert c['sebi'] == 0.20
    # IPFT: 10/cr of 201000 = 0.201 -> 0.20
    assert c['ipft'] == 0.20
    # Stamp: 0.003% of buy 100000 = 3.0
    assert c['stamp'] == 3.0
    # GST: 18% of (brokerage 40 + exch 5.9697 + ipft 0.201) = 18% of 46.1707 = 8.3107 -> 8.31
    assert c['gst'] == 8.31
    # Total = 40 + 25.25 + 5.97 + 0.20 + 0.20 + 3.0 + 8.31 (component-rounded sum)
    assert abs(c['total'] - 82.93) < 0.05
    # Net on a +1,000 gross trade: still positive but costs are ~8% of the gross edge.
    assert c['total'] < 1000


def test_stt_is_sell_side_only():
    # Same values swapped between legs -> STT tracks the SELL leg, stamp the BUY leg.
    a = round_trip_charges(buy_value=100_000, sell_value=200_000)
    b = round_trip_charges(buy_value=200_000, sell_value=100_000)
    assert a['stt'] > b['stt']       # a sells more -> more STT
    assert b['stamp'] > a['stamp']   # b buys more -> more stamp


def test_brokerage_cap_applies():
    # Tiny leg: 0.03% of 10,000 = 3 < cap 20 -> brokerage is the pct, not the cap.
    c = round_trip_charges(10_000, 10_000)
    assert c['brokerage'] == round(0.03 / 100 * 10_000 * 2, 2) == 6.0
    # Large leg: 0.03% of 1,00,00,000 = 3000 > cap -> capped at 20/leg.
    big = round_trip_charges(10_000_000, 10_000_000)
    assert big['brokerage'] == 40.0


def test_long_short_symmetry_same_prices():
    # A LONG entry@1000 exit@1010 and a SHORT entry@1010 exit@1000 have identical leg values,
    # so identical charges (both buy one leg @1000-ish, sell the other).
    long_c = trade_charges('LONG', entry_fill=1000, exit_fill=1010, qty=100)
    short_c = trade_charges('SHORT', entry_fill=1010, exit_fill=1000, qty=100)
    assert long_c == short_c


def test_zero_qty_is_zero_cost():
    assert trade_charges('LONG', 1000, 1010, 0)['total'] == 0.0
    assert trade_charges('LONG', 0, 0, 100)['total'] == 0.0


def test_config_override_zeroes_costs():
    # paper_apply_charges off is handled by the caller; here prove rates are overridable to 0.
    zero = {k: 0.0 for k in DEFAULT_RATES}
    c = round_trip_charges(100_000, 101_000, zero)
    assert c['total'] == 0.0


def test_total_is_monotonic_in_size():
    small = trade_charges('LONG', 1000, 1010, 10)['total']
    large = trade_charges('LONG', 1000, 1010, 1000)['total']
    assert large > small > 0
