# Simulation/Backtesting System - Implementation Guide

## 🎯 Overview

A comprehensive simulation system that allows traders to test strategies on historical data before risking real money.

**Key Features:**
- Replay specific historical days with real FYERS data
- Test multiple configuration variations
- See what auto-trades would have executed
- Review missed opportunities (journal)
- Compare results across configurations
- Build confidence before live trading

---

## 🏗️ Architecture

### System Components

```
┌──────────────────────────────────────────────────────────────┐
│                     User Interface (Web)                      │
│  - Create Sim Run Form                                       │
│  - Run List & Status                                         │
│  - Results Viewer (Journal, Trades, Metrics)                 │
│  - Comparison Dashboard                                       │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│                     API Layer (FastAPI)                       │
│  - POST /api/sim/runs (create)                              │
│  - GET /api/sim/runs (list)                                 │
│  - GET /api/sim/runs/:id (details)                          │
│  - POST /api/sim/runs/:id/start (trigger)                   │
│  - GET /api/sim/runs/:id/journal (opportunities)            │
│  - GET /api/sim/runs/:id/trades (orders)                    │
│  - GET /api/sim/compare?ids=1,2,3 (compare runs)            │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│                 Simulation Controller                         │
│  1. Load historical data (from cache or fetch)               │
│  2. Initialize ORB engine with custom config                 │
│  3. Replay bars chronologically                              │
│  4. Record opportunities (journal)                           │
│  5. Execute simulated auto-trades                            │
│  6. Process exits (stops/targets)                            │
│  7. Calculate metrics & finalize                             │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│              Historical Data Fetcher                          │
│  - Fetch from FYERS API (1-min or 5-min bars)               │
│  - Cache in sim_historical_bars table                        │
│  - Reuse cached data across sim runs                         │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│                     Database (SQLite)                         │
│  - sim_runs                                                  │
│  - sim_historical_bars (cached data)                         │
│  - sim_signal_logs (journal entries)                         │
│  - sim_orders (trades)                                       │
│  - sim_replay_events (for replay viewer)                     │
└──────────────────────────────────────────────────────────────┘
```

---

## 📊 Database Schema

### sim_runs
Metadata for each simulation run.

```sql
CREATE TABLE sim_runs (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    name TEXT,                     -- "Nov 15 - Tolerance 0.18%"
    description TEXT,
    config TEXT,                   -- JSON snapshot of strategy config
    start_date TEXT,               -- "2024-11-15"
    start_time TEXT,               -- "09:15"
    end_date TEXT,                 -- "2024-11-15"
    end_time TEXT,                 -- "15:30"
    bar_interval TEXT,             -- "1" or "5" minutes
    status TEXT,                   -- pending, fetching_data, running, completed, failed
    progress_pct INTEGER,
    error_message TEXT,
    created_at TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    
    -- Results (populated after completion)
    total_opportunities INTEGER,
    total_trades INTEGER,
    total_pnl REAL,
    win_rate REAL,
    expectancy_r REAL,
    total_r REAL,
    max_drawdown_r REAL
)
```

### sim_historical_bars
Cached historical market data (shared across all sim runs).

```sql
CREATE TABLE sim_historical_bars (
    id INTEGER PRIMARY KEY,
    symbol TEXT,                   -- "NSE:RELIANCE-EQ"
    date TEXT,                     -- "2024-11-15"
    bar_interval TEXT,             -- "1" or "5"
    timestamp TEXT,                -- "2024-11-15T09:20:00+05:30"
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    
    UNIQUE(symbol, date, bar_interval, timestamp)
)
```

### sim_signal_logs
Journal entries (opportunities flagged during simulation).

```sql
CREATE TABLE sim_signal_logs (
    id INTEGER PRIMARY KEY,
    sim_run_id INTEGER,
    user_id INTEGER,
    day TEXT,
    sim_time TEXT,
    symbol TEXT,
    side TEXT,
    state TEXT,
    score INTEGER,
    entry TEXT,
    stop TEXT,
    target TEXT,
    net_rr TEXT,
    rvol TEXT,
    provisional INTEGER,
    timeline TEXT                  -- JSON array of state transitions
)
```

### sim_orders
Trades executed during simulation.

```sql
CREATE TABLE sim_orders (
    id INTEGER PRIMARY KEY,
    sim_run_id INTEGER,
    user_id INTEGER,
    symbol TEXT,
    side TEXT,
    qty INTEGER,
    entry REAL,
    stop REAL,
    target REAL,
    status TEXT,                   -- "open", "closed"
    created_at TEXT,               -- Sim timestamp
    closed_at TEXT,
    close_reason TEXT,             -- "target", "stop", "eod"
    close_price REAL,
    pnl REAL,
    result_r REAL
)
```

---

## 🔧 Components Implemented

### ✅ Phase 1: Foundation (COMPLETED)

**Database Schema:**
- `server/migrations/create_simulation_tables.sql` - All tables

**Models:**
- `server/models.py` - Added 5 new models:
  - `SimRun` - Simulation run metadata
  - `SimHistoricalBar` - Cached historical data
  - `SimSignalLog` - Journal entries
  - `SimOrder` - Trades
  - `SimReplayEvent` - Replay viewer events

**Historical Data Fetcher:**
- `server/sim_data_fetcher.py` - `HistoricalDataFetcher` class
  - Fetches data from FYERS API
  - Caches in database
  - Supports both 1-min and 5-min bars
  - Handles rate limiting
  - Estimates storage requirements

---

### ✅ Phase 2: Simulation Controller (COMPLETED)

**Core Replay Engine:**
- `server/sim_controller.py` - `SimulationController` class
  - Loads historical data
  - Replays bars chronologically
  - Records opportunities (journal)
  - Executes simulated auto-trades
  - Processes exits (stops/targets)
  - Calculates P&L and metrics
  - Finalizes with summary stats

**Key Features:**
- Accelerated replay (runs full day in seconds)
- Respects user's strategy configuration
- Instant order fills at signal price
- Automatic stop/target processing
- Comprehensive metrics calculation

---

### 🚧 Phase 3: API Endpoints (TODO)

**Endpoints to Implement:**
```python
POST   /api/sim/runs              # Create new sim run
GET    /api/sim/runs              # List user's sim runs
GET    /api/sim/runs/:id          # Get run details
POST   /api/sim/runs/:id/start    # Trigger simulation
DELETE /api/sim/runs/:id          # Delete sim run
GET    /api/sim/runs/:id/journal  # Get opportunities
GET    /api/sim/runs/:id/trades   # Get trades
GET    /api/sim/compare           # Compare multiple runs
```

---

### 🚧 Phase 4: Basic UI (TODO)

**Components to Build:**
```jsx
// web/src/Simulation.jsx
- SimulationPage (main container)
- CreateSimRunForm (create new sim)
- SimRunList (list of runs with status)
- SimRunDetails (view results)
```

**Features:**
- Create sim run with date/time/config
- Monitor run status & progress
- View journal (opportunities)
- View trades & P&L
- Basic metrics display

---

### 🚧 Phase 5: Advanced UI (TODO)

**Components to Build:**
```jsx
// web/src/SimComparison.jsx
- SimComparisonView (side-by-side comparison)
- MetricsDashboard (charts & graphs)
- ConfigOptimizer (find best params)
- ReplayViewer (watch replay)
```

**Features:**
- Compare 2-3 runs side-by-side
- Metrics visualization (equity curve, drawdown)
- Configuration parameter tuning
- Replay animation viewer

---

## 🎓 User Workflow Example

### Step 1: Create Simulation Run

```
User Input:
  Name: "Nov 15 - Aggressive Setup"
  Date: 2024-11-15
  Time: 09:15 - 15:30
  Bar Interval: 1 minute
  
  Configuration:
    retest_tolerance_pct: 0.18 (vs default 0.16)
    prereq_min_rvol: 1.5 (vs default 1.0)
    auto_paper_trade: enabled
    capital_inr: 100000
    risk_pct: 1.0
```

### Step 2: System Processes

```
1. Status: pending → fetching_data
   - Check cache for 2024-11-15 1-min bars
   - If missing, fetch from FYERS API
   - Progress: 0% → 100%

2. Status: fetching_data → running
   - Load 500 symbols × ~375 bars = 187,500 bars
   - Replay chronologically
   - Progress: 0% → 100%

3. Status: running → completed
   - Calculate final metrics
   - Display results
```

### Step 3: Review Results

```
Simulation Results:
  Total Opportunities: 28
  Auto-Trades Executed: 10
  Win Rate: 70%
  Total R: +8.5R
  Total P&L: +₹8,500
  Max Drawdown: -2.1R
  
Compare vs Default Config:
  - 4 more opportunities (28 vs 24)
  - 2 more trades (10 vs 8)
  - Better R (+8.5R vs +6.2R)
  - Conclusion: 0.18% tolerance is better!
```

### Step 4: Test More Days

```
Create runs for last 10 trading days:
  - Nov 15 (0.18%) → +8.5R
  - Nov 14 (0.18%) → +6.2R
  - Nov 13 (0.18%) → +4.8R
  ...
  
  Average: +6.5R per day
  vs Default (0.16%): +5.2R per day
  
  Decision: Deploy 0.18% tolerance to production!
```

---

## 🔧 Configuration Scope

**Adjustable per Sim Run:**

✅ **Strategy Parameters:**
- `retest_tolerance_pct`
- `retest_expiry_minutes`
- `orb_stop_mode` (structure vs atr_floor)
- `bar_interval` (1-min vs 5-min)

✅ **Risk Settings:**
- `capital_inr`
- `risk_pct`
- `max_trades_per_symbol`

✅ **Prerequisites:**
- `prereq_min_rvol`
- `prereq_rvol_enabled`

✅ **Auto-Trade:**
- `auto_paper_trade` (enabled/disabled)
- `auto_trade_trigger` (RETEST_READY or CONFIRMED)

❌ **NOT Adjustable:**
- Universe (fixed to Nifty 500 or selected list)
- Broker connection (uses cached data, not live)

---

## 📈 Metrics Calculated

### Per-Run Metrics

| Metric | Description |
|--------|-------------|
| **Total Opportunities** | All signals flagged (READY, CONFIRMED, RETEST_READY) |
| **Total Trades** | Auto-trades executed |
| **Win Rate** | % of trades that hit target (not stop) |
| **Total P&L** | Net profit/loss in ₹ |
| **Total R** | Cumulative R (risk-adjusted returns) |
| **Expectancy R** | Average R per trade |
| **Max Drawdown R** | Largest peak-to-trough decline in R |

### Comparison Metrics

When comparing multiple runs:
- Side-by-side metrics table
- Equity curve overlay
- Configuration diff viewer
- Winner/loser highlight

---

## 🎯 Key Benefits

✅ **Risk-Free Testing**
- No real money at risk
- Test radical configuration changes
- Experiment without fear

✅ **Fast Iteration**
- Full day replays in ~30 seconds
- Test 30 days in 15 minutes
- Rapid configuration optimization

✅ **Confidence Building**
- See historical proof of edge
- Validate before going live
- Understand missed opportunities

✅ **Configuration Optimization**
- A/B test different parameters
- Find optimal settings
- Data-driven decisions

✅ **Learning Tool**
- Review what you missed
- Understand why signals fail
- Improve pattern recognition

---

## 🚀 Next Steps (Phases 3-5)

### Immediate: Phase 3 - API Endpoints
1. Create router: `server/routers/simulation.py`
2. Implement CRUD endpoints
3. Background task integration for async runs
4. Test with Postman/curl

### Next: Phase 4 - Basic UI
1. Create `web/src/Simulation.jsx`
2. Form to create sim runs
3. List of runs with status
4. Basic results viewer

### Finally: Phase 5 - Advanced UI
1. Comparison dashboard
2. Metrics visualization
3. Config optimizer
4. Replay viewer

---

## 📚 Technical Notes

### Data Caching Strategy

**Once Fetched, Never Refetch:**
- Historical bars are cached permanently
- Identified by: `(symbol, date, bar_interval)`
- Reused across all sim runs
- Saves API quota and time

**Storage Estimates:**
- 500 symbols × 375 bars (1-min) = 187,500 bars
- ~100 bytes per bar = ~18 MB per day
- 30 days cached = ~540 MB (acceptable)

### Simulation Speed

**Accelerated Replay:**
- Full trading day (6h 15min) replays in ~30 seconds
- 1,000x real-time speed
- No delays between bars
- CPU-bound, not I/O-bound

### Data Accuracy

**FYERS Historical API:**
- Tick-by-tick data not available
- 1-minute bars are smallest granularity
- Actual fills may differ slightly from simulation
- Acceptable for strategy validation

**Stop/Target Logic:**
- If bar's low ≤ stop → stop hit
- If bar's high ≥ target → target hit
- Assumes instant fill at exact level
- Real slippage not modeled (yet)

---

## 🎓 Usage Tips

### Best Practices

1. **Test on Multiple Days**
   - Don't optimize for one day
   - Test last 10-30 trading days
   - Look for consistent performance

2. **Configuration Validation**
   - Start with small changes (0.16% → 0.18%)
   - Test each param independently
   - Document what works and why

3. **Overfitting Warning**
   - Don't chase perfect historical results
   - Leave room for market changes
   - Prioritize robust over optimal

4. **Review Missed Opportunities**
   - Journal shows ALL signals
   - See what you could have traded
   - Learn from missed high-score setups

### Common Workflows

**A/B Test a Single Parameter:**
```
1. Create Run A with default config
2. Create Run B with changed param
3. Compare results
4. Pick winner
5. Test on more days to confirm
```

**Find Optimal Configuration:**
```
1. Pick parameter to optimize (e.g., tolerance)
2. Test range: 0.10%, 0.14%, 0.18%, 0.22%, 0.26%
3. Run all 5 on same day
4. Plot results (R vs tolerance)
5. Pick optimal value
6. Validate on other days
```

**Confidence Building:**
```
1. Test last 30 days with your config
2. Calculate:
   - Win rate across all days
   - Average R per day
   - Worst day, best day
   - Max drawdown
3. If metrics look good → deploy to live
4. If not → iterate on config
```

---

## 🔍 Future Enhancements

### Phase 6+

**Multi-Day Simulations:**
- Test across week/month
- Track cumulative performance
- Position sizing over time

**Advanced Order Types:**
- Trailing stops
- Partial exits
- Scale-in/scale-out

**Slippage Modeling:**
- Realistic fills (not at exact price)
- Volume-based slippage
- Market impact modeling

**Transaction Costs:**
- Include brokerage fees
- GST, STT, exchange charges
- Net P&L after all costs

**SMC Strategy Support:**
- Simulate SMC signals
- Compare ORB vs SMC
- Hybrid strategies

**Configuration Optimizer:**
- Automated parameter search
- Grid search / random search
- Find globally optimal config

**Replay Viewer:**
- Watch simulation in slow motion
- See signals appear live
- Understand timing better

---

## 🎯 Success Criteria

**MVP (Phases 1-3) is complete when:**
- ✅ User can create a sim run via API
- ✅ System fetches historical data
- ✅ Simulation runs successfully
- ✅ Results stored in database
- ✅ User can retrieve journal & trades
- ✅ Metrics calculated correctly

**Full Product (Phases 1-5) is complete when:**
- ✅ User can create sim run via UI
- ✅ Monitor progress in real-time
- ✅ View journal like production
- ✅ View trades & P&L
- ✅ Compare 2+ runs side-by-side
- ✅ See metrics dashboard with charts
- ✅ Make data-driven config decisions

---

## 📊 Current Status

### ✅ Completed (Phases 1-2)
- Database schema
- Models
- Historical data fetcher
- Simulation controller

### 🚧 In Progress
- Phase 3: API endpoints (next)

### 📋 Remaining
- Phase 4: Basic UI
- Phase 5: Advanced UI

**Estimated Timeline:**
- Phase 3: 1-2 days
- Phase 4: 2-3 days
- Phase 5: 3-4 days
- **Total: 1-1.5 weeks for full implementation**

---

**This simulation system will be a game-changer for strategy validation and confidence building!** 🚀
