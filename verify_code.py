#!/usr/bin/env python3
"""Verify that the code is correctly deployed and can be imported."""
import sys
import traceback

def verify_imports():
    """Test all critical imports."""
    print("Verifying imports...")

    try:
        from radar.debug_analysis import analyze_single_stock
        print("✓ radar.debug_analysis.analyze_single_stock")
    except Exception as e:
        print(f"✗ radar.debug_analysis.analyze_single_stock: {e}")
        traceback.print_exc()
        return False

    try:
        from radar.smc_engine import calculate_smc_score_with_breakdown
        print("✓ radar.smc_engine.calculate_smc_score_with_breakdown")
    except Exception as e:
        print(f"✗ radar.smc_engine.calculate_smc_score_with_breakdown: {e}")
        traceback.print_exc()
        return False

    try:
        from radar.smc_detection import (
            detect_order_block_enhanced,
            detect_fair_value_gaps,
            update_order_block_mitigation,
            update_fvg_fill_status
        )
        print("✓ radar.smc_detection functions")
    except Exception as e:
        print(f"✗ radar.smc_detection functions: {e}")
        traceback.print_exc()
        return False

    try:
        from radar.models import SMCFairValueGap
        print("✓ radar.models.SMCFairValueGap")
    except Exception as e:
        print(f"✗ radar.models.SMCFairValueGap: {e}")
        traceback.print_exc()
        return False

    return True

def test_score_breakdown():
    """Test the score breakdown function."""
    print("\nTesting score breakdown function...")

    try:
        from radar.models import SMCSymbolState, Instrument, SMCPivot
        from radar.smc_engine import calculate_smc_score_with_breakdown
        from datetime import datetime, timedelta

        # Create mock state
        inst = Instrument(symbol="TEST")
        state = SMCSymbolState(info=inst)
        now = datetime.now()
        state.trailing_high = 100.0
        state.trailing_low = 90.0
        state.swing_high = SMCPivot(
            level=99.0,
            time=now - timedelta(hours=1),
            bar_index=0,
            pivot_type='HIGH',
            is_strong=True
        )

        score, breakdown = calculate_smc_score_with_breakdown(state, 98.5)

        print(f"✓ Score: {score}")
        print(f"✓ Breakdown keys: {list(breakdown.keys())}")
        print("✓ Function test passed!")
        return True

    except Exception as e:
        print(f"✗ Function test failed: {e}")
        traceback.print_exc()
        return False

if __name__ == '__main__':
    print("=" * 60)
    print("Code Verification Script")
    print("=" * 60)

    imports_ok = verify_imports()
    test_ok = test_score_breakdown()

    print("\n" + "=" * 60)
    if imports_ok and test_ok:
        print("✓ ALL CHECKS PASSED")
        print("=" * 60)
        sys.exit(0)
    else:
        print("✗ SOME CHECKS FAILED")
        print("=" * 60)
        print("\nTroubleshooting:")
        print("1. Run: bash clear_cache.sh")
        print("2. Restart your application server")
        print("3. Check Python version (requires Python 3.9+)")
        sys.exit(1)
