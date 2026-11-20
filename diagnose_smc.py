#!/usr/bin/env python3
"""Diagnose why SMC Radar shows no opportunities."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from radar.models import Instrument, Candle
from radar.smc_engine import SMCEngine
from radar.utils import load_config

def diagnose_smc():
    """Check SMC engine with test data."""
    print("=" * 60)
    print("SMC Radar Diagnostic Tool")
    print("=" * 60)

    # Create test instruments
    test_symbols = ['NSE:RELIANCE-EQ', 'NSE:TCS-EQ', 'NSE:INFY-EQ']
    instruments = [Instrument(symbol=sym) for sym in test_symbols]

    # Initialize SMC engine
    config = load_config()
    engine = SMCEngine(instruments, config)

    print(f"\n✓ SMC Engine initialized with {len(instruments)} instruments")

    # Create mock candles (150 candles for proper pivot detection)
    now = datetime.now()
    base_price = 100.0

    for symbol in test_symbols:
        candles = []
        for i in range(150):
            # Simulate price movement
            price_var = (i % 20) - 10  # Creates highs and lows
            candle = Candle(
                at=now - timedelta(minutes=150-i),
                open=base_price + price_var,
                high=base_price + price_var + 2,
                low=base_price + price_var - 2,
                close=base_price + price_var + 1,
                volume=100000
            )
            candles.append(candle)

        engine.load_historical_candles(symbol, candles)
        print(f"✓ Loaded {len(candles)} candles for {symbol}")

    # Trigger analysis
    from radar.models import Tick
    for symbol in test_symbols:
        tick = Tick(symbol=symbol, price=base_price, time=now, daily_volume=1000000)
        engine.process_tick(symbol, tick)

    print(f"\n✓ Processed ticks for all symbols")

    # Check opportunities
    opportunities = engine.get_opportunities()

    print("\n" + "=" * 60)
    print(f"RESULT: {len(opportunities)} opportunities detected")
    print("=" * 60)

    if opportunities:
        for opp in opportunities:
            print(f"\n✓ {opp.symbol}")
            print(f"  Score: {opp.score}/100")
            print(f"  Zone: {opp.zone.zone_type if opp.zone else 'None'}")
            print(f"  Price: {opp.price}")
            print(f"  Note: {opp.note}")
    else:
        print("\n❌ No opportunities found with test data!")
        print("\nPossible causes:")
        print("1. Minimum threshold (35) too high for current market")
        print("2. Stocks not in premium/discount zones")
        print("3. No swing pivots detected (needs 101+ candles)")
        print("4. Order blocks/FVG not detected")
        print("5. Recency penalties reducing scores below 35")

        # Check states for debugging
        print("\n" + "=" * 60)
        print("Detailed State Check:")
        print("=" * 60)

        for symbol in test_symbols:
            state = engine.get_state(symbol)
            if state:
                print(f"\n{symbol}:")
                print(f"  Candles: {len(state.candles)}")
                print(f"  Trailing High: {state.trailing_high}")
                print(f"  Trailing Low: {state.trailing_low}")
                print(f"  Swing High: {state.swing_high.level if state.swing_high else 'None'}")
                print(f"  Swing Low: {state.swing_low.level if state.swing_low else 'None'}")
                print(f"  Order Blocks: {len(state.order_blocks)}")
                print(f"  Structures: {len(state.structures)}")
                print(f"  Opportunity: {state.opportunity is not None}")

                if state.opportunity:
                    print(f"  → Score: {state.opportunity.score}")
                else:
                    print(f"  → No opportunity (likely score < 35)")

    print("\n" + "=" * 60)
    print("Next Steps:")
    print("=" * 60)
    print("1. Check if scanner is running: ps aux | grep launch.py")
    print("2. Check SMC Radar tab in UI - refresh the page")
    print("3. Try Debug tab with a known active stock (RELIANCE/TCS)")
    print("4. Check if market hours and sufficient data available")
    print("5. Temporarily lower threshold to 25 for testing")
    print("\nRun: python3 diagnose_smc.py")
    print("=" * 60)

if __name__ == '__main__':
    try:
        diagnose_smc()
    except Exception as e:
        print(f"\n❌ Error: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
