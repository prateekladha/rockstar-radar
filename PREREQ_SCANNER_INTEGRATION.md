# Pre-requisite Checks - Scanner Integration

## 🎯 Overview

Pre-requisite checks are now **fully integrated** into both ORB and SMC scanners!

Stocks are filtered at the **API layer** before being shown to users, ensuring each user sees only opportunities that pass their personal prerequisite configuration.

---

## 🏗️ Architecture

### Multi-Tenant Design

```
Scanner Process (Background)
  ↓
  Generates ALL opportunities
  ↓
API Layer (server/main.py)
  ↓
  Applies per-user prerequisite filters
  ↓
User A sees: Opportunities with RVOL ≥ 1.0
User B sees: Opportunities with RVOL ≥ 1.5
```

**Why filter at API layer?**

1. **Scanner is multi-tenant** - One scanner serves multiple users
2. **Per-user settings** - Each user has different thresholds
3. **Performance** - Scanner calculates once, filters are lightweight
4. **Flexibility** - Easy to add more filters without changing scanner

---

## ✅ Integration Points

### 1. ORB Radar (`/api/radar`)

**Field:** `state['all']` (array of opportunities)

**RVOL Location:** `opportunity['rvol']` (direct field)

**Filtering:**
- Filters `state['all']` array
- Also filters `state['top5']` subset
- Adds `state['prereq_filtered']` count

**Example:**
```json
{
  "all": [
    {"symbol": "NSE:RELIANCE-EQ", "rvol": 1.45, "score": 86},
    {"symbol": "NSE:TCS-EQ", "rvol": 0.75, "score": 72}
  ],
  "prereq_filtered": 1
}

// After filtering (min_rvol = 1.0):
{
  "all": [
    {"symbol": "NSE:RELIANCE-EQ", "rvol": 1.45, "score": 86}
  ],
  "prereq_filtered": 1
}
```

---

### 2. SMC Radar (`/api/smc-radar`)

**Field:** `state['opportunities']` (array of opportunities)

**RVOL Location:** `opportunity['confluence']['rvol_cum']` (nested in confluence)

**Filtering:**
- Filters `state['opportunities']` array
- Adds `state['prereq_filtered']` count

**Example:**
```json
{
  "opportunities": [
    {
      "symbol": "NSE:INFY-EQ",
      "score": 87,
      "confluence": {"rvol_cum": 1.6, "rsi": 58}
    },
    {
      "symbol": "NSE:HDFC-EQ",
      "score": 65,
      "confluence": {"rvol_cum": 0.8, "rsi": 52}
    }
  ]
}

// After filtering (min_rvol = 1.0):
{
  "opportunities": [
    {
      "symbol": "NSE:INFY-EQ",
      "score": 87,
      "confluence": {"rvol_cum": 1.6, "rsi": 58}
    }
  ],
  "prereq_filtered": 1
}
```

---

### 3. Debug Tab (`/api/debug-stock`)

**Already integrated** - See previous commit

**Filtering:** Checks prerequisites BEFORE running SMC analysis

---

## 🔧 Implementation Details

### Helper Function: `_apply_prerequisite_filters()`

**Location:** `server/main.py`

**Signature:**
```python
def _apply_prerequisite_filters(
    opportunities: list,
    user: User,
    strategy: str = 'ORB'
) -> tuple[list, int]:
    """Filter opportunities based on user's prerequisite config.

    Returns:
        (filtered_opportunities, rejected_count)
    """
```

**Logic:**
1. Load user's prerequisite configuration from database
2. Create PrerequisiteChecker with user's settings
3. Extract RVOL from opportunity (location depends on strategy)
4. Run prerequisite check on each opportunity
5. Filter out rejected opportunities
6. Return filtered list + rejection count

**RVOL Extraction:**
```python
if strategy == 'ORB':
    # ORB: RVOL is direct field
    rvol = opp.get('rvol')
elif strategy == 'SMC':
    # SMC: RVOL is in confluence.rvol_cum
    confluence = opp.get('confluence') or {}
    rvol = confluence.get('rvol_cum')
```

---

## 📊 Data Flow

### ORB Scanner Flow

```
1. ORB Scanner (radar/engine.py)
   ↓
   Generates opportunities with RVOL
   ↓
2. Dashboard (radar/dashboard.py)
   ↓
   Serializes to JSON: {'all': [...], 'top5': [...]}
   ↓
3. HTTP (port 8765)
   ↓
   scanners.radar_state() fetches state
   ↓
4. API Layer (server/main.py)
   ↓
   _apply_prerequisite_filters(state['all'], user, 'ORB')
   ↓
5. User receives filtered opportunities
```

### SMC Scanner Flow

```
1. SMC Scanner (radar/smc_engine.py)
   ↓
   Generates opportunities with confluence data
   ↓
2. Dashboard (radar/dashboard.py)
   ↓
   Serializes to JSON: {'opportunities': [...]}
   ↓
3. HTTP (port 8765)
   ↓
   /api/smc-state endpoint
   ↓
4. API Layer (server/main.py)
   ↓
   _apply_prerequisite_filters(state['opportunities'], user, 'SMC')
   ↓
5. User receives filtered opportunities
```

---

## 🎓 Examples

### Example 1: User A (Conservative - min_rvol = 1.0)

**ORB Radar:**
```
Scanner generates:
- RELIANCE: RVOL 1.45 ✓
- TCS: RVOL 0.75 ✗
- INFY: RVOL 1.20 ✓

User A sees:
- RELIANCE: RVOL 1.45
- INFY: RVOL 1.20

Filtered: 1 (TCS)
```

**SMC Radar:**
```
Scanner generates:
- HDFC: RVOL 1.65 ✓
- ICICI: RVOL 0.85 ✗
- AXIS: RVOL 1.10 ✓

User A sees:
- HDFC: RVOL 1.65
- AXIS: RVOL 1.10

Filtered: 1 (ICICI)
```

---

### Example 2: User B (Aggressive - min_rvol = 1.5)

**ORB Radar:**
```
Scanner generates:
- RELIANCE: RVOL 1.45 ✗
- TCS: RVOL 0.75 ✗
- INFY: RVOL 1.65 ✓

User B sees:
- INFY: RVOL 1.65

Filtered: 2 (RELIANCE, TCS)
```

**SMC Radar:**
```
Scanner generates:
- HDFC: RVOL 1.65 ✓
- ICICI: RVOL 0.85 ✗
- AXIS: RVOL 1.10 ✗

User B sees:
- HDFC: RVOL 1.65

Filtered: 2 (ICICI, AXIS)
```

---

### Example 3: User C (Disabled - rvol_enabled = false)

**Both Radars:**
```
Scanner generates:
- ALL opportunities

User C sees:
- ALL opportunities (no filtering)

Filtered: 0
```

---

## 🔍 Logging

Rejections are logged to console for debugging:

```
[Prereq] ORB - Rejected NSE:TCS-EQ: Pre-requisite checks failed: RVOL (RVOL=0.75)
[Prereq] ORB - Filtered 3 opportunities for user john@example.com
[Prereq] SMC - Rejected NSE:ICICI-EQ: Pre-requisite checks failed: RVOL (RVOL=0.85)
[Prereq] SMC - Filtered 2 opportunities for user jane@example.com
```

---

## ⚙️ Configuration

### Via UI

Settings → Pre-requisite Checks:
- Enable RVOL Check (toggle)
- Minimum RVOL (input, default: 1.0)

### Via API

```bash
# Get current settings
GET /api/prerequisites

# Update settings
PUT /api/prerequisites
{
  "min_rvol": 1.5,
  "rvol_enabled": true
}
```

### Via Database

```sql
UPDATE settings
SET prereq_min_rvol = 1.5,
    prereq_rvol_enabled = 1
WHERE user_id = 1;
```

---

## 🚀 Performance Impact

### Scanner (No Change)

```
100 stocks → Calculate all 100 → Generate all opportunities
Time: Same as before
```

### API Layer (Lightweight Filtering)

```
100 opportunities → Check 100 × 1ms → Filter 40 → Return 60
Time: +100ms per request (negligible)
```

### User Experience

```
Before: 100 opportunities (some low quality)
After:  60 opportunities (all high quality)

Benefit: Better quality, faster decision making
```

---

## ✅ Testing

### Test ORB Filtering

1. Set min_rvol = 1.5 in Settings
2. Open ORB Radar
3. During low-volume period (e.g., 3:00 PM):
   - Some stocks will have RVOL < 1.5
   - They should NOT appear in opportunities
4. Check console for filtering logs

### Test SMC Filtering

1. Set min_rvol = 1.2 in Settings
2. Open SMC Radar
3. During normal market hours:
   - Stocks with RVOL < 1.2 should be filtered
   - Only high-volume setups appear
4. Check console for filtering logs

### Test Debug Tab

1. Set min_rvol = 1.0 in Settings
2. Try a low-volume stock in Debug tab
3. Should see: "Pre-requisite checks failed: RVOL"
4. Try a high-volume stock
5. Should see: Normal SMC analysis

---

## 📈 Future Enhancements

### 1. More Checks

Add to PrerequisiteConfig:
- Min liquidity (₹Cr)
- Price range (min/max)
- ATR threshold
- Spread percentage
- Sector filter
- Blocked symbols

### 2. Strategy-Specific Filters

Different thresholds for ORB vs SMC:
```python
{
  "orb_min_rvol": 1.5,  # Stricter for ORB
  "smc_min_rvol": 1.0   # Relaxed for SMC
}
```

### 3. Time-Based Filters

Different thresholds by time of day:
```python
{
  "min_rvol_morning": 1.5,  # 09:15-11:00
  "min_rvol_afternoon": 1.0  # 11:00-15:30
}
```

### 4. UI Indicators

Show why stocks were filtered:
```
Opportunities: 15 shown, 8 filtered
  - 5 filtered: Low volume (RVOL < 1.5)
  - 3 filtered: Price too high (> ₹5000)
```

---

## 🎯 Key Benefits

1. ✅ **Quality Filtering** - Only high-quality setups reach users
2. ✅ **Per-User Config** - Each user sets own thresholds
3. ✅ **Multi-Tenant** - Single scanner serves all users efficiently
4. ✅ **Extensible** - Easy to add more checks
5. ✅ **Transparent** - Logging shows what was filtered and why
6. ✅ **Performant** - Lightweight filtering at API layer
7. ✅ **Consistent** - Same logic for ORB, SMC, and Debug tab

---

## 🔗 Related Files

**Core Module:**
- `radar/prerequisites.py` - Prerequisite checking logic

**API Integration:**
- `server/main.py` - Filtering in api_radar and api_smc_radar

**Configuration:**
- `server/models.py` - Database schema
- `web/src/Settings.jsx` - UI configuration

**Documentation:**
- `PREREQUISITES_GUIDE.md` - Complete guide
- `RVOL_RSI_GUIDE.md` - RVOL data guide
- `PREREQ_SCANNER_INTEGRATION.md` - This file

---

**Integration Complete!** 🎉

Both ORB and SMC scanners now filter opportunities based on user's prerequisite configuration.
