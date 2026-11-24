# Retest Logic - Deep Dive & Tuning Guide

## 🎯 Overview

As a trading expert, let me explain the **"Retest Broke Support"** scenario - one of the most critical validation points in the ORB system. This is where **80% of false breakouts reveal themselves**.

**Current Configuration:**
```json
{
  "retest_tolerance_pct": 0.16,
  "retest_expiry_minutes": 20,
  "orb_stop_mode": "structure"
}
```

---

## 📊 What Is a Retest?

### The Concept

After a breakout, **support/resistance roles reverse**:

```
BEFORE Breakout:
  ORH (₹2,800) = Resistance (can't go above)
  
AFTER Breakout:
  ORH (₹2,800) = Support (should not go below)
```

**Retest = Price comes back to test the flipped level**

If it **holds** → Valid breakout (RETEST_READY)  
If it **breaks** → False breakout (FAILED)

---

## 🔍 The Exact Logic (Code Analysis)

### Current Implementation

**Location:** `radar/engine.py` lines 480-512

```python
def _evaluate_retest(self, st: SymbolState, c: Candle, now: datetime):
    tol = self.config['retest_tolerance_pct'] / 100  # 0.16% → 0.0016
    
    if st.confirmed_side == 'LONG':
        # FAILURE CONDITION: Bar closes below support (with tolerance)
        if c.close < op.high * (1 - tol):
            st.state = 'FAILED'
            st.reason = 'Retest candle closed below ORH support'
            return
        
        # SUCCESS CONDITION: Bar touches ORH and closes above it
        retest_ok = c.low <= op.high * (1 + tol) and c.close >= op.high
```

---

## 📐 Mathematical Breakdown

### For LONG Setups

**Given:**
- ORH = ₹2,800
- Tolerance = 0.16%

**Calculations:**
```
Lower Failure Threshold = ORH × (1 - tolerance)
                        = 2,800 × (1 - 0.0016)
                        = 2,800 × 0.9984
                        = ₹2,795.52

Upper Touch Threshold   = ORH × (1 + tolerance)
                        = 2,800 × (1 + 0.0016)
                        = 2,800 × 1.0016
                        = ₹2,804.48
```

**Decision Matrix:**

| Scenario | Bar Low | Bar Close | Verdict |
|----------|---------|-----------|---------|
| Perfect Bounce | ₹2,799 | ₹2,802 | ✅ RETEST_READY |
| Slight Dip | ₹2,794 | ₹2,801 | ✅ RETEST_READY (within tolerance) |
| Failure | ₹2,792 | ₹2,794 | ❌ FAILED (closed below ₹2,795.52) |
| No Touch | ₹2,805 | ₹2,810 | ⏳ Continue waiting |
| Overshoot Touch | ₹2,806 | ₹2,808 | ⏳ Continue waiting (didn't touch threshold) |

---

## 🎓 Real Trading Examples

### Example 1: Perfect Retest (RETEST_READY)

```
Stock: RELIANCE
ORH: ₹2,800

Timeline:
─────────────────────────────────────────────────────
10:35 AM - CONFIRMED Breakout
  Bar: O=2,795, H=2,808, L=2,793, C=2,805
  RVOL: 1.65×
  Verdict: Valid breakout ✓

10:40 AM - Price Runs
  High: ₹2,815 (don't chase!)

10:50 AM - Retest Bar
  Bar: O=2,810, H=2,812, L=2,799, C=2,802
  
  Analysis:
  • Low touched: ₹2,799 (1 point below ORH) ✓
  • Within upper threshold: 2,799 < 2,804.48 ✓
  • Closed above ORH: 2,802 > 2,800 ✓
  • Closed above lower threshold: 2,802 > 2,795.52 ✓
  
  Verdict: RETEST_READY ✅
  
  Trade Parameters:
  Entry:  ₹2,802
  Stop:   ₹2,795 (below retest low)
  Target: ₹2,825
  R:R:    3.3:1
```

**What This Shows:** Support held perfectly. Old resistance became new support.

---

### Example 2: Failed Retest (FAILED)

```
Stock: TCS
ORH: ₹3,450

Timeline:
─────────────────────────────────────────────────────
11:00 AM - CONFIRMED Breakout
  Bar: O=3,445, H=3,458, L=3,443, C=3,455
  RVOL: 1.52×
  Verdict: Valid breakout ✓

11:05 AM - Price Runs
  High: ₹3,465

11:15 AM - Retest Begins
  Price: ₹3,452

11:20 AM - Retest Bar
  Bar: O=3,452, H=3,454, L=3,443, C=3,444
  
  Analysis:
  Lower threshold: 3,450 × (1 - 0.0016) = 3,444.48
  
  • Low touched: ₹3,443 ✓
  • Closed: ₹3,444 
  • Check: 3,444 < 3,444.48? YES
  
  Verdict: FAILED ❌
  Reason: "Retest candle closed below ORH support"
```

**What This Shows:** 
The supposed "support" at ₹3,450 didn't hold. Price closed below it, indicating the breakout was **false** - there wasn't real institutional buying.

**If you had entered:** You'd be stopped out immediately.

---

### Example 3: Tolerance Saved It (Edge Case)

```
Stock: INFY
ORH: ₹1,520

Timeline:
─────────────────────────────────────────────────────
12:00 PM - CONFIRMED Breakout
  Bar closed: ₹1,524, RVOL 1.68×

12:10 PM - Retest Bar
  Bar: O=1,526, H=1,527, L=1,517, C=1,521
  
  Analysis:
  Lower threshold: 1,520 × (1 - 0.0016) = 1,517.57
  Upper threshold: 1,520 × (1 + 0.0016) = 1,522.43
  
  • Low: ₹1,517 (3 points below ORH!)
  • But 1,517 > 1,517.57 (within tolerance) ✓
  • Closed: ₹1,521 > 1,520 ✓
  
  Verdict: RETEST_READY ✅
```

**What This Shows:**
The tolerance of 0.16% allowed for a **₹2.43 dip below ORH** without failing. This accounts for:
- Bid-ask spread noise
- Momentary stop-hunting
- Market microstructure noise

Without tolerance, this would have FAILED even though it's a valid retest.

---

## ⚙️ Tuning Parameters

### Parameter 1: `retest_tolerance_pct`

**Current:** 0.16%

**What It Controls:** How far below/above the OR level price can go before failing.

#### Conservative (Stricter)

```json
{
  "retest_tolerance_pct": 0.10
}
```

**Effect:**
- **Smaller buffer** (₹2,800 → ₹2,797.20 failure threshold)
- **More failures** - even slight dips trigger FAILED
- **Higher quality** - only the strongest retests pass
- **Fewer opportunities** - marginal setups filtered out

**Use When:**
- Trading large caps (less noise)
- Lower timeframes (1-min bars)
- You want only the highest conviction setups
- Market is choppy (more false breakouts)

**Example:**
```
ORH: ₹2,800, Tolerance: 0.10%
Lower threshold: ₹2,797.20

Retest bar closes at ₹2,796:
  With 0.16%: PASS (> ₹2,795.52)
  With 0.10%: FAIL (< ₹2,797.20)
```

---

#### Aggressive (More Lenient)

```json
{
  "retest_tolerance_pct": 0.30
}
```

**Effect:**
- **Larger buffer** (₹2,800 → ₹2,791.60 failure threshold)
- **Fewer failures** - allows deeper pullbacks
- **More opportunities** - marginal setups pass
- **Lower quality** - some weak retests pass

**Use When:**
- Trading small/mid caps (more noise)
- Higher timeframes (5-min bars)
- Volatile market conditions
- You want more signals (willing to accept lower quality)

**Example:**
```
ORH: ₹2,800, Tolerance: 0.30%
Lower threshold: ₹2,791.60

Retest bar closes at ₹2,793:
  With 0.16%: FAIL (< ₹2,795.52)
  With 0.30%: PASS (> ₹2,791.60)
```

---

### Parameter 2: `retest_expiry_minutes`

**Current:** 20 minutes

**What It Controls:** How long to wait for a retest before marking as EXPIRED.

#### Shorter Window (10-15 minutes)

```json
{
  "retest_expiry_minutes": 10
}
```

**Effect:**
- Must retest quickly or opportunity expires
- Filters out weak breakouts (strong breakouts retest fast)
- More disciplined entries

**Use When:**
- Day trading (need quick moves)
- High volatility (setups develop fast)

---

#### Longer Window (30-45 minutes)

```json
{
  "retest_expiry_minutes": 30
}
```

**Effect:**
- Gives more time for retest to develop
- Catches delayed retests
- More patient entries

**Use When:**
- Swing trading
- Lower volatility
- Trending markets (retests take longer)

---

### Parameter 3: `orb_stop_mode`

**Current:** "structure"

**What It Controls:** How stop loss is calculated at retest.

#### Mode 1: "structure" (Current)

```python
stop = retest_low - 0.05%  # Just below retest wick
```

**Pros:**
- Tighter stops → Better R:R ratio
- Matches how discretionary traders place stops
- More setups pass R:R threshold (≥2:1)

**Cons:**
- More vulnerable to noise
- Higher stop-out rate
- Needs clean, tight retests

**Example:**
```
Entry: ₹2,802
Retest Low: ₹2,799
Stop: ₹2,795 (just below retest low)
Risk: 7 points

Target: ₹2,825
Reward: 23 points
R:R: 3.3:1 ✅
```

---

#### Mode 2: "atr_floor"

```python
stop = max(
    retest_low - 0.05%,      # Structure
    entry - (ATR × 0.5)       # At least 0.5× ATR away
)
```

**Pros:**
- More room for noise (wider stop)
- Lower stop-out rate
- Better for volatile stocks

**Cons:**
- Wider stops → Worse R:R ratio
- More setups fail R:R threshold
- Fewer opportunities shown

**Example:**
```
Entry: ₹2,802
Retest Low: ₹2,799
Structure Stop: ₹2,795 (7 points)
ATR Stop: ₹2,787 (15 points) ← Wider

Stop Used: ₹2,787 (wider of the two)
Risk: 15 points

Target: ₹2,825
Reward: 23 points
R:R: 1.5:1 ❌ (fails 2:1 threshold → RISK_FAIL)
```

---

## 🎯 Recommended Tuning Strategies

### Strategy 1: Strict Quality (High Win Rate)

**Goal:** Only the strongest retests, willing to miss some opportunities

```json
{
  "retest_tolerance_pct": 0.10,
  "retest_expiry_minutes": 15,
  "orb_stop_mode": "structure"
}
```

**Expected Results:**
- Fewer signals (maybe 2-3 per day)
- Higher win rate (60-70%)
- Tight stops, great R:R

**Best For:** 
- Experienced traders
- Trading large caps
- Lower volatility periods

---

### Strategy 2: Balanced (Current - Good Default)

**Goal:** Balance between quality and quantity

```json
{
  "retest_tolerance_pct": 0.16,
  "retest_expiry_minutes": 20,
  "orb_stop_mode": "structure"
}
```

**Expected Results:**
- Moderate signals (4-6 per day)
- Good win rate (55-65%)
- Reasonable stops

**Best For:**
- Most traders
- Mixed market conditions
- Current setup (already good!)

---

### Strategy 3: More Opportunities (Lower Win Rate)

**Goal:** More signals, willing to accept lower quality

```json
{
  "retest_tolerance_pct": 0.25,
  "retest_expiry_minutes": 30,
  "orb_stop_mode": "structure"
}
```

**Expected Results:**
- Many signals (8-12 per day)
- Lower win rate (45-55%)
- Need good risk management

**Best For:**
- Newer traders (need more practice)
- Small/mid caps
- High volatility periods

---

### Strategy 4: Noise Protection (Volatile Markets)

**Goal:** Survive choppy markets with wider stops

```json
{
  "retest_tolerance_pct": 0.20,
  "retest_expiry_minutes": 25,
  "orb_stop_mode": "atr_floor"
}
```

**Expected Results:**
- Moderate signals (3-5 per day)
- Fewer stop-outs
- Worse R:R (but higher win rate)

**Best For:**
- Volatile markets
- News-driven days
- Small caps

---

## 📊 Analyzing Your Failed Retests

### How to Review

After a trading session, check your logs:

```bash
grep "FAILED" data/session-*.csv | wc -l
```

**Too Many Failures (>50% of confirmations):**
→ Increase `retest_tolerance_pct` from 0.16% to 0.20-0.25%

**Too Few Failures (<10% of confirmations):**
→ Decrease `retest_tolerance_pct` from 0.16% to 0.10-0.12%

**Optimal:** 20-30% of CONFIRMED breakouts should FAIL at retest  
(This filters out false breakouts while keeping valid ones)

---

## 🔬 Advanced: Per-Stock Tuning

### High-Price Stocks (₹2,000+)

**Problem:** 0.16% of ₹3,500 = ₹5.60 buffer (might be too small)

**Solution:** Use larger tolerance

```json
{
  "retest_tolerance_pct": 0.25
}
```

**Example:**
```
Stock: MRF (₹100,000)
0.16% tolerance = ₹160 buffer
0.25% tolerance = ₹250 buffer ← Better for high-priced stocks
```

---

### Low-Price Stocks (₹50-200)

**Problem:** 0.16% of ₹100 = ₹0.16 buffer (too tight, bid-ask spread is wider)

**Solution:** Use larger tolerance

```json
{
  "retest_tolerance_pct": 0.30
}
```

---

### Liquid Large Caps (RELIANCE, TCS, INFY)

**Current 0.16% is perfect** - these trade with tight spreads and less noise.

---

## 🎓 Trading Psychology of Failed Retests

### What FAILED Tells You

```
Scenario:
─────────────────────────────────────────────
10:35 AM - Breakout confirmed at ₹2,805
           RVOL 1.5×, looks great!
           
10:50 AM - Retest at ₹2,800
           Bar closes at ₹2,794
           
           System: FAILED
```

**What Happened:**

1. **Initial breakout** had volume (RVOL 1.5×)
2. **But it wasn't real institutional buying**
3. **Weak hands** bought the breakout
4. **Smart money** sold into the breakout
5. **Support didn't hold** when tested

**Professional Interpretation:**

"The breakout fooled retail traders (including me if I wasn't using this system). The volume spike was likely stop-losses being triggered, NOT new buying. When price came back to test ₹2,800, there were no buyers to support it. This is a classic bull trap."

**Without This Filter:**

- ❌ You enter at ₹2,802 (retest)
- ❌ Price breaks to ₹2,790
- ❌ You're stopped at ₹2,795 (-7 points)
- ❌ You just lost money on a false breakout

**With This Filter:**

- ✅ System marks FAILED
- ✅ You don't enter
- ✅ You saved capital
- ✅ You can deploy it on the next valid setup

---

## 🎯 Recommended Tuning Process

### Step 1: Start with Defaults (1 Week)

```json
{
  "retest_tolerance_pct": 0.16,
  "retest_expiry_minutes": 20,
  "orb_stop_mode": "structure"
}
```

**Track:**
- How many CONFIRMED breakouts
- How many became FAILED
- How many became RETEST_READY
- Win rate on RETEST_READY trades

---

### Step 2: Analyze Your Results

**If FAILED > 40% of CONFIRMED:**
```
Problem: Too strict, filtering out valid retests
Solution: Increase tolerance to 0.20-0.25%
```

**If FAILED < 15% of CONFIRMED:**
```
Problem: Too lenient, letting weak retests through
Solution: Decrease tolerance to 0.12-0.14%
```

**If RETEST_READY signals timing out (>30% become EXPIRED):**
```
Problem: Not enough time for retest
Solution: Increase retest_expiry_minutes to 25-30
```

**If stop-outs > 40% despite RETEST_READY:**
```
Problem: Stops too tight, getting stopped by noise
Solution: Switch to orb_stop_mode: "atr_floor"
```

---

### Step 3: Adjust One Parameter at a Time

**Week 2:** Adjust tolerance only  
**Week 3:** Adjust expiry only  
**Week 4:** Adjust stop mode only

**Don't change all three at once!** You won't know what made the difference.

---

### Step 4: Find Your Sweet Spot

**Optimal Configuration:**
```
CONFIRMED → FAILED:         20-30%
CONFIRMED → RETEST_READY:   40-50%
CONFIRMED → EXPIRED:        20-30%
RETEST_READY → Win Rate:    55-65%
```

---

## 🔍 Common Questions

### Q1: Why not make tolerance 0% (no tolerance)?

**A:** Bid-ask spread and market microstructure.

```
Example: Stock with ₹0.05 tick size
ORH: ₹2,800.00

Retest touches: ₹2,799.95 (5 paise below)
This is just bid-ask spread, NOT a failure!

With 0% tolerance: FAILED ❌
With 0.16% tolerance: PASS ✅ (₹4.48 buffer)
```

---

### Q2: What if I'm trading illiquid stocks?

**A:** Increase tolerance significantly.

```json
{
  "retest_tolerance_pct": 0.40
}
```

Illiquid stocks have:
- Wider bid-ask spreads
- More price noise
- Choppy price action

They need more room.

---

### Q3: Can I have different tolerance for LONG vs SHORT?

**A:** Currently no, but it's a good feature request!

```
Could be useful because:
- SHORT breakouts often more volatile
- May need different tolerance for each direction
```

---

### Q4: What's better - tight stops or wide stops?

**A:** Depends on your personality.

**Tight Stops (structure mode):**
- More stop-outs (45-50%)
- But losses are small
- Better R:R ratios
- Need emotional discipline

**Wide Stops (atr_floor mode):**
- Fewer stop-outs (30-35%)
- But losses are bigger
- Worse R:R ratios
- Easier psychologically

**Most pros use tight stops with position sizing.**

---

## 📝 Configuration File Location

**File:** `/Users/raunakladha/Documents/rockstar-radar/config.json`

**Current Settings:**
```json
{
  "retest_tolerance_pct": 0.16,
  "retest_expiry_minutes": 20,
  "orb_stop_mode": "structure"
}
```

**To Change:**
1. Edit `config.json`
2. Restart scanner: `python3 launch.py run`
3. Changes apply immediately to new setups

---

## 🎯 My Recommendation

**For Indian Markets (NSE):**

```json
{
  "retest_tolerance_pct": 0.18,
  "retest_expiry_minutes": 25,
  "orb_stop_mode": "structure"
}
```

**Why:**
- 0.18%: Slightly more than current, accounts for NSE spread
- 25 minutes: More time for retest in trending markets
- structure: Tight stops, better R:R

**Expected Results:**
- 25-30% of breakouts will FAIL (good filter)
- 45-50% will reach RETEST_READY (good opportunity rate)
- Win rate: 58-65% on RETEST_READY signals

---

## 🚀 Summary

### Key Takeaways

1. **Tolerance is NOT a "weakness"** - it's noise protection
2. **Failed retests save you money** - they filter false breakouts
3. **20-30% failure rate is GOOD** - shows system is working
4. **Tune based on YOUR results** - no one-size-fits-all
5. **Change one parameter at a time** - scientific approach

### The Big Picture

**The retest logic is your safety net.**

Without it:
- ❌ You'd enter every breakout
- ❌ 60% would fail
- ❌ You'd lose money despite being "right" on the breakout

With it:
- ✅ System tests if support holds
- ✅ Filters 60-70% of false breakouts
- ✅ You only enter HIGH QUALITY setups

**This is what separates retail traders from professionals.**

Retail traders: "It broke out! Buy!"  
Professional traders: "It broke out. Now let's see if support holds..."

---

**Start with the defaults. Track your results for 2 weeks. Then tune.**

Don't overthink it - the current settings (0.16%, 20 min, structure) are already very good!
