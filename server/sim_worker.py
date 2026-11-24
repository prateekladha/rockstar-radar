"""Dedicated simulation worker — runs backtests/sims off the web pod.

Sims used to execute as in-process FastAPI BackgroundTasks in the web pod, which is multi-replica and
redeployed often, so a restart orphaned a run (stuck non-terminal forever). They are also heavy and
bursty (FYERS REST on the user's quota + bar replay), which we don't want co-located with either the
web request path or the live-feed scanner pod.

This worker is its own Deployment (env RADAR_SIM_WORKER=1, singleton). It CLAIMS 'pending' runs from
the DB and executes them one at a time. Claiming is atomic (UPDATE ... WHERE status='pending'), so it is
safe even if more than one worker ever runs, and it composes with the orphaned-run reconciler
(sim_controller.reconcile_orphaned_runs): a claimed run keeps a fresh heartbeat; if this pod dies
mid-run the reconciler fails it after the heartbeat goes stale, and a 'pending' run simply waits for the
worker to come back (the reconciler's pending grace is deliberately long — see that module)."""
from __future__ import annotations

import asyncio
import os

from radar.utils import now_ist

from .db import SessionLocal
from .models import SimRun

_POLL_SECONDS = int(os.environ.get('RADAR_SIM_WORKER_POLL_SEC', '5'))


def claim_next(db) -> tuple[int, int] | None:
    """Atomically claim the oldest queued run. Returns (sim_run_id, user_id) if we won it, else None.

    Flips 'pending' -> 'fetching_data' with a fresh heartbeat in one guarded UPDATE, so a concurrent
    claimer (or the reconciler) can't double-process it, and the run never looks orphaned mid-claim."""
    run = (db.query(SimRun).filter(SimRun.status == 'pending')
           .order_by(SimRun.created_at.asc()).first())
    if run is None:
        return None
    now = now_ist()
    won = (db.query(SimRun)
           .filter(SimRun.id == run.id, SimRun.status == 'pending')
           .update({SimRun.status: 'fetching_data', SimRun.started_at: now,
                    SimRun.heartbeat_at: now}, synchronize_session=False))
    db.commit()
    if won == 1:
        return run.id, run.user_id
    return None   # lost the race; try again next poll


def _claim_and_run_one() -> bool:
    """Claim one pending run and execute it to completion. Returns True if a run was processed."""
    db = SessionLocal()
    try:
        claim = claim_next(db)
    finally:
        db.close()
    if not claim:
        return False
    sim_run_id, user_id = claim
    # Imported lazily: keeps module import light and avoids pulling the FastAPI router at load time.
    from .routers.simulation import execute_sim_run
    print(f'[sim-worker] executing sim run {sim_run_id} (user {user_id})')
    try:
        execute_sim_run(sim_run_id, user_id)   # opens its own DB session; sets completed/failed itself
    except Exception as e:
        # execute_sim_run already marks the row failed on its own exceptions; this is a last-resort log.
        print(f'[sim-worker] sim run {sim_run_id} crashed: {type(e).__name__}: {e}')
    return True


async def run_sim_worker() -> None:
    """Poll loop: drain the pending queue, then idle a few seconds. Started from the app lifespan when
    RADAR_SIM_WORKER=1 (the sim-worker Deployment only)."""
    print(f'[sim-worker] on — polling every {_POLL_SECONDS}s for pending simulation runs')
    while True:
        try:
            ran = await asyncio.to_thread(_claim_and_run_one)
            if not ran:
                await asyncio.sleep(_POLL_SECONDS)   # queue empty — wait before polling again
        except Exception as e:   # the loop must survive anything
            print(f'[sim-worker] loop error: {type(e).__name__}: {e}')
            await asyncio.sleep(_POLL_SECONDS)
