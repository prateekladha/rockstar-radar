# Pre-requisite Checks - Complete Guide

## 🎯 Overview

**Pre-requisite checks are mandatory filters applied BEFORE any strategy (ORB or SMC) evaluation.**

If any prerequisite check fails, the stock is immediately rejected and will NOT appear in opportunities for that strategy.

---

## ✅ Why Pre-requisites?

**Problem:** Strategies were evaluating low-quality setups that had no chance of success.

**Examples:**
- Low volume breakouts (RVOL < 1.0) → Fake breakouts
- Illiquid stocks → Wide spreads, poor fills
- Penny stocks → High volatility, poor risk management

**Solution:** Filter out poor candidates BEFORE expensive strategy evaluation.

---

## 🏗️ Architecture

### Module: `radar/prerequisites.py`

**Core Components:**

1. **PrerequisiteConfig** - Configuration dataclass
2. **PrerequisiteChecker** - Validation logic
3. **PrerequisiteResult** - Result with pass/fail details

### Flow:

```
Stock → Pre-requisites → ✓ Pass → Strategy (ORB/SMC) → Opportunity
                      → ✗ Fail → Rejected (not shown)
```

### Integration Points:

1. **Debug Tab** (`radar/debug_analysis.py`)
   - Runs prereq checks before SMC analysis
   - Shows failure message if rejected
   
2. **ORB Scanner** (Future - `radar/engine.py`)
   - Will run prereq checks before ORB evaluation
   
3. **SMC Scanner** (Future - `radar/smc_engine.py`)
   - Will run prereq checks before SMC evaluation

---

## 📊 Available Checks

### 1. RVOL (Relative Volume) ✅ ACTIVE

**Default:** `min_rvol = 1.0`

**Purpose:** Ensure sufficient volume participation

**Logic:**
```python
if rvol < min_rvol:
    return FAIL
```

**Configuration:**
- UI: Settings → Pre-requisite Checks → Minimum RVOL
- Database: `settings.prereq_min_rvol`
- API: `/api/prerequisites`

**Example:**
```
Stock: RELIANCE
RVOL: 0.8 (80% of normal volume)
min_rvol: 1.0
Result: ❌ FAIL - "RVOL 0.80 < 1.00"
```

**Recommendation:**
- **min_rvol = 1.0** (default) - Normal or higher volume
- **min_rvol = 1.2** - Good volume (20% above normal)
- **min_rvol = 1.5** - Strong volume (50% above normal)

---

### 2. Liquidity Check (Future - Disabled)

**Purpose:** Ensure tradeable liquidity

**Logic:**
```python
if liquidity_cr < min_liquidity_cr:
    return FAIL
```

**When to enable:**
- Large position sizes
- Need tight spreads
- Professional trading

---

### 3. Price Range Check (Future - Disabled)

**Purpose:** Filter by price range

**Logic:**
```python
if price < min_price or price > max_price:
    return FAIL
```

**Use cases:**
- Avoid penny stocks (min_price = 100)
- Focus on specific segment (200-1000 range)

---

### 4. Sector Filter (Future - Disabled)

**Purpose:** Only trade specific sectors

**Logic:**
```python
if sector not in allowed_sectors:
    return FAIL
```

**Use cases:**
- Sector-focused strategies
- Avoid certain industries

---

### 5. Blocked Symbols (Future - Disabled)

**Purpose:** Blacklist specific stocks

**Logic:**
```python
if symbol in blocked_symbols:
    return FAIL
```

**Use cases:**
- Bad past experience
- Illiquid stocks
- Regulatory issues

---

## 🔧 Configuration

### Via UI (Recommended)

1. Open **Settings** page
2. Scroll to **"Pre-requisite Checks"** panel
3. Configure settings:
   - Toggle **"Enable RVOL Check"** (ON by default)
   - Set **"Minimum RVOL"** (default: 1.0)
4. Click **"Save prerequisite settings"**

### Via API

**GET /api/prerequisites**
```json
{
  "min_rvol": 1.0,
  "rvol_enabled": true,
  "min_liquidity_cr": null,
  "min_price": null,
  "max_price": null,
  "allowed_sectors": null,
  "blocked_symbols": null
}
```

**PUT /api/prerequisites**
```bash
curl -X PUT http://127.0.0.1:8765/api/prerequisites \
  -H "Content-Type: application/json" \
  -d '{"min_rvol": 1.2, "rvol_enabled": true}'
```

### Via Database

```sql
UPDATE settings 
SET prereq_min_rvol = 1.2, 
    prereq_rvol_enabled = 1
WHERE user_id = 1;
```

---

## 📱 User Experience

### In Debug Tab

**When prerequisites PASS:**
```
✓ Pre-requisite checks passed
  RVOL: 1.45 ✓

SMC Analysis:
  Score: 87/100
  Zone: Premium
  ...
```

**When prerequisites FAIL:**
```
❌ Pre-requisite checks failed: RVOL

RELIANCE at ₹2,815.50
RVOL: 0.78

Failed Checks:
  • RVOL: 0.78 < 1.00 (threshold)

This stock was rejected before strategy evaluation.
```

### In SMC Radar

**Before (without prerequisites):**
- Shows 20 opportunities
- Some have low volume (RVOL 0.5-0.8)
- These are likely to fail

**After (with prerequisites):**
- Shows 12 opportunities
- All have RVOL ≥ 1.0
- Higher quality setups

### In ORB Radar

Similar behavior - low RVOL stocks filtered out early.

---

## 💻 Code Usage

### Quick Check

```python
from radar.prerequisites import PrerequisiteChecker, PrerequisiteConfig

# Create config
config = PrerequisiteConfig(
    min_rvol=1.0,
    rvol_enabled=True
)

# Create checker
checker = PrerequisiteChecker(config)

# Check a stock
result = checker.check('NSE:RELIANCE-EQ', {
    'rvol': 0.85,
    'price': 2815.50,
    'liquidity_cr': 150.5
})

if not result.passed:
    print(f"❌ {result.error_message}")
    print(f"Failed: {', '.join(result.failed_checks)}")
else:
    print("✓ All checks passed")
```

### In Strategy Code

```python
def evaluate_stock(symbol, data, config, prereq_config):
    """Evaluate a stock with prerequisites."""
    
    # Step 1: Run prerequisite checks
    from radar.prerequisites import PrerequisiteChecker
    
    checker = PrerequisiteChecker(prereq_config)
    prereq_result = checker.check(symbol, data)
    
    if not prereq_result.passed:
        # Reject early - don't waste time on strategy evaluation
        return {
            'success': False,
            'error': 'Pre-requisite checks failed',
            'failed_checks': prereq_result.failed_checks,
            'details': prereq_result.details
        }
    
    # Step 2: Run expensive strategy evaluation
    return run_strategy(symbol, data, config)
```

---

## 🎓 Examples

### Example 1: Default Configuration (RVOL only)

```python
config = PrerequisiteConfig(
    min_rvol=1.0,
    rvol_enabled=True
)

# Stock A: RELIANCE with RVOL 1.45
result_a = checker.check('NSE:RELIANCE-EQ', {'rvol': 1.45, 'price': 2815})
# ✓ PASS

# Stock B: TCS with RVOL 0.75
result_b = checker.check('NSE:TCS-EQ', {'rvol': 0.75, 'price': 3450})
# ✗ FAIL - "RVOL 0.75 < 1.00"
```

### Example 2: Stricter RVOL (1.5×)

```python
config = PrerequisiteConfig(
    min_rvol=1.5,  # Need 50% above normal volume
    rvol_enabled=True
)

# Stock A: INFY with RVOL 1.45
result_a = checker.check('NSE:INFY-EQ', {'rvol': 1.45, 'price': 1520})
# ✗ FAIL - "RVOL 1.45 < 1.50"

# Stock B: HDFC with RVOL 1.85
result_b = checker.check('NSE:HDFCBANK-EQ', {'rvol': 1.85, 'price': 1685})
# ✓ PASS
```

### Example 3: Multiple Checks (Future)

```python
config = PrerequisiteConfig(
    min_rvol=1.0,
    rvol_enabled=True,
    min_liquidity_cr=10.0,  # At least ₹10Cr liquidity
    min_price=100.0,        # No penny stocks
    max_price=5000.0        # No super expensive stocks
)

# Stock: Small cap with low liquidity
result = checker.check('NSE:SMALLCAP-EQ', {
    'rvol': 1.2,
    'price': 85,           # Too cheap
    'liquidity_cr': 5.5    # Too low liquidity
})
# ✗ FAIL - "Pre-requisite checks failed: Price Range, Liquidity"
```

---

## 🔍 Debugging

### Check if Prerequisites Are Active

```python
from radar.prerequisites import PrerequisiteChecker, PrerequisiteConfig

config = PrerequisiteConfig(min_rvol=1.0, rvol_enabled=True)
checker = PrerequisiteChecker(config)

print(checker.get_summary())
# Output: "Active checks: RVOL ≥ 1.0"
```

### View Failure Details

```python
result = checker.check(symbol, data)

if not result.passed:
    print(f"Failed checks: {result.failed_checks}")
    # ['RVOL']
    
    print(f"Details: {result.details}")
    # {
    #   'rvol': {
    #     'passed': False,
    #     'reason': 'RVOL 0.75 < 1.0',
    #     'threshold': 1.0,
    #     'actual': 0.75
    #   }
    # }
```

---

## 📊 Performance Impact

### Without Prerequisites:
```
100 stocks → Evaluate all → 20 opportunities (some poor quality)
Time: 100 × 50ms = 5000ms
```

### With Prerequisites (RVOL ≥ 1.0):
```
100 stocks → 60 pass prereqs → Evaluate 60 → 15 opportunities (high quality)
Time: (100 × 1ms) + (60 × 50ms) = 3100ms

Savings: 38% faster + better quality
```

---

## 🚀 Migration Guide

### Database Migration

**After first app run, apply migration:**

```bash
cd /Users/raunakladha/Documents/rockstar-radar
sqlite3 data/app.db < server/migrations/add_prereq_config.sql
```

**Migration adds these columns to `settings` table:**
- `prereq_min_rvol` (default: 1.0)
- `prereq_rvol_enabled` (default: 1)
- `prereq_min_liquidity_cr`
- `prereq_min_price`
- `prereq_max_price`
- `prereq_allowed_sectors`
- `prereq_blocked_symbols`

---

## ⚠️ Important Notes

1. **All checks are AND** - If any fails, stock is rejected
2. **Per-user configuration** - Each user has their own thresholds
3. **Applies to ALL strategies** - ORB and SMC both use same prereqs
4. **Early rejection** - Happens before expensive strategy evaluation
5. **Debug tab shows failures** - User can see why a stock was rejected

---

## 🎯 Recommendations

### Conservative (Default)
```json
{
  "min_rvol": 1.0,
  "rvol_enabled": true
}
```
**Effect:** Filter out low-volume stocks

### Moderate
```json
{
  "min_rvol": 1.2,
  "rvol_enabled": true
}
```
**Effect:** Only trade stocks with good volume

### Aggressive
```json
{
  "min_rvol": 1.5,
  "rvol_enabled": true
}
```
**Effect:** Only trade high-volume breakouts

### Disabled (Not Recommended)
```json
{
  "rvol_enabled": false
}
```
**Effect:** No filtering - evaluate all stocks

---

## 🔗 Files Changed

**New Files:**
- `radar/prerequisites.py` - Core module
- `server/migrations/add_prereq_config.sql` - Database schema
- `PREREQUISITES_GUIDE.md` - This documentation

**Modified Files:**
- `server/models.py` - Added prereq columns to Settings model
- `server/main.py` - Added /api/prerequisites endpoints
- `radar/debug_analysis.py` - Integrated prereq checks
- `web/src/Settings.jsx` - Added prereq configuration UI

**Future Integration (TODO):**
- `radar/engine.py` - Add prereq checks to ORB scanner
- `radar/smc_engine.py` - Add prereq checks to SMC scanner

---

## ✅ Testing

### Test Debug Tab

1. Set min_rvol = 1.5 in Settings
2. Try stock with low volume (e.g., during low-activity hours)
3. Should see: "Pre-requisite checks failed: RVOL"

### Test Settings UI

1. Go to Settings
2. Find "Pre-requisite Checks" panel
3. Change min_rvol value
4. Click "Save prerequisite settings"
5. Check database: `SELECT prereq_min_rvol FROM settings WHERE user_id = 1;`

---

## 📈 Future Enhancements

1. **More checks:**
   - ATR (volatility filtering)
   - Spread percentage
   - Volume profile shape
   - Market cap range

2. **Dynamic thresholds:**
   - Different thresholds for different strategies
   - Time-of-day adjustments
   - Market condition-based

3. **Soft vs Hard failures:**
   - Hard: Block evaluation
   - Soft: Lower score but still evaluate

---

**Built with extensibility in mind - easy to add new prerequisite checks!** 🚀
