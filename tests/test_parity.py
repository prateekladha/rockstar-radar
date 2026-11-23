"""Tests for the paper→live parity layer (docs/PAPER_LIVE_PARITY.md):
slippage, the real-margin fundability/leverage gates, cost-netting in mark_closed, and the SMC
score-bucket report. Pure helpers + one integration test that a closed paper order books NET of costs.
"""
from server.order_engine import (_apply_slippage, _fundable, _intraday_leverage, _fy_symbol,
                                  mark_closed)
from server.models import Order
from radar.smc_engine import score_bucket_report


# --- slippage ---------------------------------------------------------------------------------
def test_slippage_is_always_adverse():
    # Entry: LONG pays up, SHORT sells down.
    assert _apply_slippage(1000, 'LONG', 10, 'entry') == 1001.0   # +10bps
    assert _apply_slippage(1000, 'SHORT', 10, 'entry') == 999.0   # -10bps
    # Exit (market/stop): LONG sells down, SHORT buys up.
    assert _apply_slippage(1000, 'LONG', 10, 'exit') == 999.0
    assert _apply_slippage(1000, 'SHORT', 10, 'exit') == 1001.0


def test_slippage_noop_cases():
    assert _apply_slippage(1000, 'LONG', 0, 'entry') == 1000      # 0 bps
    assert _apply_slippage(None, 'LONG', 10, 'entry') is None     # no price
    assert _apply_slippage(1000, 'LONG', 10, 'target') == 1000    # favourable limit: unchanged


# --- margin fundability + leverage -----------------------------------------------------------
def test_fundable_respects_committed_pool():
    # 50k avail, nothing committed -> a 40k order fits.
    assert _fundable(40_000, 50_000, 0) is True
    # 30k already committed -> a 40k order no longer fits (would need 70k of 50k).
    assert _fundable(40_000, 50_000, 30_000) is False
    # exactly fits.
    assert _fundable(20_000, 50_000, 30_000) is True


def test_fundable_unknown_inputs_are_not_fundable():
    assert _fundable(None, 50_000, 0) is False
    assert _fundable(40_000, None, 0) is False


def test_intraday_leverage():
    # ₹5,00,000 notional on ₹1,00,000 margin = 5x.
    assert _intraday_leverage(500_000, 100_000) == 5.0
    # ~1x = no real intraday benefit (the 'not MIS' proxy).
    assert _intraday_leverage(100_000, 100_000) == 1.0
    assert _intraday_leverage(0, 100_000) is None
    assert _intraday_leverage(100_000, 0) is None


def test_fy_symbol_canonicalises():
    assert _fy_symbol('TCS') == 'NSE:TCS-EQ'
    assert _fy_symbol('NSE:TCS-EQ') == 'NSE:TCS-EQ'
    assert _fy_symbol('RELIANCE-EQ') == 'NSE:RELIANCE-EQ'


# --- mark_closed nets costs + tags the exit ---------------------------------------------------
def _paper_long(qty=100, entry=1000.0, fill=1000.0, stop=990.0):
    o = Order(mode='paper', side='LONG', qty=qty, entry=entry, stop=stop,
              fill_price=fill, init_stop=stop, booked_qty=0, booked_pnl=0.0)
    return o


def test_mark_closed_books_net_of_costs():
    o = _paper_long()
    mark_closed(o, 1010.0, reason='target')           # +10/share * 100 = +1000 gross
    assert o.gross_pnl == 1000.0
    assert o.charges is not None and o.charges > 0     # real FYERS costs deducted
    assert o.pnl == round(1000.0 - o.charges, 2)       # pnl is NET
    assert o.pnl < o.gross_pnl
    assert o.exit_reason == 'target'                   # exit tagged
    # R is measured on the GROSS edge (10/share over a 10/share risk = ~1R), not net.
    assert o.result_r == 1.0


def test_mark_closed_manual_reason_persists():
    o = _paper_long()
    mark_closed(o, 1005.0, reason='manual')
    assert o.exit_reason == 'manual'                   # drives the re-entry guard


# --- SMC score-bucket report ------------------------------------------------------------------
def test_score_bucket_report_separates_buckets():
    samples = [
        {'score': 85, 'result_r': 2.0, 'pnl': 2000},
        {'score': 82, 'result_r': 1.0, 'pnl': 1000},
        {'score': 72, 'result_r': -1.0, 'pnl': -1000},
        {'score': 65, 'result_r': -1.0, 'pnl': -1000},
        {'score': 50, 'result_r': None, 'pnl': None},   # no realised R -> ignored in stats
    ]
    rep = {b['bucket']: b for b in score_bucket_report(samples)}
    assert rep['80-89']['n'] == 2
    assert rep['80-89']['avg_r'] == 1.5
    assert rep['80-89']['win_rate'] == 1.0
    assert rep['80-89']['total_pnl'] == 3000.0
    assert rep['70-79']['avg_r'] == -1.0
    assert rep['70-79']['win_rate'] == 0.0
    # empty bucket is well-formed, not a crash.
    assert rep['90-100']['n'] == 0 and rep['90-100']['avg_r'] is None
