"""
Simulation/Backtesting API endpoints.

Provides CRUD operations for simulation runs and results viewing.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from radar.selecting import load_universe
from radar.utils import ROOT, now_ist
from ..auth import require_user
from ..db import get_db
from ..models import User, SimRun, SimSignalLog, SimOrder, SimHistoricalBar, BrokerConnection
from ..sim_controller import SimulationController
from ..sim_data_fetcher import HistoricalDataFetcher, estimate_data_size

router = APIRouter()
logger = logging.getLogger(__name__)


# ============================================================================
# Request/Response Models
# ============================================================================

class CreateSimRunRequest(BaseModel):
    name: str
    description: str | None = None
    start_date: str  # "2024-11-15"
    start_time: str = "09:15"
    end_date: str  # Same as start_date for single day
    end_time: str = "15:30"
    bar_interval: str = "1"  # "1" or "5"
    config: dict  # Strategy configuration


class SimRunResponse(BaseModel):
    id: int
    name: str
    description: str | None
    start_date: str
    start_time: str
    end_date: str
    end_time: str
    bar_interval: str
    status: str
    progress_pct: int
    error_message: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None
    # Results
    total_opportunities: int | None
    total_trades: int | None
    total_pnl: float | None
    win_rate: float | None
    expectancy_r: float | None
    total_r: float | None
    max_drawdown_r: float | None

    class Config:
        from_attributes = True


# ============================================================================
# Endpoints
# ============================================================================

@router.post('/api/sim/runs', response_model=SimRunResponse)
async def create_sim_run(
    request: CreateSimRunRequest,
    user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    """
    Create a new simulation run.

    The run is persisted as 'pending' and executed by the dedicated sim-worker pod (server/sim_worker),
    which claims pending runs from the DB. It deliberately does NOT run here as a FastAPI BackgroundTask:
    that tied execution to the web pod (multi-replica, redeployed often), so a restart orphaned it. The
    worker is isolated from web and the live-feed scanner. See docs / [[fyers-pilot-browser-session-deps]].
    """
    try:
        # Validate dates
        start_date = datetime.fromisoformat(request.start_date).date()
        end_date = datetime.fromisoformat(request.end_date).date()

        if end_date != start_date:
            raise HTTPException(
                status_code=400,
                detail="Multi-day simulations not yet supported. start_date must equal end_date."
            )

        # Validate bar interval
        if request.bar_interval not in ["1", "5"]:
            raise HTTPException(
                status_code=400,
                detail="bar_interval must be '1' or '5'"
            )

        # Create sim run
        sim_run = SimRun(
            user_id=user.id,
            name=request.name,
            description=request.description,
            config=json.dumps(request.config),
            start_date=request.start_date,
            start_time=request.start_time,
            end_date=request.end_date,
            end_time=request.end_time,
            bar_interval=request.bar_interval,
            status='pending',
            progress_pct=0
        )

        db.add(sim_run)
        db.commit()
        db.refresh(sim_run)

        # Left 'pending'; the sim-worker pod claims and runs it. No in-process execution here.
        logger.info(f"Queued sim run {sim_run.id} for user {user.email} (sim-worker will execute)")

        return _sim_run_to_response(sim_run)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create sim run: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/api/sim/runs', response_model=List[SimRunResponse])
def list_sim_runs(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    limit: int = 50,
    offset: int = 0
):
    """List user's simulation runs, most recent first."""
    runs = db.query(SimRun).filter_by(user_id=user.id)\
        .order_by(SimRun.created_at.desc())\
        .limit(limit)\
        .offset(offset)\
        .all()

    return [_sim_run_to_response(run) for run in runs]


@router.get('/api/sim/runs/{run_id}', response_model=SimRunResponse)
def get_sim_run(
    run_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Get details of a specific simulation run."""
    run = db.query(SimRun).filter_by(id=run_id, user_id=user.id).first()

    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")

    return _sim_run_to_response(run)


@router.delete('/api/sim/runs/{run_id}')
def delete_sim_run(
    run_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Delete a simulation run and all its data."""
    run = db.query(SimRun).filter_by(id=run_id, user_id=user.id).first()

    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")

    # Cascade delete will remove related sim_signal_logs, sim_orders, sim_replay_events
    db.delete(run)
    db.commit()

    logger.info(f"Deleted sim run {run_id} for user {user.email}")

    return {"success": True, "message": "Simulation run deleted"}


@router.get('/api/sim/runs/{run_id}/journal')
def get_sim_journal(
    run_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    state: str | None = None  # Filter by state (e.g., "RETEST_READY")
):
    """Get journal entries (opportunities) for a simulation run."""
    run = db.query(SimRun).filter_by(id=run_id, user_id=user.id).first()

    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")

    # Query journal entries
    query = db.query(SimSignalLog).filter_by(sim_run_id=run_id)

    if state:
        query = query.filter_by(state=state)

    logs = query.order_by(SimSignalLog.score.desc()).all()

    # Format response
    items = []
    for log in logs:
        items.append({
            'id': log.id,
            'sim_time': log.sim_time,
            'symbol': log.symbol,
            'side': log.side,
            'state': log.state,
            'score': log.score,
            'entry': log.entry,
            'stop': log.stop,
            'target': log.target,
            'net_rr': log.net_rr,
            'rvol': log.rvol,
            'qty': log.qty,
            'provisional': bool(log.provisional),
            'note': log.note,
            'timeline': json.loads(log.timeline) if log.timeline else []
        })

    return {
        'sim_run_id': run_id,
        'total': len(items),
        'items': items
    }


@router.get('/api/sim/runs/{run_id}/trades')
def get_sim_trades(
    run_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    status: str | None = None  # Filter by status ("open" or "closed")
):
    """Get trades (orders) for a simulation run."""
    run = db.query(SimRun).filter_by(id=run_id, user_id=user.id).first()

    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")

    # Query orders
    query = db.query(SimOrder).filter_by(sim_run_id=run_id)

    if status:
        query = query.filter_by(status=status)

    orders = query.order_by(SimOrder.created_at).all()

    # Format response
    items = []
    for order in orders:
        items.append({
            'id': order.id,
            'symbol': order.symbol,
            'side': order.side,
            'qty': order.qty,
            'entry': order.entry,
            'stop': order.stop,
            'target': order.target,
            'status': order.status,
            'created_at': order.created_at,
            'closed_at': order.closed_at,
            'close_reason': order.close_reason,
            'close_price': order.close_price,
            'pnl': order.pnl,
            'result_r': order.result_r
        })

    return {
        'sim_run_id': run_id,
        'total': len(items),
        'items': items
    }


@router.get('/api/sim/compare')
def compare_sim_runs(
    run_ids: str,  # Comma-separated: "1,2,3"
    user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    """Compare multiple simulation runs side-by-side."""
    try:
        ids = [int(id.strip()) for id in run_ids.split(',')]
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run_ids format")

    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 runs to compare")

    if len(ids) > 5:
        raise HTTPException(status_code=400, detail="Cannot compare more than 5 runs")

    # Fetch all runs
    runs = db.query(SimRun).filter(
        SimRun.id.in_(ids),
        SimRun.user_id == user.id
    ).all()

    if len(runs) != len(ids):
        raise HTTPException(status_code=404, detail="One or more simulation runs not found")

    # Build comparison data
    comparison = []
    for run in runs:
        comparison.append({
            'id': run.id,
            'name': run.name,
            'date': run.start_date,
            'bar_interval': run.bar_interval,
            'status': run.status,
            'metrics': {
                'total_opportunities': run.total_opportunities,
                'total_trades': run.total_trades,
                'win_rate': run.win_rate,
                'total_pnl': run.total_pnl,
                'total_r': run.total_r,
                'expectancy_r': run.expectancy_r,
                'max_drawdown_r': run.max_drawdown_r
            },
            # Include config diff
            'config': json.loads(run.config) if run.config else {}
        })

    return {
        'runs': comparison,
        'count': len(comparison)
    }


@router.get('/api/sim/data-size-estimate')
def estimate_data_size_endpoint(
    date: str,
    bar_interval: str = "1",
    user: User = Depends(require_user)
):
    """Estimate storage size for historical data fetch."""
    # Get universe size (default to Nifty 500)
    num_symbols = 500  # TODO: Get from actual universe

    estimate = estimate_data_size(num_symbols, bar_interval)

    return {
        'date': date,
        'bar_interval': bar_interval,
        'num_symbols': num_symbols,
        'estimated_size': estimate
    }


# ============================================================================
# Simulation execution (invoked by the sim-worker pod — see server/sim_worker.py)
# ============================================================================

def execute_sim_run(sim_run_id: int, user_id: int):
    """Fetch data + replay one simulation to completion. Called by the sim-worker after it claims a
    'pending' run (never as a web BackgroundTask — that orphaned runs on a web-pod restart). Updates the
    SimRun row's status/heartbeat/results; opens and closes its own DB session."""
    from ..db import SessionLocal

    db = SessionLocal()
    try:
        sim_run = db.query(SimRun).get(sim_run_id)
        if not sim_run:
            logger.error(f"Sim run {sim_run_id} not found in background task")
            return

        logger.info(f"Starting background simulation {sim_run_id}")

        # Liveness heartbeat: a long fetch/replay keeps stamping this so the orphaned-run reconciler
        # (sim_controller.reconcile_orphaned_runs) can tell a live run from one whose pod died. Commit
        # is throttled — the fetcher already commits per symbol, so most calls are a cheap field set.
        _beat_n = [0]
        def _beat():
            sim_run.heartbeat_at = now_ist()
            _beat_n[0] += 1
            if _beat_n[0] % 10 == 0:
                db.commit()
        sim_run.heartbeat_at = now_ist()
        db.commit()

        # Get user's broker connection for data fetching
        user = db.query(User).get(user_id)
        broker_conn = db.query(BrokerConnection).filter_by(
            user_id=user_id,
            broker='fyers'
        ).first()

        if not broker_conn or not broker_conn.token_enc:
            sim_run.status = 'failed'
            sim_run.error_message = "No FYERS broker connection found. Connect your broker first."
            db.commit()
            return

        # Mirror production: rank the full universe on prior-session DAILY data, pick the ~100 symbols
        # the live scanner would have traded that day, then fetch INTRADAY only for those (the sim day
        # for the replay + prior sessions for RVOL baselines). This keeps the sim faithful to prod and
        # bounds the FYERS cost (vs. fetching intraday for all ~500 symbols).
        fetcher = HistoricalDataFetcher(db, broker_conn)
        interval = sim_run.bar_interval

        universe_path = ROOT / 'data' / 'nifty500.csv'
        if not universe_path.exists():
            sim_run.status = 'failed'
            sim_run.error_message = f"Universe file not found: {universe_path}"
            db.commit()
            return
        universe = load_universe(universe_path)  # [(symbol, industry), ...]
        logger.info(f"[sim {sim_run_id}] universe: {len(universe)} symbols")

        # Step 1: daily history for selection (cached across runs)
        sim_run.status = 'fetching_data'
        sim_run.progress_pct = 0
        sim_run.heartbeat_at = now_ist()
        db.commit()
        fetcher.fetch_daily_history([s for s, _ in universe], sim_run.start_date, on_heartbeat=_beat)

        # Step 2: select the ~100-symbol watchlist for the date (production selection logic). Keep the
        # full Instrument PROFILES (resistance/support/ATR/turnover), not just the symbols — the ORB
        # engine derives targets from Instrument.resistance/support and widens stops by daily_atr_pct, so
        # bare Instruments make every retest fail at RISK_FAIL ("no known target") and no entry is ever
        # produced.
        profiles = _select_watchlist_for_date(fetcher, universe, sim_run.start_date)
        symbols = [p.symbol for p in profiles]
        logger.info(f"[sim {sim_run_id}] selected {len(symbols)} symbols for {sim_run.start_date}")
        if not symbols:
            sim_run.status = 'failed'
            sim_run.error_message = ("Could not select a watchlist for this date — insufficient daily "
                                     "history. Try a more recent trading day.")
            db.commit()
            return

        # Step 3: intraday for the selected symbols — sim day (replay) + prior sessions (baselines)
        sim_run.progress_pct = 40
        sim_run.heartbeat_at = now_ist()
        db.commit()
        have = fetcher.fetch_intraday_window(symbols, sim_run.start_date, interval, on_heartbeat=_beat)
        if have == 0:
            sim_run.status = 'failed'
            sim_run.error_message = (f"No intraday data for {sim_run.start_date}. It may be a market "
                                     "holiday or outside FYERS' intraday history range.")
            db.commit()
            return

        db.expire_all()
        db.refresh(sim_run)

        # Step 4: replay the sim day through the real engine, restricted to the selected watchlist,
        # using the real per-symbol profiles so the engine can compute targets/stops.
        controller = SimulationController(db, sim_run, symbols=symbols, profiles=profiles)
        controller.run()

        logger.info(f"Simulation {sim_run_id} completed successfully")

    except Exception as e:
        logger.error(f"Simulation {sim_run_id} failed: {e}", exc_info=True)
        sim_run.status = 'failed'
        sim_run.error_message = str(e)
        db.commit()
    finally:
        db.close()


# ============================================================================
# Helper Functions
# ============================================================================

def _select_watchlist_for_date(fetcher, universe, sim_date: str) -> list:
    """Replay the production morning selection for a PAST date, using cached DAILY bars.

    Builds a liquidity/ATR profile per symbol from the prior sessions' daily candles
    (radar.selecting.compute_daily_profile) and picks the top ~100 (choose_top100 — same price /
    turnover / ATR / industry-diversification filters the live scanner uses). On a thin date where
    fewer than the cap pass, falls back to taking whatever passed rather than hard-failing.

    Returns the chosen Instrument PROFILES (not just symbols): each carries resistance/support,
    daily_atr_pct, previous_close and median_turnover_cr, which the ORB engine needs to compute
    retest targets and size stops. `[p.symbol for p in ...]` recovers the plain symbol list.
    """
    from datetime import timedelta
    from radar.selecting import compute_daily_profile, choose_top100, SelectionError
    from radar.models import Candle
    from radar.utils import load_config

    cutoff = datetime.fromisoformat(sim_date).date()
    lookback_start = (cutoff - timedelta(days=90)).isoformat()
    profiles = []
    for symbol, industry in universe:
        rows = fetcher.get_bars_in_range(symbol, 'D', lookback_start, cutoff.isoformat())
        if not rows:
            continue
        candles = [Candle(at=datetime.fromisoformat(b.timestamp), open=b.open, high=b.high,
                          low=b.low, close=b.close, volume=b.volume) for b in rows]
        p = compute_daily_profile(symbol, industry, candles, cutoff)
        if p:
            profiles.append(p)

    config = load_config()
    try:
        chosen = choose_top100(profiles, config, morning_pins=[])
    except SelectionError:
        chosen = _relaxed_pick(profiles, config)
    return chosen


def _relaxed_pick(profiles, config):
    """Same filters/diversification as choose_top100 but without the hard 'need the full cap' error —
    used when a historical date has thinner data than a live pre-open would."""
    from collections import Counter
    cap = min(config.get('max_symbols', 100), 100)
    passed = [p for p in profiles if
              p.previous_close >= config['min_price_inr'] and
              p.median_turnover_cr >= config['min_median_daily_turnover_cr'] and
              config['min_daily_atr_pct'] <= p.daily_atr_pct <= config['max_daily_atr_pct']]
    passed.sort(key=lambda x: -x.selection_score)
    chosen, industry_count = [], Counter()
    for p in passed:
        if industry_count[p.industry] >= config['max_industry_members']:
            continue
        chosen.append(p)
        industry_count[p.industry] += 1
        if len(chosen) == cap:
            break
    return chosen


def _sim_run_to_response(run: SimRun) -> SimRunResponse:
    """Convert SimRun model to response object."""
    return SimRunResponse(
        id=run.id,
        name=run.name,
        description=run.description,
        start_date=run.start_date,
        start_time=run.start_time,
        end_date=run.end_date,
        end_time=run.end_time,
        bar_interval=run.bar_interval,
        status=run.status,
        progress_pct=run.progress_pct or 0,
        error_message=run.error_message,
        created_at=run.created_at.isoformat() if run.created_at else None,
        started_at=run.started_at.isoformat() if run.started_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        total_opportunities=run.total_opportunities,
        total_trades=run.total_trades,
        total_pnl=run.total_pnl,
        win_rate=run.win_rate,
        expectancy_r=run.expectancy_r,
        total_r=run.total_r,
        max_drawdown_r=run.max_drawdown_r
    )
