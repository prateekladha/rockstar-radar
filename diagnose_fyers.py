#!/usr/bin/env python3
"""Diagnose FYERS API -99 error."""
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

# Check for ssl_fix
if os.path.exists('ssl_fix.py'):
    os.environ.setdefault('DEV_LOGIN', '1')
    try:
        import ssl_fix  # noqa: F401
        print("✓ SSL fix loaded (DEV_LOGIN=1)")
    except ImportError:
        pass

from radar.fyers import FyersAdapter
from radar.utils import load_config, market_dt, now_ist

def diagnose():
    """Run diagnostics on FYERS API connection."""
    print("=" * 70)
    print("FYERS API Diagnostic Tool")
    print("=" * 70)

    # Check environment
    print("\n1. Environment Check:")
    app_id = os.environ.get('FYERS_APP_ID')
    token = os.environ.get('FYERS_ACCESS_TOKEN')

    print(f"   FYERS_APP_ID: {'✓ Set' if app_id else '✗ Not set'}")
    print(f"   FYERS_ACCESS_TOKEN: {'✓ Set' if token else '✗ Not set'}")
    print(f"   DEV_LOGIN: {os.environ.get('DEV_LOGIN', 'not set')}")

    if not app_id or not token:
        print("\n❌ Missing credentials!")
        print("   Run: python3 launch.py login")
        return

    # Try to load config
    print("\n2. Config Check:")
    try:
        config = load_config()
        print("   ✓ Config loaded")
    except Exception as e:
        print(f"   ✗ Config error: {e}")
        return

    # Initialize adapter
    print("\n3. Adapter Initialization:")
    try:
        adapter = FyersAdapter(config)
        print("   ✓ FyersAdapter created")
    except Exception as e:
        print(f"   ✗ Adapter error: {e}")
        import traceback
        traceback.print_exc()
        return

    # Test quotes (simple API call)
    print("\n4. Testing Quotes API:")
    try:
        quotes = adapter.quotes(['NSE:SBIN-EQ'])
        if quotes:
            print("   ✓ Quotes API working")
            for symbol, data in quotes.items():
                print(f"   {symbol}: ₹{data.get('ltp', 'N/A')}")
        else:
            print("   ⚠ Quotes API returned empty")
    except Exception as e:
        print(f"   ✗ Quotes error: {type(e).__name__}: {e}")
        if "-99" in str(e):
            print("\n   ⚠ ERROR -99 detected!")
            print("   Common causes:")
            print("   • Token expired (re-login needed)")
            print("   • SSL/TLS issue (check ssl_fix.py)")
            print("   • Cloudflare block (IP banned)")
            print("   • Invalid request format")

    # Test history (the failing API call)
    print("\n5. Testing History API:")

    # Calculate date range
    today = now_ist().date()
    from_dt = market_dt(today - timedelta(days=2), '09:15')
    to_dt = market_dt(today, '15:30')

    print(f"   Symbol: NSE:SBIN-EQ")
    print(f"   From: {from_dt}")
    print(f"   To: {to_dt}")

    try:
        from radar.service import baseline_history
        candles = baseline_history(adapter, 'NSE:SBIN-EQ', '5', from_dt, to_dt)

        if candles:
            print(f"   ✓ History API working - {len(candles)} candles")
            print(f"   First: {candles[0].at} - ₹{candles[0].close}")
            print(f"   Last:  {candles[-1].at} - ₹{candles[-1].close}")
        else:
            print("   ⚠ History API returned no data")
    except Exception as e:
        print(f"   ✗ History error: {type(e).__name__}: {e}")
        if "-99" in str(e):
            print("\n   🔍 ERROR -99 in History API!")
            print("\n   Troubleshooting steps:")
            print("   1. Re-login to FYERS:")
            print("      python3 launch.py login")
            print("   2. Check if ssl_fix.py exists and DEV_LOGIN=1")
            print("   3. Try with a different symbol")
            print("   4. Check FYERS API status")
            print("   5. Wait 5 minutes (possible temporary ban)")

    # Check token validity
    print("\n6. Token Validity Check:")
    try:
        # Profile call requires valid token
        profile = adapter.client.get_profile()
        if profile and profile.get('s') == 'ok':
            print("   ✓ Token is valid")
            data = profile.get('data', {})
            print(f"   Name: {data.get('name', 'N/A')}")
            print(f"   Email: {data.get('email_id', 'N/A')}")
        else:
            print("   ⚠ Token might be expired")
    except Exception as e:
        print(f"   ✗ Token check failed: {e}")
        print("   → Re-login required: python3 launch.py login")

    print("\n" + "=" * 70)
    print("Diagnostic Complete")
    print("=" * 70)

if __name__ == '__main__':
    try:
        diagnose()
    except KeyboardInterrupt:
        print("\n\nDiagnostic interrupted")
    except Exception as e:
        print(f"\n❌ Diagnostic failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
