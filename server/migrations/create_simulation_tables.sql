-- Simulation system tables
-- Run this migration to create tables for backtesting/simulation feature

-- Simulation runs (each test with different config)
CREATE TABLE IF NOT EXISTS sim_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    config TEXT NOT NULL,              -- JSON config snapshot
    start_date TEXT NOT NULL,          -- "2024-11-15"
    start_time TEXT NOT NULL,          -- "09:15"
    end_date TEXT NOT NULL,            -- "2024-11-15" (same for single day)
    end_time TEXT NOT NULL,            -- "15:30"
    bar_interval TEXT NOT NULL,        -- "1" or "5" (minutes)
    status TEXT NOT NULL DEFAULT 'pending',  -- "pending", "fetching_data", "running", "completed", "failed"
    progress_pct INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,

    -- Results summary (populated after completion)
    total_opportunities INTEGER,
    total_trades INTEGER,
    total_pnl REAL,
    win_rate REAL,
    expectancy_r REAL,
    total_r REAL,
    max_drawdown_r REAL,

    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_sim_runs_user_status ON sim_runs(user_id, status);
CREATE INDEX IF NOT EXISTS idx_sim_runs_created ON sim_runs(created_at DESC);

-- Historical market data cache (shared across all sim runs)
CREATE TABLE IF NOT EXISTS sim_historical_bars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,                -- "2024-11-15"
    bar_interval TEXT NOT NULL,        -- "1" or "5"
    timestamp TEXT NOT NULL,           -- ISO format: "2024-11-15T09:20:00+05:30"
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sim_bars_unique ON sim_historical_bars(symbol, date, bar_interval, timestamp);
CREATE INDEX IF NOT EXISTS idx_sim_bars_lookup ON sim_historical_bars(symbol, date, bar_interval);

-- Journal entries for each sim run
CREATE TABLE IF NOT EXISTS sim_signal_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sim_run_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    sim_time TEXT NOT NULL,            -- ISO timestamp in simulation
    symbol TEXT,
    side TEXT,
    state TEXT,
    score INTEGER DEFAULT 0,
    entry TEXT,
    stop TEXT,
    target TEXT,
    net_rr TEXT,
    rvol TEXT,
    qty INTEGER,
    provisional INTEGER DEFAULT 0,
    note TEXT,
    timeline TEXT,                      -- JSON array

    FOREIGN KEY (sim_run_id) REFERENCES sim_runs(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_sim_signal_logs_run ON sim_signal_logs(sim_run_id, state);
CREATE INDEX IF NOT EXISTS idx_sim_signal_logs_symbol ON sim_signal_logs(sim_run_id, symbol);

-- Orders/trades for each sim run
CREATE TABLE IF NOT EXISTS sim_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sim_run_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty INTEGER NOT NULL,
    entry REAL NOT NULL,
    stop REAL NOT NULL,
    target REAL,
    status TEXT NOT NULL DEFAULT 'open',  -- "open", "closed"
    source TEXT DEFAULT 'auto',            -- "auto" or "manual"
    created_at TEXT NOT NULL,              -- ISO timestamp (sim time)
    closed_at TEXT,                        -- ISO timestamp (sim time)
    close_reason TEXT,                     -- "target", "stop", "eod"
    close_price REAL,
    pnl REAL,
    result_r REAL,

    FOREIGN KEY (sim_run_id) REFERENCES sim_runs(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_sim_orders_run ON sim_orders(sim_run_id, status);
CREATE INDEX IF NOT EXISTS idx_sim_orders_symbol ON sim_orders(sim_run_id, symbol);

-- Replay events for visualization (optional, for replay viewer)
CREATE TABLE IF NOT EXISTS sim_replay_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sim_run_id INTEGER NOT NULL,
    sim_time TEXT NOT NULL,
    event_type TEXT NOT NULL,          -- "signal", "order_created", "order_closed", "state_change"
    symbol TEXT,
    data TEXT,                          -- JSON payload

    FOREIGN KEY (sim_run_id) REFERENCES sim_runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sim_replay_events ON sim_replay_events(sim_run_id, sim_time);
