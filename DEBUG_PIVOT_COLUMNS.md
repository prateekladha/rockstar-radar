# Troubleshooting Empty Pivot Columns in Debug Tab

## Issue
Strong High, Weak High, Strong Low, Weak Low, and Structure columns showing empty (—) in Debug tab.

## Root Cause Analysis

The backend code is working correctly (verified via unit tests). The issue is likely:
1. **Frontend not rebuilt** - Changes to JSX not compiled to production bundle
2. **Browser cache** - Old JavaScript bundle still loaded
3. **Missing pivot detection** - Stock doesn't have pivots yet (needs 101+ candles)

## Steps to Fix

### Step 1: Pull Latest Code
```bash
git pull origin fix/debug-pivot-columns
```

### Step 2: Rebuild Frontend
```bash
# Use the convenience script
bash rebuild_frontend.sh

# OR manually:
cd web
rm -rf dist
npm run build
cd ..
```

### Step 3: Clear Python Cache (if needed)
```bash
bash clear_cache.sh
```

### Step 4: Restart Backend Server
```bash
# Stop your current server (Ctrl+C or kill process)
# Then restart:
python3 launch.py run
# Or however you run your server in production
```

### Step 5: Test in Browser

1. **Hard refresh** browser: `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (Mac)
2. Open **Debug tab**
3. Search for a stock (e.g., "RELIANCE" or "VOLTAS")
4. Look for the **🔍 DEBUG: Raw API Response** section (click to expand)
5. Check what data is in the JSON

### Step 6: Check Browser Console

1. Open browser DevTools (F12)
2. Go to Console tab
3. Look for "OpportunityCard data:" log
4. Verify if the data shows:
   ```javascript
   {
     oppStrongHigh: 108.0,    // or null
     oppWeakLow: 92.0,        // or null
     swingHigh: { level: 108.0, is_strong: true },
     swingLow: { level: 92.0, is_strong: false },
     computed: {
       strongHigh: 108.0,
       weakLow: 92.0
     }
   }
   ```

## What the Debug Section Shows

The collapsible "🔍 DEBUG: Raw API Response" shows exactly what the backend returned:

```json
{
  "opportunity": {
    "strong_high": 108.0,
    "strong_low": null,
    "weak_high": null,
    "weak_low": 92.0,
    "recent_structure": "BULLISH BOS"
  },
  "swing_high": {
    "level": 108.0,
    "is_strong": true,
    "time": "2026-11-20T00:45:33"
  },
  "swing_low": {
    "level": 92.0,
    "is_strong": false,
    "time": "2026-11-19T23:45:33"
  }
}
```

## Expected Results

### When Opportunity Exists (Score >= 35):

| Column | Shows | Example |
|--------|-------|---------|
| Strong High | Value if swing_high.is_strong=true | 108.50 |
| Strong Low | Value if swing_low.is_strong=true | 91.20 |
| Weak High | Value if swing_high.is_strong=false | — |
| Weak Low | Value if swing_low.is_strong=false | 92.30 |
| Structure | Recent structure if exists | BULLISH BOS |

### When No Opportunity (Score < 35):

A separate "Detected Pivots" table shows below the "No Opportunity" banner, displaying the same pivot data.

## If Still Not Working

**Check these:**

1. **Verify frontend build happened:**
   ```bash
   ls -lh web/dist/
   # Should show recently updated files
   ```

2. **Verify backend has latest code:**
   ```bash
   python3 verify_code.py
   # Should show "✓ ALL CHECKS PASSED"
   ```

3. **Check if pivots are actually detected:**
   - Expand "🔍 DEBUG: Raw API Response"
   - If `swing_high` and `swing_low` are both `null` → Stock needs more candles
   - If they exist but columns empty → Frontend issue

4. **Test with a known good stock:**
   ```bash
   # Test backend directly
   python3 << 'EOF'
   from radar.fyers import FyersAdapter
   from radar.debug_analysis import analyze_single_stock
   from radar.utils import load_config
   
   adapter = FyersAdapter(load_config())
   result = analyze_single_stock(adapter, "RELIANCE", load_config())
   
   print(f"Success: {result.get('success')}")
   print(f"Swing High: {result.get('swing_high')}")
   print(f"Swing Low: {result.get('swing_low')}")
   if result.get('opportunity'):
       opp = result['opportunity']
       print(f"Strong High: {opp.get('strong_high')}")
       print(f"Weak Low: {opp.get('weak_low')}")
   EOF
   ```

## Contact

If none of the above works, provide:
1. Screenshot of the "🔍 DEBUG: Raw API Response" section (expanded)
2. Screenshot of browser console showing "OpportunityCard data:" log
3. Output of: `python3 verify_code.py`

This will help identify exactly where the data is getting lost.
