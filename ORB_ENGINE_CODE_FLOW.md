# ORB Engine - Complete Code Flow Guide

## 🎯 Overview

This guide explains how the ORB (Opening Range Breakout) engine works - from startup to opportunity generation. Follow this to understand the codebase.

---

## 📂 Entry Point

**File:** `launch.py` (root directory)

**Command to run:**
```bash
python3 launch.py run
```

This is what you execute to start the ORB scanner.

---

## 🔄 Execution Flow

### Level 1: Launch Script (launch.py)

**Purpose:** Entry point, handles command-line arguments and routing

**Key Section:**
```python
# Line 161-163
if args.command == 'run':
    from radar.service import start_live
    start_live(cfg, Path(args.selection), args.port)
```

**What it does:**
1. Loads configuration from `config.json`
2. Reads selection file (`data/today100.json`) - list of stocks to scan
3. Calls `start_live()` from `radar/service.py`

**Read:** Lines 30-163

---

### Level 2: Service Layer (radar/service.py)

**Purpose:** Orchestrates the entire scanning process

#### Function: `start_live(config, selection_path, port)`

**Location:** Line 465

**Flow:**

```python
# 1. Load stock selection
info = read_selection(selection_path)  # List of Instrument objects

# 2. Create ORB Engine (THE CORE)
engine = RadarEngine(info, config, today, on_signal=on_signal)

# 3. Create SMC Engine (for Smart Money Concepts)
smc_engine = SMCEngine(info, config)

# 4. Load historical volume baselines (RVOL calculation)
baselines = build_baselines(adapter, list(engine.states), today, config)
for symbol, values in baselines.items():
    engine.set_baseline(symbol, values)

# 5. Load SMC historical context
smc_loaded = load_smc_history(adapter, smc_engine, today, config)

# 6. Setup real-time data flow
def on_tick(tick):
    engine.update_tick(tick)           # Update ORB engine
    smc_engine.process_tick(tick)      # Update SMC engine
    builder.add_tick(tick)             # Build candles from ticks

def on_bar_completed(symbol, candle):
    engine.ingest_live_bar(symbol, candle)    # ORB processes candle
    smc_engine.process_candle(symbol, candle) # SMC processes candle

# 7. Start WebSocket (real-time data)
adapter.subscribe(list(engine.states), on_tick, engine.update_health)

# 8. Start HTTP dashboard
serve(engine, smc_engine, port=port, mode='LIVE')
```

**Key Functions to Read:**
- `start_live()` - Lines 465-640 (main orchestrator)
- `build_baselines()` - Lines 174-250 (calculates RVOL baselines)
- `load_smc_history()` - Lines 390-430 (loads SMC context)

**Important:** This file connects everything together.

---

### Level 3: ORB Engine (radar/engine.py)

**Purpose:** THE CORE - implements Opening Range Breakout logic

**Location:** Lines 1-700+

#### Class: `RadarEngine`

**Initialization:**
```python
def __init__(self, instruments, config, session, mode='LIVE', on_signal=None):
    # Creates SymbolState for each stock
    self.states: dict[str, SymbolState] = {
        info.symbol: SymbolState(info=info) for info in instruments
    }
    # Configuration
    self.config = config
    self.or_minutes = config['open_range_minutes']  # Default: 5 minutes (09:15-09:20)
    self.bar_minutes = signal_bar_minutes(config)   # 5-minute bars
```

**Location:** Lines 42-85

---

#### Key Methods (Execution Order):

#### 1. **set_baseline()** - Load historical volume data

```python
def set_baseline(self, symbol: str, values: dict[str, float]):
    """Store volume baseline for RVOL calculation"""
    if symbol in self.states:
        self.baselines[symbol] = values
```

**Location:** Line 73

**What it stores:**
```python
baselines['NSE:RELIANCE-EQ'] = {
    '09:15': 125000.0,  # Median volume at 09:15 AM
    '09:20': 135000.0,  # Median volume at 09:20 AM
    '09:25': 142000.0,  # etc...
    # ... for every 5-min slot in the day
}
```

---

#### 2. **update_tick()** - Process real-time price ticks

```python
def update_tick(self, tick: Tick):
    """Process incoming price tick"""
    with self.lock:
        st = self.states.get(tick.symbol)
        if not st:
            return
        
        st.last_tick = tick  # Store current price
        
        # Calculate opening range if in OR window (09:15-09:20)
        if self._in_or_window(candle):
            st.opening = self._build_opening(st)
        
        # Check for WATCH state (price near OR boundary)
        if st.state == 'IDLE' and st.opening:
            self._check_watch(st)
        
        # Check for READY state (all confirmations met)
        if st.state == 'WATCH':
            self._check_ready(st)
        
        # Check for BREAKOUT (price crosses OR boundary)
        if st.state in ('READY', 'WATCH'):
            self._check_breakout_pending(st)
```

**Location:** Lines 87-178

**State Progression:**
```
IDLE → WATCH → READY → BREAKOUT_PENDING → CONFIRMED
```

---

#### 3. **ingest_live_bar()** - Process completed 5-minute candle

```python
def ingest_live_bar(self, symbol: str, candle: Candle):
    """Process a completed 5-minute candle"""
    with self.lock:
        st = self.states.get(symbol)
        if not st:
            return
        
        # Store candle
        st.completed[candle.at.strftime('%H:%M')] = candle
        
        # Calculate RVOL
        st.rvol = self._rvol(symbol, candle)
        
        # Calculate VWAP
        st.vwap = self._candle_vwap(st)
        
        # Update opening range (if still in OR window)
        if self._in_or_window(candle):
            st.opening = self._build_opening(st)
        
        # Check if BREAKOUT_PENDING → CONFIRMED
        if st.state == 'BREAKOUT_PENDING':
            self._confirm_breakout(st, candle)
        
        # Check for RETEST opportunities
        if st.state == 'CONFIRMED':
            self._check_retest(st, candle)
```

**Location:** Lines 326-380

---

#### 4. **_rvol()** - Calculate Relative Volume

```python
def _rvol(self, symbol: str, candle: Candle):
    """Calculate RVOL for current bar"""
    baseline = self.baselines.get(symbol, {}).get(candle.at.strftime('%H:%M'))
    if not baseline or baseline <= 0:
        return None
    return candle.volume / baseline
```

**Location:** Lines 197-201

**Formula:**
```
RVOL = Current Bar Volume / Historical Median Volume (same time)
```

**Example:**
```
Time: 10:30 AM
Current volume: 150,000
Baseline (median last 20 days at 10:30): 100,000
RVOL = 150,000 / 100,000 = 1.5×
```

---

#### 5. **_check_watch()** - Check if price near OR boundary

```python
def _check_watch(self, st: SymbolState):
    """Check if price is within watch distance of OR boundary"""
    if not st.opening or not st.last_tick:
        return
    
    price = st.last_tick.price
    orh = st.opening.high
    orl = st.opening.low
    
    # Check LONG setup (price near ORH)
    if price >= orl and price < orh:
        distance_to_orh = (orh - price) / price * 100
        if distance_to_orh <= self.config['near_boundary_pct']:  # Default: 0.3%
            st.state = 'WATCH'
            st.side = 'LONG'
            st.reason = f'Within {distance_to_orh:.2f}% of ORH'
    
    # Check SHORT setup (price near ORL)
    # ... similar logic
```

**Location:** Lines 228-260

---

#### 6. **_check_ready()** - Check if all confirmations met

```python
def _check_ready(self, st: SymbolState):
    """Check if setup is READY (all confirmations)"""
    if not st.rvol or st.rvol < self.config['min_watch_rvol']:  # Default: 1.0
        return  # Need minimum RVOL
    
    if not st.vwap:
        return  # Need VWAP calculated
    
    # All confirmations met
    st.state = 'READY'
    st.score = self._score(st, st.distance_pct)
    st.reason = 'Setup ready, waiting for breakout'
```

**Location:** Lines 262-280

**Confirmations needed:**
1. ✓ RVOL ≥ min_watch_rvol (default: 1.0)
2. ✓ VWAP available
3. ✓ Price within boundary distance

---

#### 7. **_check_breakout_pending()** - Check if price broke OR

```python
def _check_breakout_pending(self, st: SymbolState):
    """Check if price crossed OR boundary"""
    if not st.opening or not st.last_tick:
        return
    
    price = st.last_tick.price
    
    if st.side == 'LONG':
        # LONG breakout: price > ORH
        if price > st.opening.high:
            st.state = 'BREAKOUT_PENDING'
            st.entry = st.opening.high
            st.stop = st.opening.low
            st.reason = 'Price broke above ORH, awaiting confirmation'
    
    elif st.side == 'SHORT':
        # SHORT breakout: price < ORL
        if price < st.opening.low:
            st.state = 'BREAKOUT_PENDING'
            st.entry = st.opening.low
            st.stop = st.opening.high
            st.reason = 'Price broke below ORL, awaiting confirmation'
```

**Location:** Lines 300-340

---

#### 8. **_confirm_breakout()** - Confirm breakout on bar close

```python
def _confirm_breakout(self, st: SymbolState, candle: Candle):
    """Confirm breakout when bar closes beyond OR"""
    if st.side == 'LONG':
        # Confirm if bar closes above ORH
        if candle.close > st.opening.high:
            if st.rvol >= self.config['min_confirm_rvol']:  # Default: 1.5
                st.state = 'CONFIRMED'
                st.confirmed_at = candle.at
                st.reason = 'Breakout confirmed with volume'
                
                # Fire signal event
                if self.on_signal:
                    self.on_signal(Signal(
                        symbol=st.info.symbol,
                        side='LONG',
                        state='CONFIRMED',
                        price=candle.close,
                        entry=st.entry,
                        stop=st.stop,
                        score=st.score
                    ))
    # ... similar for SHORT
```

**Location:** Lines 380-430

**Confirmation requirements:**
1. ✓ Bar CLOSES beyond OR boundary
2. ✓ RVOL ≥ min_confirm_rvol (default: 1.5)
3. ✓ Other risk checks pass

---

#### 9. **_score()** - Calculate opportunity score

```python
def _score(self, st: SymbolState, distance: float) -> int:
    """Calculate 0-100 score for opportunity"""
    cfg = self.config
    
    # Proximity to OR (30 pts max)
    proximity = max(0, 30 * (1 - max(0.0, distance) / cfg['near_boundary_pct']))
    
    # Volume (30 pts max)
    volume = min(30, 14 * min(st.rvol or 0, 3.0) / 1.5)
    
    # Liquidity (20 pts max)
    liquidity = min(20, st.info.median_turnover_cr / 100 * 20)
    
    # Momentum - price vs VWAP (12 pts)
    momentum = 12 if (st.last_tick and st.vwap and
                      ((st.last_tick.price >= st.vwap) == (st.side == 'LONG'))) else 0
    
    # Opening range width (8 pts)
    width = (8 if st.opening and 0.25 <=
             (st.opening.high - st.opening.low) / st.opening.open * 100 <= 1.8 else 2)
    
    return int(min(100, round(proximity + volume + liquidity + momentum + width)))
```

**Location:** Lines 211-220

**Score Components:**
- **Proximity** (30 pts) - How close to OR boundary
- **Volume** (30 pts) - RVOL confirmation
- **Liquidity** (20 pts) - Stock tradability
- **Momentum** (12 pts) - Price vs VWAP alignment
- **Width** (8 pts) - OR width quality

---

#### 10. **snapshot()** - Return current state for UI

```python
def snapshot(self, reference_time=None):
    """Get current radar state for dashboard"""
    with self.lock:
        rows = []
        for st in self.states.values():
            rows.append({
                'symbol': st.info.symbol,
                'state': st.state,
                'side': st.side,
                'score': st.score,
                'price': st.last_tick.price if st.last_tick else None,
                'orh': st.opening.high if st.opening else None,
                'orl': st.opening.low if st.opening else None,
                'rvol': st.rvol,
                'vwap_proxy': st.vwap,
                'entry': st.entry,
                'stop': st.stop,
                'target': st.target,
                'reason': st.reason
            })
        
        # Sort by state priority and score
        priority = {'RETEST_READY': 0, 'CONFIRMED': 1, 'BREAKOUT_PENDING': 2,
                    'READY': 3, 'WATCH': 4}
        actionable = [r for r in rows if r['state'] in priority]
        actionable.sort(key=lambda r: (priority[r['state']], -r['score']))
        
        return {
            'mode': self.mode,
            'top5': actionable[:5],      # Top 5 opportunities
            'all': sorted(rows, key=lambda r: (-r['score'], r['symbol'])),
            'counts': {...},
            'events': [...]
        }
```

**Location:** Lines 622-693

**This is what the UI displays!**

---

## 📊 Data Models (radar/models.py)

### Key Classes:

#### 1. **Tick** - Real-time price update
```python
@dataclass
class Tick:
    symbol: str           # 'NSE:RELIANCE-EQ'
    price: float          # 2815.50
    time: datetime        # 2026-11-24 10:35:22
    daily_volume: int     # 5250000
```

#### 2. **Candle** - 5-minute OHLCV bar
```python
@dataclass
class Candle:
    at: datetime          # 2026-11-24 10:35:00
    open: float           # 2810.00
    high: float           # 2820.00
    low: float            # 2808.00
    close: float          # 2815.00
    volume: int           # 125000
```

#### 3. **SymbolState** - Per-stock tracking
```python
@dataclass
class SymbolState:
    info: Instrument      # Stock metadata
    state: str            # 'IDLE', 'WATCH', 'READY', 'CONFIRMED', etc.
    side: str             # 'LONG' or 'SHORT'
    score: int            # 0-100
    opening: Candle       # Opening Range (09:15-09:20)
    last_tick: Tick       # Latest price
    rvol: float           # Relative Volume (1.5× = 150% of normal)
    vwap: float           # Volume-Weighted Average Price
    entry: float          # Entry price (ORH for LONG, ORL for SHORT)
    stop: float           # Stop loss
    target: float         # Target price
    reason: str           # Human-readable state reason
```

**Location:** Lines 50-90

---

## 🔄 Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────┐
│ 1. START                                                 │
│    python3 launch.py run                                 │
└─────────────┬───────────────────────────────────────────┘
              │
              ↓
┌─────────────────────────────────────────────────────────┐
│ 2. LAUNCH.PY                                             │
│    - Parse arguments                                     │
│    - Load config.json                                    │
│    - Read data/today100.json (stock list)                │
│    - Call radar.service.start_live()                     │
└─────────────┬───────────────────────────────────────────┘
              │
              ↓
┌─────────────────────────────────────────────────────────┐
│ 3. RADAR/SERVICE.PY                                      │
│    start_live():                                         │
│      a. Create RadarEngine                               │
│      b. Create SMCEngine                                 │
│      c. Load volume baselines (RVOL history)             │
│      d. Load SMC historical context                      │
│      e. Setup WebSocket (real-time data)                 │
│      f. Start HTTP dashboard                             │
└─────────────┬───────────────────────────────────────────┘
              │
              ↓
┌─────────────────────────────────────────────────────────┐
│ 4. REAL-TIME LOOP                                        │
│                                                           │
│    WebSocket receives tick                               │
│           │                                               │
│           ↓                                               │
│    engine.update_tick(tick) ─────────────────┐          │
│           │                                   │          │
│           ↓                                   │          │
│    Check state transitions:                  │          │
│      IDLE → WATCH (near boundary)            │          │
│      WATCH → READY (confirmations met)       │          │
│      READY → BREAKOUT_PENDING (price crossed)│          │
│           │                                   │          │
│           ↓                                   │          │
│    5-minute candle completes                 │          │
│           │                                   │          │
│           ↓                                   │          │
│    engine.ingest_live_bar(candle) ───────────┤          │
│           │                                   │          │
│           ↓                                   │          │
│    BREAKOUT_PENDING → CONFIRMED              │          │
│      - Bar closes beyond OR                  │          │
│      - RVOL ≥ 1.5                            │          │
│      - Fire signal event! 🎉                 │          │
│           │                                   │          │
│           ↓                                   │          │
│    Update dashboard (snapshot())             │          │
│           │                                   │          │
│           └───────────────────────────────────┘          │
│                     ↑                                     │
│                     │                                     │
│                  Repeat                                   │
└───────────────────────────────────────────────────────────┘
              │
              ↓
┌─────────────────────────────────────────────────────────┐
│ 6. UI / API                                              │
│    GET /api/state → engine.snapshot()                    │
│                                                           │
│    Returns:                                               │
│      {                                                    │
│        "top5": [...],      // Top opportunities           │
│        "all": [...],       // All stocks                  │
│        "counts": {...}     // State counts                │
│      }                                                    │
└───────────────────────────────────────────────────────────┘
```

---

## 📚 Reading Order

To understand the code, read in this order:

### Level 1: Entry & Setup (20 min)
1. **launch.py** (lines 30-163) - Entry point
2. **radar/service.py** (lines 465-640) - Orchestration
3. **radar/models.py** (lines 50-90) - Data structures

### Level 2: Core Logic (60 min)
4. **radar/engine.py** (lines 42-85) - Initialization
5. **radar/engine.py** (lines 87-178) - update_tick() - State machine
6. **radar/engine.py** (lines 326-380) - ingest_live_bar() - Candle processing
7. **radar/engine.py** (lines 211-220) - _score() - Scoring logic

### Level 3: Detailed Methods (40 min)
8. **radar/engine.py** (lines 197-201) - _rvol() - RVOL calculation
9. **radar/engine.py** (lines 228-260) - _check_watch() - Watch detection
10. **radar/engine.py** (lines 262-280) - _check_ready() - Ready confirmation
11. **radar/engine.py** (lines 300-340) - _check_breakout_pending() - Breakout detection
12. **radar/engine.py** (lines 380-430) - _confirm_breakout() - Confirmation
13. **radar/engine.py** (lines 622-693) - snapshot() - UI state

### Level 4: Supporting (30 min)
14. **radar/service.py** (lines 174-250) - build_baselines() - RVOL history
15. **radar/dashboard.py** (lines 1-125) - HTTP dashboard
16. **radar/fyers.py** - FYERS API adapter

**Total:** ~2.5 hours to understand core flow

---

## 🎓 Key Concepts

### 1. Opening Range (OR)
```
Time: 09:15 - 09:20 AM (5 minutes)
ORH = Highest price in this period
ORL = Lowest price in this period
```

### 2. Breakout
```
LONG: Price crosses above ORH
SHORT: Price crosses below ORL
```

### 3. RVOL (Relative Volume)
```
RVOL = Current Volume / Historical Median Volume (same time)

Example:
  Current (10:30 AM): 150,000 shares
  Median (10:30 AM, last 20 days): 100,000 shares
  RVOL = 1.5× (50% above normal)
```

### 4. State Machine
```
IDLE → WATCH → READY → BREAKOUT_PENDING → CONFIRMED

IDLE: Waiting for setup
WATCH: Price near OR boundary
READY: All confirmations met
BREAKOUT_PENDING: Price crossed OR, awaiting bar close
CONFIRMED: Breakout confirmed with volume
```

### 5. Score (0-100)
```
Proximity:  30 pts (how close to OR)
Volume:     30 pts (RVOL)
Liquidity:  20 pts (stock tradability)
Momentum:   12 pts (price vs VWAP)
Width:       8 pts (OR quality)
```

---

## 🔍 Important Files

| File | Purpose | Lines to Read |
|------|---------|---------------|
| **launch.py** | Entry point | 30-163 |
| **radar/service.py** | Orchestration | 465-640 |
| **radar/engine.py** | Core ORB logic | All (700+ lines) |
| **radar/models.py** | Data structures | 50-90 |
| **radar/fyers.py** | FYERS API | 1-500 |
| **radar/dashboard.py** | HTTP server | 1-125 |
| **config.json** | Configuration | All |

---

## 🎯 Quick Reference

### Key Configuration (config.json)
```json
{
  "open_range_minutes": 5,        // 09:15-09:20
  "near_boundary_pct": 0.3,       // Watch distance
  "min_watch_rvol": 1.0,          // Ready threshold
  "min_confirm_rvol": 1.5,        // Confirm threshold
  "new_signals_stop": "11:30"     // Stop generating new signals
}
```

### Key State Transitions
```
Price near ORH + RVOL ≥ 1.0 → WATCH
WATCH + All confirmations → READY
READY + Price > ORH → BREAKOUT_PENDING
BREAKOUT_PENDING + Bar closes > ORH + RVOL ≥ 1.5 → CONFIRMED
```

---

## 🚀 Next Steps

After reading the code:

1. **Run with debugging:**
   ```bash
   python3 launch.py run
   ```
   Watch console output to see state transitions.

2. **Open dashboard:**
   ```
   http://127.0.0.1:8765
   ```
   See live opportunities.

3. **Add print statements:**
   ```python
   # In radar/engine.py
   def _check_watch(self, st):
       print(f"[WATCH CHECK] {st.info.symbol}: price={st.last_tick.price}, orh={st.opening.high}")
       # ... rest of function
   ```

4. **Test with one stock:**
   Edit `data/today100.json` to include just one symbol for easier debugging.

---

**Happy Reading!** 🎉

Start with `launch.py` and follow the flow step by step!
