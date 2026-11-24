# Display States - Signal Health & Freshness Indicators

## 🎯 Overview

The ORB system has **two layers of states**:

1. **Internal States** - The actual trading state (WATCH, READY, CONFIRMED, etc.)
2. **Display States** - What the UI shows (adds health/freshness indicators)

**Display States = Internal State + Real-Time Health Check**

---

## 📊 The Display States

### Display State Categories

```
┌─────────────────────────────────────────────┐
│ HEALTH INDICATORS (Override Internal State) │
│ - HALTED                                     │
│ - SESSION_CLOSED                             │
│ - STALE                                      │
│ - SIGNAL_AGED                                │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│ NORMAL STATES (Show Internal State As-Is)   │
│ - WATCH, READY, CONFIRMED, RETEST_READY...  │
└─────────────────────────────────────────────┘
```

**Key Insight:** Health indicators **override** the internal state for display purposes to warn users about data quality or signal freshness.

---

## 🔍 Display State #1: HALTED

### What It Means

**System-wide shutdown** - all trading signals suppressed.

```
Display State:  HALTED
Internal State: (any - doesn't matter)
Message:        "FYERS data unavailable; no actionable signals"
```

### When It Appears

**Triggered When:**
- FYERS WebSocket disconnects
- API rate limit exceeded
- Authentication fails
- Broker returns error

**Code Logic:**
```python
if self.halted:
    visible = 'HALTED'
    # Overrides all other states
```

### Trading Significance

**⛔ DO NOT TRADE**

**What Happened:**
```
Timeline:
─────────────────────────────────────────────
10:30 AM - System running normally
           RELIANCE: RETEST_READY (looks good!)
           
10:35 AM - FYERS WebSocket dies
           System detects disconnect
           
           ALL stocks → HALTED
           
10:36 AM - You see "HALTED" on UI
           RELIANCE still shows HALTED (not RETEST_READY)
```

**Why This Exists:**

Without real-time data:
- ❌ Price shown is outdated
- ❌ RVOL calculation is wrong
- ❌ Signals are unreliable
- ❌ You'd trade on stale data

**Protection:** System shows HALTED to prevent trading on bad data.

**What To Do:**
1. Check terminal/logs for error message
2. Usually resolves in 1-2 minutes (auto-reconnect)
3. If persists >5 min, restart scanner

**Common Causes:**
- API rate limit (made too many requests)
- Token expired (need to re-login)
- Network issues
- FYERS server maintenance

---

## 🔍 Display State #2: SESSION_CLOSED

### What It Means

**Market closed** - no new signals generated.

```
Display State:  SESSION_CLOSED
Internal State: SESSION_CLOSED (same)
Time:           After 11:30 AM (default new_signals_stop)
```

### When It Appears

**Triggered When:**
- Current time > `new_signals_stop` + `retest_expiry_minutes`
- Default: After 11:50 AM (11:30 + 20 minutes)

**Code Logic:**
```python
if st.state == 'SESSION_CLOSED':
    visible = 'SESSION_CLOSED'
```

### Trading Significance

**📊 Review-Only Mode**

**What This Means:**

```
Configuration:
  new_signals_stop = "11:30"
  retest_expiry_minutes = 20

Timeline:
─────────────────────────────────────────────
11:30 AM - Last new signal can be generated
           (WATCH → READY → CONFIRMED)
           
11:50 AM - System enters SESSION_CLOSED
           (11:30 + 20 min grace period)
           
           All stocks → SESSION_CLOSED
           
12:00 PM - You see historical signals
           But no new signals generated
```

**Why This Exists:**

**Problem Without This:**
```
1:00 PM - Stock breaks out with RVOL 1.5×
          System: CONFIRMED ✓
          
You: "Sweet! Let me enter..."

Reality: It's 1:00 PM - too late in the day!
         - Low liquidity
         - Wider spreads
         - Exit at 3:30 PM (only 2.5 hours)
         - Market behaves differently late day
```

**Protection:** No new signals after trading window closes.

**What To Do:**
- Review historical signals (learning)
- Prepare for tomorrow
- **DO NOT** trade signals generated after 11:30 AM

**Configuration:**

To change the cutoff time:

```json
{
  "new_signals_stop": "12:00"  // Generate signals until noon
}
```

**Use Cases:**
- **11:30** (default): Conservative, avoid late-day trades
- **12:00**: Moderate, still have afternoon window
- **14:00**: Aggressive, trade all day (not recommended)

---

## 🔍 Display State #3: STALE

### What It Means

**Data feed is old** - no recent price updates.

```
Display State:  STALE
Internal State: (any - WATCH, READY, etc.)
Condition:      No tick received in last 30 seconds
```

### When It Appears

**Triggered When:**
```python
stale = (last_tick is None or 
         (now - last_tick.time) > 30 seconds)

if stale and st.opening exists:
    visible = 'STALE'
```

**Configuration:**
```json
{
  "market_feed_stale_seconds": 30
}
```

### Trading Significance

**⚠️ DATA QUALITY WARNING**

**Scenario 1: Illiquid Stock**

```
Stock: SMALL-CAP (₹150)

Timeline:
─────────────────────────────────────────────
10:30:00 - Last tick: ₹152.50
           State: READY
           
10:30:35 - 35 seconds passed, no new tick
           Display: STALE (was READY)
           
10:30:45 - Still no tick
           Display: STALE
           
10:31:10 - New tick: ₹152.60
           Display: READY (back to normal)
```

**Why:** Small caps trade infrequently. 30-60 second gaps are normal.

---

**Scenario 2: System Issue**

```
Stock: RELIANCE (very liquid)

Timeline:
─────────────────────────────────────────────
10:30:00 - Last tick: ₹2,805
           State: RETEST_READY
           
10:30:35 - No tick in 35 seconds (unusual!)
           Display: STALE
           
Problem: RELIANCE trades every second!
         Gap means data feed issue
```

**Why:** Network glitch or WebSocket hiccup.

---

**What To Do:**

**If only 1-2 stocks show STALE:**
→ Normal (those stocks are illiquid)
→ OK to ignore

**If MANY stocks show STALE:**
→ Data feed problem
→ Check network connection
→ Wait 1-2 minutes
→ If persists, restart scanner

**If RETEST_READY → STALE:**
→ **DO NOT ENTER** until it comes back
→ Price shown is outdated (30+ seconds old)
→ Wait for fresh tick

**Configuration Tuning:**

```json
// More lenient (for illiquid stocks)
{
  "market_feed_stale_seconds": 60
}

// Stricter (for liquid stocks only)
{
  "market_feed_stale_seconds": 20
}
```

---

## 🔍 Display State #4: SIGNAL_AGED

### What It Means

**Signal is old** - entry opportunity passed.

```
Display State:  SIGNAL_AGED
Internal State: RETEST_READY (still valid structurally)
Condition:      Signal generated >5 minutes ago
```

### When It Appears

**Triggered When:**
```python
if (st.state == 'RETEST_READY' and
    (now - st.last_signal_time) > 300 seconds):  # 5 minutes
    visible = 'SIGNAL_AGED'
```

**Hardcoded:** 300 seconds (5 minutes) - not configurable

### Trading Significance

**⏰ ENTRY WINDOW EXPIRED**

**Complete Example:**

```
Stock: TCS
Timeline:
─────────────────────────────────────────────
11:00 AM - CONFIRMED breakout at ₹3,455

11:15 AM - RETEST_READY
           Entry: ₹3,452
           Stop:  ₹3,445
           Target: ₹3,475
           R:R: 3.2:1 ✅
           
           Display: RETEST_READY (enter now!)
           
11:16 AM - You're away from desk...

11:17 AM - Still shows RETEST_READY

11:20 AM - 5 minutes passed since signal
           Display changes: SIGNAL_AGED
           
           Internal state: Still RETEST_READY
           But display: SIGNAL_AGED
           
11:21 AM - You return to desk
           Price now: ₹3,460 (moved away!)
```

**What Changed:**

| Time | Display | Internal | Price | Action |
|------|---------|----------|-------|--------|
| 11:15 | RETEST_READY | RETEST_READY | ₹3,452 | ✅ Enter |
| 11:17 | RETEST_READY | RETEST_READY | ₹3,453 | ✅ Still OK |
| 11:20 | SIGNAL_AGED | RETEST_READY | ₹3,458 | ⚠️ Late! |
| 11:21 | SIGNAL_AGED | RETEST_READY | ₹3,460 | ❌ Too late |

---

### Why This Exists

**Problem: Stale Entry Points**

```
Optimal Entry: ₹3,452 (at retest)
5 minutes later: ₹3,460 (8 points higher)

If you enter at ₹3,460:
  Entry: ₹3,460 (not ₹3,452)
  Stop:  ₹3,445 (same)
  Target: ₹3,475 (same)
  
  Risk:   15 points (was 7) ← 2× worse!
  Reward: 15 points (was 23) ← 35% worse!
  R:R:    1:1 (was 3.2:1) ← Terrible!
```

**Protection:** Prevents chasing stale entry points.

---

### What To Do

**When You See SIGNAL_AGED:**

**Option 1: Skip It (Recommended)**
```
"Entry point passed. Looking for next opportunity."
```

**Option 2: Reassess (Advanced)**
```
Check current price vs entry:
  
If price < entry + 50%:
  → Might still be OK
  → Recalculate R:R manually
  → If still ≥2:1, consider entry
  
If price > entry + 50%:
  → Skip it
  → Entry window closed
```

**Example Reassessment:**
```
Original Signal (11:15):
  Entry: ₹3,452, Stop: ₹3,445, Target: ₹3,475
  R:R: 3.2:1 ✅

5 Minutes Later (11:20 - SIGNAL_AGED):
  Current: ₹3,456 (4 points higher)
  New R:R: (3,475-3,456)/(3,456-3,445) = 19/11 = 1.7:1
  
  Verdict: Still OK (>1.5:1), can enter
  
5 More Minutes (11:25):
  Current: ₹3,462 (10 points higher)
  New R:R: (3,475-3,462)/(3,462-3,445) = 13/17 = 0.76:1
  
  Verdict: Skip it (< 1:1), entry window closed
```

---

### Trading Psychology

**SIGNAL_AGED teaches discipline:**

**Retail Trader Behavior:**
```
11:15 - Signal appears: RETEST_READY
        "Oh cool, let me finish this coffee..."
        
11:20 - Returns: "Let me enter now"
        Price has moved
        Enters at worse price
        Gets stopped out
        "This system doesn't work!"
```

**Professional Behavior:**
```
11:15 - Signal appears: RETEST_READY
        "Entry opportunity NOW"
        Enters immediately at ₹3,452
        
11:20 - Already in position
        Managing trade
```

**System Behavior:**
```
11:15 - Shows: RETEST_READY
        
11:20 - Shows: SIGNAL_AGED
        Message: "You missed the entry window"
        
Trader: "OK, I'll catch the next one"
        Discipline maintained ✅
```

---

## 📊 Display State Priority (Hierarchy)

**When multiple conditions are true, what shows?**

```
Priority Order (Highest to Lowest):
─────────────────────────────────────────────
1. HALTED              (system-wide emergency)
   ↓
2. SESSION_CLOSED      (market closed)
   ↓
3. STALE               (data feed issue)
   ↓
4. SIGNAL_AGED         (old signal)
   ↓
5. <Internal State>    (normal - show as-is)
```

**Example Scenario:**

```
Conditions:
  - Internal state: RETEST_READY
  - Last tick: 35 seconds ago (STALE)
  - Signal age: 6 minutes (SIGNAL_AGED)
  - System: Running normally

Display: STALE (priority #3 wins over #4)
```

**Why:** Data quality (STALE) is more critical than signal age (SIGNAL_AGED).

---

## 🎯 Practical Guide for Traders

### Decision Matrix

| Display State | Action | Explanation |
|---------------|--------|-------------|
| **HALTED** | ⛔ Stop trading | Data feed broken |
| **SESSION_CLOSED** | 📊 Review only | Trading window closed |
| **STALE** | ⏸️ Pause | Wait for fresh tick |
| **SIGNAL_AGED** | ⏰ Reassess | Entry window passed |
| **RETEST_READY** | ✅ Enter now | Fresh signal! |
| **CONFIRMED** | 👀 Watch | Wait for retest |
| **READY** | 🟡 Alert | Breakout imminent |

---

### Real-Time Checklist

**Before Entering Any Trade:**

✅ **Check Display State**
```
Is it RETEST_READY? → Good ✅
Is it SIGNAL_AGED?  → Reassess ⚠️
Is it STALE?        → Wait ⏸️
```

✅ **Check Signal Age**
```
<2 minutes old?  → Fresh ✅
2-5 minutes old? → OK ⚠️
>5 minutes old?  → Likely SIGNAL_AGED ❌
```

✅ **Check Data Freshness**
```
Last tick: <10 seconds ago? → Fresh ✅
Last tick: 10-30 seconds?   → OK ⚠️
Last tick: >30 seconds?      → STALE ❌
```

---

## ⚙️ Configuration Summary

**Relevant Settings:**

```json
{
  "market_feed_stale_seconds": 30,
  "new_signals_stop": "11:30",
  "retest_expiry_minutes": 20
}
```

**SIGNAL_AGED threshold:** 300 seconds (5 minutes, hardcoded)

---

## 🎓 Key Takeaways

### 1. Two-Layer State System

**Internal State:** Trading logic  
**Display State:** Health + Freshness

### 2. Display States Are Warnings

**Not errors** - they're **protections**:
- HALTED → Protects from bad data
- STALE → Protects from outdated price
- SIGNAL_AGED → Protects from chasing

### 3. Act Fast on RETEST_READY

```
RETEST_READY → You have ~2-3 minutes

After 5 minutes → SIGNAL_AGED

Don't hesitate! Enter when signals are fresh.
```

### 4. Health Monitoring is Automatic

System constantly checks:
- ✓ Is data feed alive?
- ✓ Are ticks recent?
- ✓ Are signals fresh?
- ✓ Is trading window open?

You don't need to monitor - **system tells you!**

---

## 💡 Pro Tips

### Tip 1: Monitor Terminal Output

```bash
python3 launch.py run
```

**Watch for:**
```
FYERS WebSocket connected ✓
Received tick: RELIANCE ₹2,805
Received tick: TCS ₹3,452
...

If you see:
WebSocket disconnected ⚠️
Reconnecting... ⚠️

→ Expect HALTED or STALE temporarily
```

---

### Tip 2: Signal Age on UI

The UI shows `signal_age_sec` for each opportunity:

```
RETEST_READY
RELIANCE | Entry ₹2,802 | Signal Age: 45s ✅ Fresh!

RETEST_READY  
TCS | Entry ₹3,452 | Signal Age: 312s ⚠️ SIGNAL_AGED
```

**Use this to prioritize:**
- <120s: Fresh, enter now
- 120-300s: OK, but hurry
- >300s: SIGNAL_AGED, reassess

---

### Tip 3: Dashboard Color Coding

**Visual Indicators:**

```
🟢 RETEST_READY (fresh)      → Enter
🟡 RETEST_READY (2-5 min)    → Enter quickly
🔴 SIGNAL_AGED (>5 min)      → Reassess
⚫ STALE                      → Wait
⛔ HALTED                     → Stop
```

---

## 🚀 Summary

**Display States = Internal State + Real-Time Health**

**Four Health Indicators:**
1. **HALTED** - System emergency (don't trade)
2. **SESSION_CLOSED** - Market closed (review only)
3. **STALE** - Data feed delay (wait)
4. **SIGNAL_AGED** - Signal old (reassess)

**These states PROTECT you from:**
- ❌ Trading on bad data (HALTED)
- ❌ Late-day trades (SESSION_CLOSED)
- ❌ Outdated prices (STALE)
- ❌ Chasing (SIGNAL_AGED)

**Key Rule:**

**Only enter trades when:**
✅ Display shows RETEST_READY (not SIGNAL_AGED)  
✅ Signal age < 300 seconds  
✅ No STALE indicator  
✅ System not HALTED  

**This is what separates professional trading systems from amateur ones - automatic health monitoring!** 🎯
