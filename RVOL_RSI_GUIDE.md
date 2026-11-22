# RVOL and RSI Data - Complete Guide

## ✅ YES - You Have Both RVOL and RSI!

Your system has fully implemented:
- ✅ **RVOL (Relative Volume)** - Cumulative relative volume
- ✅ **RSI (Relative Strength Index)** - Wilder's RSI (14-period)

Both are calculated from OHLCV data and available in your **ORB Radar** system.

---

## 📊 What's Available

### 1. RVOL (Relative Volume)

**File:** `radar/rvol_cum.py`

**What it shows:**
```
RVOL = Today's Cumulative Volume / Average Cumulative Volume (same time)
```

**Example:**
```
Time: 11:30 AM
Today's volume so far: 5,000,000 shares
Average volume by 11:30 AM (last 10 days): 3,000,000 shares

RVOL = 5,000,000 / 3,000,000 = 1.67×
```

**Interpretation:**
- **RVOL > 1.5** = High participation (real move, fuel)
- **RVOL 1.0-1.5** = Normal participation
- **RVOL < 1.0** = Low participation (fade/trap risk)

**Used for:**
- Confirming breakouts (need high RVOL)
- Filtering weak setups (low RVOL = skip)
- Avoiding false breakouts

---

### 2. RSI (Relative Strength Index)

**File:** `radar/indicators.py`

**What it shows:**
```
RSI = Momentum oscillator (0-100)
```

**Calculation:**
- Wilder's RSI (TradingView default)
- 14-period
- Matches what you see on charts

**Interpretation:**
- **RSI > 70** = Overbought (reversal risk)
- **RSI 55-65** = Bullish momentum (LONG preferred)
- **RSI 45-55** = Neutral
- **RSI 35-45** = Bearish momentum (SHORT preferred)
- **RSI < 30** = Oversold (reversal risk)

**Used for:**
- Momentum confirmation
- Directional bias (LONG vs SHORT)
- Avoiding overbought/oversold entries

---

## 🎯 Where This Data Is Used

### Currently Used In: ORB Radar

**ORB (Opening Range Breakout) system uses both:**

1. **Signal Generation** (`radar/engine.py`)
   - RVOL confirms breakouts
   - RSI provides directional bias

2. **Confluence Scoring** (`radar/confluence.py`)
   - RVOL weight: 10 points
   - RSI weight: 10 points
   - Combined with other factors for final score

3. **Minimum Thresholds** (`config.json`)
   ```json
   {
     "min_confirm_rvol": 0.8,
     "min_watch_rvol": 0.5
   }
   ```

**Example Signal:**
```json
{
  "symbol": "NSE:RELIANCE-EQ",
  "side": "LONG",
  "state": "CONFIRMED",
  "score": 86,
  "rvol": 1.67,      ← RVOL data here
  "price": 2805.50,
  "entry": 2806.00,
  "stop": 2795.00
}
```

---

## ❌ NOT Yet Used In: SMC Radar

**SMC Radar currently does NOT use RVOL or RSI.**

SMC scoring uses:
- Zone proximity
- Key levels
- Order blocks
- Fair Value Gaps
- Structure
- Recency

**No volume or momentum indicators yet.**

---

## 🚀 How to Add RVOL/RSI to SMC Radar

### Option 1: Add to SMC Score (Recommended)

Enhance SMC scoring with volume/momentum confirmation:

```python
# In radar/smc_engine.py, calculate_smc_score()

def calculate_smc_score_enhanced(state, current_price, rvol=None, rsi=None):
    """Enhanced SMC score with RVOL and RSI."""
    
    # Existing SMC score (0-100)
    base_score = calculate_smc_score(state, current_price)
    
    # RVOL bonus (0-10 pts)
    rvol_bonus = 0
    if rvol:
        if rvol >= 1.5:
            rvol_bonus = 10  # Strong volume
        elif rvol >= 1.2:
            rvol_bonus = 7   # Good volume
        elif rvol >= 1.0:
            rvol_bonus = 5   # Normal volume
        else:
            rvol_bonus = 0   # Low volume (no bonus)
    
    # RSI alignment (0-10 pts)
    rsi_bonus = 0
    if rsi:
        zone_type = state.opportunity.zone.zone_type if state.opportunity else None
        
        if zone_type == 'PREMIUM':
            # Bearish setup - RSI should be falling
            if 35 <= rsi <= 60:
                rsi_bonus = 10
            elif 60 < rsi < 70:
                rsi_bonus = 5
        elif zone_type == 'DISCOUNT':
            # Bullish setup - RSI should be rising
            if 40 <= rsi <= 65:
                rsi_bonus = 10
            elif 30 < rsi < 40:
                rsi_bonus = 5
    
    # Final score (capped at 100)
    enhanced_score = min(base_score + rvol_bonus + rsi_bonus, 100)
    
    return enhanced_score
```

**Effect:**
- Premium + good RSI + high RVOL: score increases by 15-20 points
- Low RVOL: no bonus (score stays same)
- Wrong RSI (overbought on LONG): no bonus

---

### Option 2: Add as Filter (Alternative)

Use as minimum requirements instead of scoring:

```python
def should_show_opportunity(opportunity, rvol, rsi):
    """Filter SMC opportunities by RVOL and RSI."""
    
    # Require minimum RVOL
    if rvol and rvol < 0.8:
        return False  # Too low volume, skip
    
    # Check RSI extremes
    if rsi:
        if opportunity.zone.zone_type == 'PREMIUM':
            # Don't show BEARISH setups if RSI < 30 (oversold)
            if rsi < 30:
                return False
        elif opportunity.zone.zone_type == 'DISCOUNT':
            # Don't show BULLISH setups if RSI > 70 (overbought)
            if rsi > 70:
                return False
    
    return True
```

---

## 📈 How to Calculate for SMC

### Getting RVOL for a Symbol:

```python
from radar.rvol_cum import rvol_cumulative

# Need: today's volumes + prior sessions
today_volumes = [candle.volume for candle in today_candles]
prior_sessions = [
    [c.volume for c in session1_candles],
    [c.volume for c in session2_candles],
    # ... last 10 sessions
]

rvol = rvol_cumulative(today_volumes, prior_sessions)
# Returns: 1.67 (today is 67% higher volume than usual)
```

### Getting RSI for a Symbol:

```python
from radar.indicators import rsi

# Need: at least 15 closes (14 period + 1)
closes = [candle.close for candle in recent_candles[-20:]]

rsi_value = rsi(closes, period=14)
# Returns: 58.3 (momentum oscillator value)
```

---

## 🎯 Recommendation: Should You Add to SMC?

### Pros:
✅ More confirmation (volume + momentum)  
✅ Filters fake setups (low volume breakouts)  
✅ Avoids extremes (overbought/oversold)  
✅ Data already available (no extra API calls)  
✅ Code already written (just need integration)  

### Cons:
⚠️ More complex scoring (harder to understand)  
⚠️ Might filter too much (fewer opportunities)  
⚠️ SMC already has good filters (OB, FVG, structure)  

### My Recommendation:

**YES - Add RVOL, MAYBE add RSI**

**RVOL is essential:**
- Volume confirms institutional activity
- Low volume = institutional NOT participating
- Complements Order Blocks perfectly

**RSI is optional:**
- SMC already has directional bias (premium/discount)
- But RSI can avoid extremes (overbought/oversold)
- Good for filtering edge cases

**Suggested Implementation:**

```python
# SMC Score Components (after adding RVOL/RSI):

Base SMC Score (0-100):
  - Zone Proximity: 0-35
  - Key Level: 0-30
  - Order Blocks: 0-20
  - FVG: 0-15
  - Structure: 0-10
  - Recency: -5 to +15

Volume Confirmation (0-10):
  - RVOL ≥ 1.5: +10 pts
  - RVOL 1.2-1.5: +7 pts
  - RVOL 1.0-1.2: +5 pts
  - RVOL < 1.0: 0 pts (no penalty, just no bonus)

Momentum Alignment (0-10):
  - RSI aligned with zone: +10 pts
  - RSI neutral: +5 pts
  - RSI misaligned: 0 pts

Total Possible: 120 pts (capped at 100)
```

---

## 📊 Example: RELIANCE with RVOL/RSI

### Current SMC Scoring (Without RVOL/RSI):
```
RELIANCE at ₹2,815 (Premium zone)
  Zone: 32 pts
  Key Level: 25 pts
  Order Block: 15 pts
  FVG: 0 pts
  Structure: 10 pts
  Recency: +5 pts
  ──────────
  TOTAL: 87/100 ← High score
```

### Enhanced with RVOL/RSI:
```
RELIANCE at ₹2,815 (Premium zone)
  Zone: 32 pts
  Key Level: 25 pts
  Order Block: 15 pts
  FVG: 0 pts
  Structure: 10 pts
  Recency: +5 pts
  RVOL (1.8×): +10 pts ← Volume confirms
  RSI (52): +10 pts    ← Momentum aligned
  ──────────
  RAW TOTAL: 107
  FINAL: 100/100 ← Perfect score!
```

**Vs Low Volume Example:**
```
TCS at ₹3,450 (Premium zone)
  Zone: 28 pts
  Key Level: 20 pts
  Order Block: 10 pts
  FVG: 5 pts
  Structure: 5 pts
  Recency: 0 pts
  RVOL (0.6×): 0 pts  ← Low volume, no bonus
  RSI (75): 0 pts     ← Overbought, no bonus
  ──────────
  TOTAL: 68/100 ← Lower score, might skip
```

---

## 🔧 Implementation Checklist

To add RVOL/RSI to SMC Radar:

- [ ] Modify `SMCEngine` to track volume history
- [ ] Calculate RVOL in `_update_opportunity()`
- [ ] Calculate RSI from recent closes
- [ ] Update `calculate_smc_score()` to accept RVOL/RSI
- [ ] Add volume bonus (0-10 pts)
- [ ] Add RSI alignment bonus (0-10 pts)
- [ ] Update score breakdown to show RVOL/RSI components
- [ ] Test with known stocks
- [ ] Update UI to display RVOL/RSI values

---

## 💡 Quick Answer

**Q: Do you have RVOL and RSI data?**

**A: YES!**
- ✅ RVOL is calculated and used in **ORB Radar**
- ✅ RSI is calculated and used in **ORB Radar**
- ❌ NOT yet used in **SMC Radar**
- ✅ Can easily be added to SMC Radar (code exists, just need integration)

**Files:**
- `radar/rvol_cum.py` - RVOL calculation
- `radar/indicators.py` - RSI calculation (line 19)
- `radar/confluence.py` - How they're used for scoring

**Where to see it:**
- ORB Radar tab → RVOL column shows values like "1.67×"
- Internally: RSI used for scoring but not displayed in UI

---

**Want me to add RVOL/RSI to SMC Radar scoring?** I can implement it in ~30 minutes! 🚀
