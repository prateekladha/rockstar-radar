#!/usr/bin/env python3
"""Replay SMC analysis for historical date/time to see OBs and FVGs as they appeared then."""
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from radar.fyers import FyersAdapter
from radar.models import Instrument, Tick
from radar.smc_engine import SMCEngine
from radar.utils import load_config, market_dt, IST


def replay_smc(symbol: str, replay_date: date, replay_time: str = "14:30"):
    """
    Replay SMC analysis for a specific date and time.

    Shows Order Blocks, FVGs, pivots, and score as they would have appeared at that moment.

    Args:
        symbol: Stock symbol (e.g., "RELIANCE", "TCS")
        replay_date: Date to replay (date object)
        replay_time: Time to replay to (HH:MM format, default: 14:30)
    """
    config = load_config()
    adapter = FyersAdapter(config)

    # Normalize symbol
    if not symbol.startswith('NSE:'):
        symbol = f'NSE:{symbol}-EQ'

    print("=" * 70)
    print(f"SMC REPLAY: {symbol}")
    print(f"Replaying to: {replay_date} {replay_time} IST")
    print("=" * 70)

    # Calculate date range: need 5 days before for proper pivot detection
    from_date = replay_date - timedelta(days=7)
    to_date = replay_date

    # Fetch historical data UP TO the replay time
    from_dt = market_dt(from_date, '09:15')
    to_dt = market_dt(to_date, replay_time)

    print(f"\n📊 Fetching historical data...")
    print(f"   From: {from_dt}")
    print(f"   To:   {to_dt}")

    # Fetch 5-minute candles
    from radar.service import baseline_history
    candles = baseline_history(adapter, symbol, '5', from_dt, to_dt)

    if not candles:
        print("❌ No data available for this symbol/date")
        return

    print(f"✓ Loaded {len(candles)} candles")

    # Initialize SMC engine
    instrument = Instrument(symbol=symbol)
    engine = SMCEngine([instrument], config)

    # Load all candles into engine
    engine.load_historical_candles(symbol, candles)

    # Get the price at replay time (last candle's close)
    current_price = candles[-1].close
    current_time = candles[-1].at

    print(f"✓ SMC analysis complete")
    print(f"   Current price: ₹{current_price:.2f}")
    print(f"   Last candle: {current_time}")

    # Process a tick to trigger opportunity calculation
    tick = Tick(
        symbol=symbol,
        price=current_price,
        time=current_time,
        daily_volume=sum(c.volume for c in candles[-75:])  # Approx daily volume
    )
    engine.process_tick(symbol, tick)

    # Get the state
    state = engine.get_state(symbol)

    if not state:
        print("❌ Could not analyze symbol")
        return

    # Display results
    print("\n" + "=" * 70)
    print("SMC STATE AT THIS MOMENT")
    print("=" * 70)

    # Trailing extremes
    print(f"\n📈 Price Range:")
    print(f"   Trailing High: ₹{state.trailing_high:.2f}")
    print(f"   Trailing Low:  ₹{state.trailing_low:.2f}")
    print(f"   Current:       ₹{current_price:.2f}")
    print(f"   ATR (14):      {state.atr:.2f}")

    # Swing Pivots
    print(f"\n📍 Swing Pivots:")
    if state.swing_high:
        age = (current_time - state.swing_high.time).total_seconds() / 3600
        print(f"   Swing High: ₹{state.swing_high.level:.2f} "
              f"({'STRONG' if state.swing_high.is_strong else 'WEAK'}) "
              f"[{age:.1f}h ago]")
    else:
        print(f"   Swing High: None detected")

    if state.swing_low:
        age = (current_time - state.swing_low.time).total_seconds() / 3600
        print(f"   Swing Low:  ₹{state.swing_low.level:.2f} "
              f"({'STRONG' if state.swing_low.is_strong else 'WEAK'}) "
              f"[{age:.1f}h ago]")
    else:
        print(f"   Swing Low: None detected")

    # Order Blocks
    print(f"\n📦 Order Blocks ({len(state.order_blocks)} detected):")
    if state.order_blocks:
        for i, ob in enumerate(state.order_blocks[-5:], 1):  # Show last 5
            age = (current_time - ob.time).total_seconds() / 3600
            status = "MITIGATED" if ob.mitigated else "FRESH"
            print(f"   {i}. {ob.bias} OB: ₹{ob.low:.2f}-₹{ob.high:.2f}")
            print(f"      Body zone: ₹{ob.body_low:.2f}-₹{ob.body_high:.2f}")
            print(f"      Strength: {ob.strength:.2f} | {status} | {age:.1f}h ago")
    else:
        print(f"   None detected")

    # Fair Value Gaps
    print(f"\n💎 Fair Value Gaps ({len(state.fair_value_gaps)} detected):")
    if state.fair_value_gaps:
        for i, fvg in enumerate(state.fair_value_gaps[-5:], 1):  # Show last 5
            age = (current_time - fvg.time).total_seconds() / 3600
            status = f"FILLED ({fvg.fill_percentage:.0f}%)" if fvg.filled else "UNFILLED"
            print(f"   {i}. {fvg.bias} FVG: ₹{fvg.low:.2f}-₹{fvg.high:.2f}")
            print(f"      Gap size: {fvg.gap_size_pct:.2f}% | {status} | {age:.1f}h ago")
    else:
        print(f"   None detected")

    # Market Structure
    print(f"\n🔄 Market Structure ({len(state.structures)} detected):")
    if state.structures:
        for i, struct in enumerate(state.structures[-3:], 1):  # Show last 3
            age = (current_time - struct.time).total_seconds() / 3600
            print(f"   {i}. {struct.bias} {struct.structure_type} at ₹{struct.level:.2f} [{age:.1f}h ago]")
    else:
        print(f"   None detected")

    # Opportunity
    print(f"\n⭐ SMC Opportunity:")
    if state.opportunity:
        opp = state.opportunity
        print(f"   Score: {opp.score}/100")
        print(f"   Zone: {opp.zone.zone_type if opp.zone else 'NONE'}")
        print(f"   Note: {opp.note}")

        # Show score breakdown
        from radar.smc_engine import calculate_smc_score_with_breakdown
        score, breakdown = calculate_smc_score_with_breakdown(state, current_price)

        print(f"\n   Score Breakdown:")
        print(f"     Zone Proximity:  {breakdown['zone_score']}/35")
        print(f"     Key Level:       {breakdown['key_level_score']}/30")
        print(f"     Order Blocks:    {breakdown['order_block_score']}/20")
        print(f"     Fair Value Gap:  {breakdown['fvg_score']}/15")
        print(f"     Structure:       {breakdown['structure_score']}/10")
        print(f"     Recency:         {breakdown['recency_score']}/15")
        print(f"     ─────────────────────────")
        print(f"     TOTAL:           {breakdown['final_score']}/100")
    else:
        print(f"   No opportunity (score < 25 or no confluence)")

    print("\n" + "=" * 70)
    print("REPLAY COMPLETE")
    print("=" * 70)
    print("\n💡 This is exactly what the system would have shown at that time!")
    print("   You can see OBs, FVGs, and the score that would have been calculated.")
    print("")


def main():
    """Run SMC replay from command line."""
    import argparse

    parser = argparse.ArgumentParser(description='Replay SMC analysis for historical date/time')
    parser.add_argument('symbol', help='Stock symbol (e.g., RELIANCE, TCS)')
    parser.add_argument('--date', help='Date to replay (YYYY-MM-DD, default: yesterday)',
                       default=(date.today() - timedelta(days=1)).isoformat())
    parser.add_argument('--time', help='Time to replay to (HH:MM, default: 14:30)',
                       default='14:30')

    args = parser.parse_args()

    try:
        replay_date = date.fromisoformat(args.date)
    except ValueError:
        print(f"❌ Invalid date format: {args.date}")
        print("   Use YYYY-MM-DD format (e.g., 2026-11-20)")
        sys.exit(1)

    try:
        replay_smc(args.symbol, replay_date, args.time)
    except Exception as e:
        print(f"\n❌ Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
