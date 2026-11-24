"""
Simulation/Backtesting API endpoints.

Provides CRUD operations for simulation runs and results viewing.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from radar.selecting import load_universe
from radar.utils import ROOT
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
    background_tasks: BackgroundTasks,
    user: User = Depends(require_user),
    db: Session = Depends(get_db)
):
    """
    Create a new simulation run.

    The simulation will be queued for execution in the background.
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

        # Queue for execution in background
        background_tasks.add_task(
            _run_simulation_background,
            sim_run.id,
            user.id
        )

        logger.info(f"Created sim run {sim_run.id} for user {user.email}")

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
# Background Tasks
# ============================================================================

def _run_simulation_background(sim_run_id: int, user_id: int):
    """
    Background task to run a simulation.

    This runs asynchronously after the API returns the initial response.
    """
    from ..db import SessionLocal

    db = SessionLocal()
    try:
        sim_run = db.query(SimRun).get(sim_run_id)
        if not sim_run:
            logger.error(f"Sim run {sim_run_id} not found in background task")
            return

        logger.info(f"Starting background simulation {sim_run_id}")

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

        # Step 1: Fetch historical data
        fetcher = HistoricalDataFetcher(db, broker_conn)

        # Get universe symbols
        # TODO: Make this configurable per sim run
        universe_path = ROOT / 'data' / 'nifty500.csv'
        logger.info(f"Loading universe from: {universe_path}")

        if not universe_path.exists():
            sim_run.status = 'failed'
            sim_run.error_message = f"Universe file not found: {universe_path}"
            db.commit()
            return

        universe_data = load_universe(universe_path)
        symbols = [symbol for symbol, industry in universe_data]
        logger.info(f"Loaded {len(symbols)} symbols from universe")

        fetcher.fetch_day_data(sim_run, symbols)

        # Refresh session to see newly committed data
        db.expire_all()
        db.refresh(sim_run)

        # Step 2: Run simulation
        controller = SimulationController(db, sim_run)
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
