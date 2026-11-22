# RVOL Calculation Settings - User Guide

## 🎯 Overview

You can now customize how RVOL (Relative Volume) is calculated through the Settings UI. This gives you control over the lookback period, timeframe, and calculation method.

**Location:** Settings → RVOL Calculation Settings

---

## ⚙️ Configuration Options

### 1. Anchor Timeframe

**What it does:** Defines the time period for volume comparison.

**Options:**

| Value | Description | Use Case |
|-------|-------------|----------|
| **Session** | Compares intraday session only | Day traders (09:15-15:30) |
| **Day** (Default) | Compares same time across days | Most users, swing traders |
| **Week** | Compares weekly patterns | Position traders |
| **Month** | Compares monthly patterns | Long-term analysis |

**Example (Day):**
```
Current: 10:30 AM Tuesday
Compares to: 10:30 AM on previous 10 Tuesdays
```

**Example (Session):**
```
Current: 10:30 AM (75 min into session)
Compares to: 75 min into previous 10 sessions
```

**Default:** `day`

---

### 2. Length (Lookback Period)

**What it does:** Number of previous periods to compare against.

**Range:** 1-100

**Default:** `10`

**Examples:**

| Length | Effect | Use Case |
|--------|--------|----------|
| **5** | Recent comparison (1 week) | Fast-moving markets |
| **10** (Default) | Balanced (2 weeks) | Most users |
| **20** | Longer history (1 month) | Stable markets |
| **50** | Extended history (10 weeks) | Research, backtesting |

**Formula:**
```
RVOL = Current Volume / Average of Last N Periods
```

**Default:** `10 days`

---

### 3. Calculation Mode

**What it does:** How to aggregate and compare volume data.

**Options:**

#### Cumulative (Default) ✅

**Formula:**
```
Today's cumulative volume up to current time
─────────────────────────────────────────────
Average cumulative volume at same time
```

**Example:**
```
Time: 11:30 AM
Today's volume (09:15-11:30): 5,000,000
Average volume (09:15-11:30) last 10 days: 3,000,000

RVOL = 5,000,000 / 3,000,000 = 1.67×
```

**Use Case:** Default for most users. Shows if today is trading heavier than normal for this time of day.

---

#### Per Bar (Spot)

**Formula:**
```
Current bar's volume
────────────────────
Median volume at same time slot
```

**Example:**
```
Current bar: 10:30-10:35 AM → 125,000 volume
Median 10:30-10:35 volume (last 10 days): 100,000

RVOL = 125,000 / 100,000 = 1.25×
```

**Use Case:** Traders who want spot volume comparisons for each 5-minute bar.

---

#### Mean Average

**Formula:**
```
Current cumulative volume
─────────────────────────
Mean of historical cumulative volumes
```

**Example:**
```
Today: 5,000,000
Day -1: 3,200,000
Day -2: 2,800,000
...
Day -10: 3,500,000

Mean = (3,200,000 + 2,800,000 + ... + 3,500,000) / 10 = 3,000,000
RVOL = 5,000,000 / 3,000,000 = 1.67×
```

**Use Case:** Standard statistical comparison. Similar to cumulative but explicitly uses mean.

---

#### Median (Robust)

**Formula:**
```
Current cumulative volume
─────────────────────────
Median of historical cumulative volumes
```

**Example:**
```
Today: 5,000,000
Historical volumes sorted: [2,500,000, 2,800,000, 3,000,000, 3,200,000, 3,500,000, ...]
Median (5th value): 3,100,000

RVOL = 5,000,000 / 3,100,000 = 1.61×
```

**Use Case:** Robust to outliers. If historical data has extreme volume days, median ignores them.

---

## 🎓 Examples

### Example 1: Day Trader Setup

**Configuration:**
```json
{
  "anchor_timeframe": "session",
  "length": 5,
  "calculation_mode": "cumulative"
}
```

**Effect:**
- Compares today's intraday volume to last 5 sessions
- Fast adjustment to recent market conditions
- Cumulative shows if participation is building

**Use Case:** Day trading, scalping, quick reactions

---

### Example 2: Swing Trader Setup (Default)

**Configuration:**
```json
{
  "anchor_timeframe": "day",
  "length": 10,
  "calculation_mode": "cumulative"
}
```

**Effect:**
- Compares same time across last 10 days
- Balanced lookback period
- Reliable for most market conditions

**Use Case:** Swing trading, position trading (default for most users)

---

### Example 3: Conservative Setup

**Configuration:**
```json
{
  "anchor_timeframe": "day",
  "length": 20,
  "calculation_mode": "median"
}
```

**Effect:**
- Longer history (20 days)
- Median is robust to extreme volume days
- Smoother RVOL values

**Use Case:** Risk-averse traders, stable markets

---

### Example 4: Aggressive Setup

**Configuration:**
```json
{
  "anchor_timeframe": "session",
  "length": 3,
  "calculation_mode": "per_bar"
}
```

**Effect:**
- Very short lookback (3 sessions)
- Spot volume comparisons
- Quick to detect anomalies

**Use Case:** Momentum trading, news-driven trading

---

## 📊 How It Affects Your Trading

### Impact on Pre-requisite Filtering

**Prerequisite:** `min_rvol = 1.0`

**With Default Settings (Day, 10, Cumulative):**
```
Stock A: RVOL 1.45 (45% above normal for this time) ✓ PASS
Stock B: RVOL 0.85 (15% below normal for this time) ✗ FAIL
```

**With Conservative Settings (Day, 20, Median):**
```
Stock A: RVOL 1.38 (smoother due to longer history) ✓ PASS
Stock B: RVOL 0.90 (less extreme due to median) ✗ FAIL
```

**With Aggressive Settings (Session, 3, Per Bar):**
```
Stock A: RVOL 1.60 (more volatile, recent data) ✓ PASS
Stock B: RVOL 0.75 (more volatile, recent data) ✗ FAIL
```

---

### Impact on Opportunity Count

| Settings | RVOL Values | Opportunities (min_rvol=1.0) |
|----------|-------------|------------------------------|
| **Conservative** (Day, 20, Median) | Smoother, stable | More opportunities pass |
| **Default** (Day, 10, Cumulative) | Balanced | Balanced opportunity count |
| **Aggressive** (Session, 3, Per Bar) | Volatile, sensitive | Fewer opportunities pass |

---

## 🚀 How to Use

### Step 1: Open Settings

```
http://127.0.0.1:8765
→ Settings (gear icon)
→ Scroll to "RVOL Calculation Settings"
```

### Step 2: Configure

**Choose your profile:**

**Day Trader:**
- Anchor: Session
- Length: 5
- Mode: Cumulative

**Swing Trader (Default):**
- Anchor: Day
- Length: 10
- Mode: Cumulative

**Conservative:**
- Anchor: Day
- Length: 20
- Mode: Median

### Step 3: Save

Click **"Save RVOL settings"**

### Step 4: Restart Scanner

**Important:** Scanner must be restarted for changes to take effect.

```bash
# Stop scanner
pkill -f "launch.py run"

# Start scanner
python3 launch.py run
```

---

## ⚠️ Important Notes

### 1. Scanner Restart Required

Changes to RVOL settings require scanner restart because:
- Baselines are calculated at startup
- Volume history is loaded once
- RVOL calculation is baked into engine

**After saving settings:**
```
✓ Settings saved to database
⚠ Scanner still using old settings
→ Restart scanner to apply changes
```

---

### 2. Historical Data Requirements

| Length | Days of Data Required |
|--------|-----------------------|
| 5 | At least 5 trading days |
| 10 | At least 10 trading days |
| 20 | At least 20 trading days |
| 50 | At least 50 trading days |

**If insufficient data:**
- RVOL calculation returns `None`
- Stock fails prerequisite check
- Not shown in opportunities

---

### 3. Mode Comparison

| Mode | Pros | Cons |
|------|------|------|
| **Cumulative** | Shows building participation, default | - |
| **Per Bar** | Spot volume analysis | More volatile |
| **Mean** | Standard statistical method | Affected by outliers |
| **Median** | Robust to outliers | May miss extreme moves |

**Recommendation:** Start with **Cumulative** (default)

---

## 🔍 Troubleshooting

### Issue 1: RVOL Values Changed After Update

**Before:** RVOL = 1.45  
**After:** RVOL = 1.38

**Reason:** Different calculation settings produce different values.

**Solution:** This is expected. Adjust your `min_rvol` threshold accordingly.

---

### Issue 2: Too Few Opportunities

**Symptom:** After changing to aggressive settings, fewer opportunities appear.

**Reason:** Aggressive settings (short lookback, per bar) are more volatile and strict.

**Solution:**
1. Lower `min_rvol` threshold (e.g., 1.0 → 0.8)
2. OR switch to conservative settings
3. OR use longer lookback period

---

### Issue 3: Settings Not Applied

**Symptom:** Changed settings but RVOL values unchanged.

**Reason:** Scanner not restarted.

**Solution:**
```bash
# Stop scanner
pkill -f "launch.py run"

# Start fresh
python3 launch.py run
```

---

## 📈 Best Practices

### 1. Start with Defaults

```json
{
  "anchor_timeframe": "day",
  "length": 10,
  "calculation_mode": "cumulative"
}
```

**Run for 1 week, observe results, then adjust.**

---

### 2. Match Settings to Trading Style

| Trading Style | Recommended Settings |
|--------------|---------------------|
| **Day Trading** | Session, 5, Cumulative |
| **Swing Trading** | Day, 10, Cumulative |
| **Position Trading** | Day, 20, Median |
| **Research** | Day, 50, Mean |

---

### 3. Adjust min_rvol with Settings

| RVOL Settings | Recommended min_rvol |
|---------------|---------------------|
| **Conservative** (longer lookback) | 1.0 (default) |
| **Default** | 1.0-1.2 |
| **Aggressive** (short lookback) | 0.8-1.0 |

**Why:** Aggressive settings produce more volatile RVOL values, so lower threshold compensates.

---

### 4. Monitor Impact

After changing settings:

1. **Check opportunity count** (too many/few?)
2. **Check RVOL values** (changed as expected?)
3. **Check filtering logs** (more/fewer rejections?)
4. **Adjust min_rvol** if needed

---

## 🎯 Summary

### Configuration Location

**Settings → RVOL Calculation Settings**

### Three Parameters

1. **Anchor Timeframe** (day, session, week, month)
2. **Length** (1-100, default: 10)
3. **Calculation Mode** (cumulative, per_bar, mean, median)

### Defaults (Recommended)

```json
{
  "anchor_timeframe": "day",
  "length": 10,
  "calculation_mode": "cumulative"
}
```

### After Changing

**Always restart scanner:**
```bash
pkill -f "launch.py run"
python3 launch.py run
```

---

## 📚 Related Documentation

- **RVOL_RSI_GUIDE.md** - Understanding RVOL and RSI data
- **PREREQUISITES_GUIDE.md** - Pre-requisite checks system
- **PREREQ_SCANNER_INTEGRATION.md** - Scanner integration details

---

**Happy Trading!** 🚀
