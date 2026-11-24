"""
Simulation controller - orchestrates the replay of historical data through the ORB engine.

This is the core of the backtesting system. It:
1. Loads historical bars
2. Replays them chronologically through the REAL ORB engine
3. Records opportunities (journal)
4. Executes simulated auto-trades
5. Processes exits (stops/targets)
6. Calculates P&L and metrics
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, date, timezone
from typing import List, Dict, Any

from sqlalchemy.orm import Session

from radar.engine import RadarEngine
from radar.models import Candle, Instrument
from radar.utils import IST, now_ist
from .models import SimRun, SimHistoricalBar, SimSignalLog, SimOrder
from .sim_data_fetcher import HistoricalDataFetcher

logger = logging.getLogger(__name__)


def _fmt_num(x, nd: int = 2):
    """Round a numeric to a SHORT string for SimSignalLog's String(16) price columns.

    The engine hands back unrounded floats (e.g. a stop of 213.15293999999997 = 18 chars). SQLite
    (dev) ignores the column width, but Oracle ADB (prod) enforces VARCHAR(16) and rejects the row with
    ORA-12899 — which aborts the commit, breaks the Session, and freezes the whole run at 0%. Rounding
    to 2dp keeps every realistic NSE price/R:R/RVOL well inside 16 chars. None stays None.
    """
    if x is None:
        return None
    try:
        return str(round(float(x), nd))
    except (TypeError, ValueError):
        return None


class SimulationController:
    """Orchestrates simulation replay."""

    def __init__(self, db: Session, sim_run: SimRun, symbols: List[str] | None = None,
                 profiles: List[Instrument] | None = None):
        from radar.utils import load_config
        self.db = db
        self.sim_run = sim_run
        # The RadarEngine expects the FULL product config (new_signals_stop, near_boundary_pct,
        # orb_stop_mode, rvol_thresholds, …), exactly as production builds it. sim_run.config is only
        # the user's sim-specific overrides, so layer it ON TOP of the full config.json defaults —
        # otherwise the engine KeyErrors on the first key the sim subset omits.
        sim_overrides = json.loads(sim_run.config) if sim_run.config else {}
        self.config = {**load_config(), **(sim_overrides or {})}
        self.current_time = None
        self.session_date = datetime.fromisoformat(sim_run.start_date).date()
        # Width of a replayed bar. The engine only acts on a candle once the wall clock has passed the
        # bar's CLOSE (engine.py guards against half-formed live bars: `candle.at + bar_delta > wall`).
        # In replay we are the wall clock, so a bar opening at T is "observed" at its close, T + width —
        # otherwise every bar looks unfinished, the opening range never forms and the whole day is stuck
        # in WAIT_OR (0 opportunities/trades). bar_interval is '1' or '5' minutes.
        try:
            self._bar_delta = timedelta(minutes=int(sim_run.bar_interval or 5))
        except (TypeError, ValueError):
            self._bar_delta = timedelta(minutes=5)
        # The watchlist the live scanner would have traded that day (selected upstream). When set, the
        # replay and baselines are restricted to these symbols — so stale sim-day bars cached for other
        # symbols by an earlier run don't leak the full universe back into the sim.
        self.selected_symbols = list(symbols) if symbols else None
        # Real per-symbol daily profiles (resistance/support/daily_atr_pct/turnover) from the selection
        # step. The ORB engine derives retest TARGETS from Instrument.resistance/support and widens the
        # stop by daily_atr_pct; without them every retest dies at RISK_FAIL ("no known target"), nothing
        # reaches RETEST_READY, and the journal only ever shows CONFIRMED (score 65) with no entry/stop/
        # target. When profiles aren't supplied (e.g. a direct/legacy call) we fall back to bare
        # Instruments, which still replay but produce no entry tickets.
        self._profiles_by_symbol = {p.symbol: p for p in (profiles or [])}
        if profiles and not self.selected_symbols:
            self.selected_symbols = [p.symbol for p in profiles]

        # Which strategy this run replays: 'ORB' (RadarEngine) or 'SMC' (SMCEngine). Stored in the
        # config JSON (no DB column), defaults to ORB for older runs.
        self.strategy = str(self.config.get('strategy') or 'ORB').upper()
        if self.strategy not in ('ORB', 'SMC'):
            self.strategy = 'ORB'

        # Will be initialized during replay (RadarEngine for ORB, SMCEngine for SMC)
        self.engine = None
        self.open_orders: Dict[str, SimOrder] = {}  # symbol -> currently OPEN order
        # Symbols already auto-traded in this run. The engine keeps reporting a symbol as RETEST_READY
        # with FROZEN entry/stop/target after the breakout; once a position closes it leaves open_orders,
        # so without this guard the next bar re-enters the identical setup and it re-closes at the same
        # stop/target — spawning one duplicate trade per bar (prod blocks this via held + trades-per-day).
        # One entry per symbol per run: a replayed frozen signal never represents a genuinely new setup.
        self.traded_symbols: set[str] = set()
        self.symbols: List[str] = []

    def run(self) -> None:
        """Main entry point - run the complete simulation."""
        try:
            logger.info(f"Starting simulation run {self.sim_run.id}: {self.sim_run.name}")

            # Update status
            self.sim_run.status = 'running'
            self.sim_run.started_at = now_ist()
            self.sim_run.progress_pct = 0
            self.sim_run.heartbeat_at = now_ist()   # liveness for the orphaned-run reconciler
            self.db.commit()

            # Load historical data
            bars_by_symbol = self._load_historical_data()

            if not bars_by_symbol:
                raise ValueError("No historical data available for this simulation")

            # Initialize engine with sim config
            self._initialize_engine(list(bars_by_symbol.keys()))

            # Replay bar-by-bar
            self._replay_bars(bars_by_symbol)

            # Finalize
            self._finalize_simulation()

            logger.info(f"Simulation {self.sim_run.id} completed successfully")

        except Exception as e:
            logger.error(f"Simulation {self.sim_run.id} failed: {e}", exc_info=True)
            self.sim_run.status = 'failed'
            self.sim_run.error_message = str(e)
            self.db.commit()
            raise

    def _load_historical_data(self) -> Dict[str, List[SimHistoricalBar]]:
        """Load cached historical bars for this simulation."""
        logger.info(f"Loading historical data for date={self.sim_run.start_date}, interval={self.sim_run.bar_interval}...")

        # Check total bars available
        total_bars = self.db.query(SimHistoricalBar).filter(
            SimHistoricalBar.date == self.sim_run.start_date,
            SimHistoricalBar.bar_interval == self.sim_run.bar_interval
        ).count()
        logger.info(f"Found {total_bars} total bars in database")

        q = self.db.query(SimHistoricalBar).filter(
            SimHistoricalBar.date == self.sim_run.start_date,
            SimHistoricalBar.bar_interval == self.sim_run.bar_interval
        )
        if self.selected_symbols:
            # Replay only the selected watchlist (the ~100 the live scanner would have traded).
            q = q.filter(SimHistoricalBar.symbol.in_(self.selected_symbols))
        bars = q.order_by(SimHistoricalBar.timestamp).all()

        # Group by symbol
        bars_by_symbol = defaultdict(list)
        for bar in bars:
            bars_by_symbol[bar.symbol].append(bar)

        logger.info(f"Loaded data for {len(bars_by_symbol)} symbols ({total_bars} total bars)")
        return dict(bars_by_symbol)

    def _initialize_engine(self, symbols: List[str]):
        """Initialize the REAL engine for this run's strategy with the simulation config."""
        self.symbols = symbols
        if self.strategy == 'SMC':
            self._initialize_smc_engine(symbols)
            return
        logger.info(f"Initializing ORB engine with {len(symbols)} symbols...")

        # Create Instrument objects
        # In production, this comes from universe.py with real median turnover data
        # For simulation, we'll use a simplified version
        instruments = []
        for symbol in symbols:
            # Prefer the real selection profile (resistance/support/ATR/turnover) so the ORB engine can
            # compute retest targets and size stops. Fall back to a bare Instrument only when a profile
            # wasn't supplied — that still replays but yields no entry tickets.
            prof = self._profiles_by_symbol.get(symbol)
            if prof is not None:
                instruments.append(prof)
            else:
                # Instrument (radar/models.py) has no 'name' field — its identity is `symbol`; the
                # optional classifier is `industry`. median_turnover_cr is a placeholder for the sim.
                instruments.append(Instrument(symbol=symbol, median_turnover_cr=1.0))

        # Initialize RadarEngine in SIMULATION mode
        self.engine = RadarEngine(
            instruments=instruments,
            config=self.config,
            session=self.session_date,
            mode='SIMULATION',
            on_signal=None  # No real-time signaling needed
        )

        # Calculate and set baselines for RVOL
        # We need historical data from before the simulation date
        self._calculate_baselines()

        logger.info("ORB engine initialized successfully")

    def _initialize_smc_engine(self, symbols: List[str]):
        """Initialize the SMC engine and warm it up with prior-session intraday candles.

        SMC swing detection needs >=101 candles (size=50 pivots) — far more than one day (75 5m bars) —
        so every cached intraday bar BEFORE the sim day is preloaded as historical context. The sim-day
        bars are then replayed one at a time through process_candle/process_tick during the replay loop.
        """
        from radar.smc_engine import SMCEngine
        logger.info(f"Initializing SMC engine with {len(symbols)} symbols...")
        instruments = [self._profiles_by_symbol.get(s) or Instrument(symbol=s, median_turnover_cr=1.0)
                       for s in symbols]
        self.engine = SMCEngine(instruments=instruments, config=self.config)
        iv = self.sim_run.bar_interval
        warmed = 0
        for symbol in symbols:
            prior = self.db.query(SimHistoricalBar).filter(
                SimHistoricalBar.symbol == symbol,
                SimHistoricalBar.bar_interval == iv,
                SimHistoricalBar.date < self.sim_run.start_date
            ).order_by(SimHistoricalBar.timestamp).all()
            if not prior:
                continue
            candles = [Candle(at=datetime.fromisoformat(b.timestamp), open=b.open, high=b.high,
                              low=b.low, close=b.close, volume=b.volume) for b in prior]
            self.engine.load_historical_candles(symbol, candles)
            warmed += 1
        logger.info(f"SMC engine warmed up with prior-session candles for {warmed}/{len(symbols)} symbols")

    def _replay_bars(self, bars_by_symbol: Dict[str, List[SimHistoricalBar]]):
        """
        Replay bars chronologically through the engine.

        Strategy:
        1. Create a timeline of all bars across all symbols
        2. Process bars in chronological order
        3. At each timestamp:
           - Feed bars to engine
           - Get engine snapshot
           - Record opportunities
           - Execute auto-trades
           - Process exits
        """
        logger.info("Starting bar replay...")

        # Create chronological timeline of all bars
        all_bars_timeline = []
        for symbol, bars in bars_by_symbol.items():
            for bar in bars:
                all_bars_timeline.append((bar.timestamp, symbol, bar))

        # Sort by timestamp
        all_bars_timeline.sort(key=lambda x: x[0])

        if not all_bars_timeline:
            raise ValueError("No bars to replay")

        # Group bars by timestamp (multiple symbols at same time)
        bars_by_time = defaultdict(list)
        for timestamp, symbol, bar in all_bars_timeline:
            bars_by_time[timestamp].append((symbol, bar))

        timestamps = sorted(bars_by_time.keys())
        total_timestamps = len(timestamps)

        logger.info(f"Replaying {total_timestamps} timestamps...")

        for idx, timestamp in enumerate(timestamps):
            self.current_time = datetime.fromisoformat(timestamp)
            bars_at_time = bars_by_time[timestamp]

            # Process this timestamp
            self._process_timestamp(bars_at_time)

            # Update progress
            if idx % 10 == 0:  # Update every 10 timestamps
                progress = int((idx / total_timestamps) * 100)
                self.sim_run.progress_pct = progress
                self.sim_run.heartbeat_at = now_ist()   # liveness for the orphaned-run reconciler
                self.db.commit()

        self.sim_run.progress_pct = 100
        self.db.commit()

    def _calculate_baselines(self):
        """Build RVOL baselines from the PRIOR sessions' intraday bars, using the SAME product-wide
        builder as the live engine (radar.rvol.build_baseline). This yields the rich schema
        ({'v', 'sessions', 'bar': {slot: median}, 'cum': {slot: mean_cumulative}}) that rvol_runtime
        expects, so cumulative RVOL (the product default) is computed correctly — not the legacy flat
        per-slot table reused for both modes. Requires the prior-session intraday history that
        HistoricalDataFetcher.fetch_intraday_window caches alongside the sim day.
        """
        from radar.rvol import build_baseline, RvolConfig

        logger.info("Calculating RVOL baselines (radar.rvol.build_baseline)...")
        cfg = RvolConfig.from_config(self.config)
        cutoff_date = self.session_date
        lookback_start = cutoff_date - timedelta(days=60)
        built = 0
        for symbol in self.symbols:
            hist_bars_data = self.db.query(SimHistoricalBar).filter(
                SimHistoricalBar.symbol == symbol,
                SimHistoricalBar.bar_interval == self.sim_run.bar_interval,
                SimHistoricalBar.date >= lookback_start.isoformat(),
                SimHistoricalBar.date < cutoff_date.isoformat()
            ).order_by(SimHistoricalBar.timestamp).all()
            if not hist_bars_data:
                continue
            history = [Candle(at=datetime.fromisoformat(b.timestamp), open=b.open, high=b.high,
                              low=b.low, close=b.close, volume=b.volume) for b in hist_bars_data]
            baseline = build_baseline(history, cutoff_date, length=cfg.length)
            if baseline.get('bar') or baseline.get('cum'):
                self.engine.set_baseline(symbol, baseline)
                built += 1

        logger.info(f"RVOL baselines built for {built}/{len(self.symbols)} symbols "
                    f"(mode={cfg.mode}, length={cfg.length})")

    def _process_timestamp(self, bars_at_time: List[tuple]):
        """
        Process all bars at a specific timestamp using the REAL engine for this run's strategy.

        Args:
            bars_at_time: List of (symbol, SimHistoricalBar) tuples
        """
        if self.strategy == 'SMC':
            self._process_timestamp_smc(bars_at_time)
            return
        # 1. Feed bars to engine (ingest_closed_bar)
        for symbol, bar_data in bars_at_time:
            # Convert SimHistoricalBar to Candle
            candle = Candle(
                at=datetime.fromisoformat(bar_data.timestamp),
                open=bar_data.open,
                high=bar_data.high,
                low=bar_data.low,
                close=bar_data.close,
                volume=bar_data.volume
            )

            # Feed to engine (non-provisional, authoritative historical data). observed_at is the bar's
            # CLOSE (open + width), the simulated moment the bar is fully known — see _bar_delta above.
            self.engine.ingest_closed_bar(
                symbol=symbol,
                candle=candle,
                observed_at=self.current_time + self._bar_delta,
                provisional=False
            )

        # 2. Get engine snapshot (as of the bar close, consistent with how the bars were ingested)
        state = self.engine.snapshot(reference_time=self.current_time + self._bar_delta)

        # 3. Record opportunities (journal)
        self._record_opportunities(state)

        # 4. Execute auto-trades
        self._execute_auto_trades(state)

        # 5. Process exits (stops/targets)
        self._process_exits(bars_at_time)

    # ---- SMC strategy path ----------------------------------------------------------------------

    def _process_timestamp_smc(self, bars_at_time: List[tuple]):
        """Feed bars to the SMC engine, then journal + auto-trade its opportunities, then run exits."""
        from radar.models import Tick
        bar_close = self.current_time + self._bar_delta
        for symbol, bar_data in bars_at_time:
            candle = Candle(at=datetime.fromisoformat(bar_data.timestamp), open=bar_data.open,
                            high=bar_data.high, low=bar_data.low, close=bar_data.close,
                            volume=bar_data.volume)
            self.engine.process_candle(symbol, candle)
            self.engine.process_tick(symbol, Tick(symbol=symbol, price=bar_data.close, time=bar_close))
        opps = [self._smc_opp_to_dict(o) for o in self.engine.get_opportunities()]
        self._record_opportunities_smc(opps)
        self._execute_auto_trades_smc(opps)
        self._process_exits(bars_at_time)

    @staticmethod
    def _smc_opp_to_dict(opp) -> dict:
        """Serialize an SMCOpportunity to the dict the journaling/auto-trade code reads (mirrors the
        radar.dashboard /api/smc-state payload)."""
        return {
            'symbol': opp.symbol,
            'price': opp.price,
            'score': opp.score,
            'zone': opp.zone.zone_type if opp.zone else None,
            'trade': opp.trade,     # {side, entry, stop, target, rr, in_fresh_ob} or None
            'confluence': opp.confluence,
        }

    def _record_opportunities_smc(self, opps: list):
        """Journal SMC opportunities that carry a trade plan — one row per (symbol, side), best score.

        Uses the engine's raw opportunities (no prerequisite RVOL filter) to stay faithful to how live
        SMC trading works: order_engine._auto_trade_smc trades off the raw score/zone/R:R, not the
        prereq filter (which is an ORB radar/journaling concern).
        """
        if not opps:
            return
        day = self.sim_run.start_date
        existing = {(s.symbol, s.side): s for s in self.db.query(SimSignalLog).filter_by(
            sim_run_id=self.sim_run.id, day=day).all()}
        changed = False
        for o in opps:
            plan = o.get('trade') or {}
            side = plan.get('side')
            if side not in ('LONG', 'SHORT'):
                continue   # equilibrium / no fresh order block → not a tradeable setup
            score = int(float(o.get('score') or 0))   # truncate, matching prod _auto_trade_smc
            key = (o.get('symbol'), side)
            prev = existing.get(key)
            entry, stop = _fmt_num(plan.get('entry')), _fmt_num(plan.get('stop'))
            target, net_rr = _fmt_num(plan.get('target')), _fmt_num(plan.get('rr'))
            rvol = _fmt_num((o.get('confluence') or {}).get('rvol_cum'))
            if prev is None:
                log = SimSignalLog(
                    sim_run_id=self.sim_run.id, user_id=self.sim_run.user_id, day=day,
                    sim_time=self.current_time.isoformat(), symbol=o.get('symbol'), side=side,
                    state=o.get('zone') or 'SMC', score=score, entry=entry, stop=stop, target=target,
                    net_rr=net_rr, rvol=rvol, provisional=0, note=f"SMC {o.get('zone')} setup",
                    timeline=json.dumps([{'t': self.current_time.strftime('%H:%M:%S'),
                                          'event': o.get('zone') or 'SMC', 'detail': f"score {score}"}]))
                self.db.add(log)
                existing[key] = log
                changed = True
            elif score > (prev.score or 0):
                prev.state = o.get('zone') or prev.state
                prev.score = score
                prev.entry = entry or prev.entry
                prev.stop = stop or prev.stop
                prev.target = target or prev.target
                prev.net_rr = net_rr or prev.net_rr
                prev.rvol = rvol or prev.rvol
                prev.sim_time = self.current_time.isoformat()
                changed = True
        if changed:
            self.db.commit()

    def _execute_auto_trades_smc(self, opps: list):
        """Auto paper-trade SMC opportunities — mirrors order_engine._auto_trade_smc, one entry/symbol."""
        if not self.config.get('auto_paper_trade'):
            return
        try:
            min_score = int(self.config.get('auto_trade_smc_min_score', 80) or 80)
        except (TypeError, ValueError):
            min_score = 80
        min_rr = float(self.config.get('min_net_reward_risk', 2.0) or 2.0)
        enforce_rr = bool(self.config.get('smc_enforce_min_rr', True))
        runner = bool(self.config.get('smc_runner_target', False))
        capital = self.config.get('capital_inr', 100000)
        risk_pct = self.config.get('risk_pct', 1.0)
        max_risk = capital * risk_pct / 100
        if not max_risk:
            return
        # Trade off the engine's RAW opportunities — no prerequisite RVOL filter — exactly like
        # order_engine._auto_trade_smc. The SMC score/zone/R:R are the quality gate.
        placed = False
        for o in opps:
            try:
                score = int(float(o.get('score') or 0))   # truncate, matching prod _auto_trade_smc
            except (TypeError, ValueError):
                continue
            if score < min_score:
                continue
            plan = o.get('trade') or {}
            side = plan.get('side')
            entry, stop, target, rr = (plan.get('entry'), plan.get('stop'),
                                       plan.get('target'), plan.get('rr'))
            if side not in ('LONG', 'SHORT') or not entry or not stop or (not target and not runner):
                continue
            if enforce_rr and (rr is None or rr < min_rr):
                continue
            symbol = o.get('symbol')
            if not symbol or symbol in self.open_orders or symbol in self.traded_symbols:
                continue
            rps = abs(entry - stop)
            qty = int(max_risk / rps) if rps > 0 else 0
            if qty < 1:
                continue
            order = SimOrder(
                sim_run_id=self.sim_run.id, user_id=self.sim_run.user_id, symbol=symbol, side=side,
                qty=qty, entry=entry, stop=stop, target=(None if runner else target),
                status='open', source='auto_smc', created_at=self.current_time.isoformat())
            self.db.add(order)
            self.open_orders[symbol] = order
            self.traded_symbols.add(symbol)
            placed = True
        if placed:
            self.db.commit()

    def _record_opportunities(self, state: dict):
        """
        Record opportunities (journal entries) from engine state.

        Similar to production journaling.py but writes to sim_signal_logs.
        Applies prerequisite filters just like production.
        """
        from .journaling import ACTIONABLE, _PRIORITY
        from .models import User

        all_opps = state.get('all') or []
        if not all_opps:
            return

        # Apply prerequisite filters (EXACT same logic as production)
        user = self.db.query(User).get(self.sim_run.user_id)
        if user:
            from .journaling import apply_prerequisite_filters
            filtered_opps, rejected_count = apply_prerequisite_filters(
                all_opps, user, strategy='ORB'
            )
            if rejected_count > 0:
                logger.debug(f"Prerequisite filters rejected {rejected_count} opportunities")
            # Use filtered opportunities
            rows = [r for r in filtered_opps if r.get('state') in ACTIONABLE]
        else:
            rows = [r for r in all_opps if r.get('state') in ACTIONABLE]

        if not rows:
            return

        day = self.sim_run.start_date
        existing = {(s.symbol, s.side): s for s in
                    self.db.query(SimSignalLog).filter_by(
                        sim_run_id=self.sim_run.id,
                        day=day
                    ).all()}

        changed = False
        for r in rows:
            key = (r.get('symbol'), r.get('side'))
            state_name = r.get('state')
            prev = existing.get(key)

            if prev is None:
                # New opportunity
                timeline = [{'t': self.current_time.strftime('%H:%M:%S'),
                            'event': state_name,
                            'detail': r.get('reason')}]

                log = SimSignalLog(
                    sim_run_id=self.sim_run.id,
                    user_id=self.sim_run.user_id,
                    day=day,
                    sim_time=self.current_time.isoformat(),
                    symbol=r.get('symbol'),
                    side=r.get('side'),
                    state=state_name,
                    score=r.get('score') or 0,
                    entry=_fmt_num(r.get('entry')),
                    stop=_fmt_num(r.get('stop')),
                    target=_fmt_num(r.get('target')),
                    net_rr=_fmt_num(r.get('net_rr')),
                    rvol=_fmt_num(r.get('rvol')),
                    qty=r.get('qty'),
                    provisional=1 if r.get('provisional') else 0,
                    note=r.get('reason'),
                    timeline=json.dumps(timeline)
                )
                self.db.add(log)
                changed = True

            elif _PRIORITY.get(state_name, 0) > _PRIORITY.get(prev.state, 0):
                # Better state reached
                timeline = json.loads(prev.timeline or '[]')
                timeline.append({'t': self.current_time.strftime('%H:%M:%S'),
                               'event': state_name,
                               'detail': r.get('reason')})

                prev.state = state_name
                prev.score = max(prev.score or 0, r.get('score') or 0)
                prev.entry = _fmt_num(r.get('entry')) or prev.entry
                prev.stop = _fmt_num(r.get('stop')) or prev.stop
                prev.target = _fmt_num(r.get('target')) or prev.target
                prev.net_rr = _fmt_num(r.get('net_rr')) or prev.net_rr
                prev.rvol = _fmt_num(r.get('rvol')) or prev.rvol
                prev.provisional = 1 if r.get('provisional') else 0
                prev.timeline = json.dumps(timeline)
                prev.sim_time = self.current_time.isoformat()
                changed = True

        if changed:
            self.db.commit()

    def _execute_auto_trades(self, state: dict):
        """
        Execute simulated auto-trades based on engine state.

        Similar to production auto-trade but:
        - Instant fills at signal price
        - No broker API calls
        - Writes to sim_orders table

        Applies EXACT same prerequisite filters as production.
        """
        # Check if auto-trade enabled
        if not self.config.get('auto_paper_trade'):
            return

        # Get trigger state (RETEST_READY or CONFIRMED)
        trigger = self.config.get('auto_trade_trigger', 'RETEST_READY').upper()
        if trigger not in ('RETEST_READY', 'CONFIRMED'):
            trigger = 'RETEST_READY'

        # Apply prerequisite filters (EXACT same as production)
        from .models import User
        all_opps = state.get('all', [])
        if not all_opps:
            return

        user = self.db.query(User).get(self.sim_run.user_id)
        if user:
            from .journaling import apply_prerequisite_filters
            filtered_opps, _ = apply_prerequisite_filters(all_opps, user, strategy='ORB')
        else:
            filtered_opps = all_opps

        for opp in filtered_opps:
            # Mirror production (order_engine._auto_trade): the CONFIRMED trigger enters on the breakout
            # confirmation OR the later retest — whichever first carries a ticket. In replay, entry/stop
            # are only populated at RETEST_READY (a CONFIRMED row has no ticket yet), so both triggers
            # effectively enter at the retest. Matching the state EXACTLY to 'CONFIRMED' matched only
            # ticketless rows and produced ZERO trades; the ticketless rows are then skipped below by the
            # entry/stop guard, so this safely waits for RETEST_READY.
            opp_state = opp.get('state')
            if trigger == 'CONFIRMED':
                if opp_state not in ('CONFIRMED', 'RETEST_READY'):
                    continue
            elif opp_state != 'RETEST_READY':
                continue

            symbol = opp.get('symbol')
            if not symbol:
                continue

            # Skip if currently in a position OR already traded this symbol in the run (no re-entering
            # the same frozen replayed signal — that was the source of 200+ duplicate trades).
            if symbol in self.open_orders or symbol in self.traded_symbols:
                continue

            # Create simulated order
            side = opp.get('side')
            entry = opp.get('entry')
            stop = opp.get('stop')
            target = opp.get('target')

            if not all([side, entry, stop]):
                continue

            # Calculate quantity based on risk
            capital = self.config.get('capital_inr', 100000)
            risk_pct = self.config.get('risk_pct', 1.0)
            max_risk = capital * risk_pct / 100
            risk_per_share = abs(entry - stop)
            qty = int(max_risk / risk_per_share) if risk_per_share > 0 else 0

            if qty < 1:
                continue

            order = SimOrder(
                sim_run_id=self.sim_run.id,
                user_id=self.sim_run.user_id,
                symbol=symbol,
                side=side,
                qty=qty,
                entry=entry,
                stop=stop,
                target=target,
                status='open',
                source='auto',
                created_at=self.current_time.isoformat()
            )
            self.db.add(order)
            self.open_orders[symbol] = order
            self.traded_symbols.add(symbol)

        self.db.commit()

    def _process_exits(self, bars_at_time: List[tuple]):
        """
        Process stop/target exits for open orders.

        Check each open order against current bar to see if stop or target was hit.
        """
        for symbol, bar in bars_at_time:
            if symbol not in self.open_orders:
                continue

            order = self.open_orders[symbol]

            # Check if stop or target hit. target may be None (SMC runner mode = ride to EOD square-off),
            # so only test the target when it exists — otherwise only the stop can close intraday.
            if order.side == 'LONG':
                if bar.low <= order.stop:
                    self._close_order(order, order.stop, 'stop')
                elif order.target is not None and bar.high >= order.target:
                    self._close_order(order, order.target, 'target')

            elif order.side == 'SHORT':
                if bar.high >= order.stop:
                    self._close_order(order, order.stop, 'stop')
                elif order.target is not None and bar.low <= order.target:
                    self._close_order(order, order.target, 'target')

    def _close_order(self, order: SimOrder, close_price: float, reason: str):
        """Close an order and calculate P&L."""
        order.status = 'closed'
        order.closed_at = self.current_time.isoformat()
        order.close_price = close_price
        order.close_reason = reason

        # Calculate P&L
        if order.side == 'LONG':
            pnl_per_share = close_price - order.entry
        else:  # SHORT
            pnl_per_share = order.entry - close_price

        order.pnl = pnl_per_share * order.qty

        # Calculate result in R
        risk_per_share = abs(order.entry - order.stop)
        order.result_r = pnl_per_share / risk_per_share if risk_per_share > 0 else 0

        # Remove from open orders
        if order.symbol in self.open_orders:
            del self.open_orders[order.symbol]

        self.db.commit()

        logger.debug(f"Closed {order.symbol} at {close_price} ({reason}): {order.result_r:.2f}R")

    def _finalize_simulation(self):
        """
        Finalize simulation - calculate metrics and update sim_run.
        """
        logger.info("Finalizing simulation...")

        # Close any remaining open orders at EOD
        self._close_all_at_eod()

        # Calculate summary metrics
        metrics = self._calculate_metrics()

        # Update sim_run
        self.sim_run.status = 'completed'
        self.sim_run.completed_at = now_ist()
        self.sim_run.total_opportunities = metrics['total_opportunities']
        self.sim_run.total_trades = metrics['total_trades']
        self.sim_run.total_pnl = metrics['total_pnl']
        self.sim_run.win_rate = metrics['win_rate']
        self.sim_run.expectancy_r = metrics['expectancy_r']
        self.sim_run.total_r = metrics['total_r']
        self.sim_run.max_drawdown_r = metrics['max_drawdown_r']

        self.db.commit()

        logger.info(f"Simulation complete: {metrics['total_trades']} trades, "
                   f"{metrics['win_rate']:.1f}% win rate, {metrics['total_r']:.2f}R total")

    def _close_all_at_eod(self):
        """Close all open orders at end of day."""
        # Get all open orders
        open_orders = self.db.query(SimOrder).filter_by(
            sim_run_id=self.sim_run.id,
            status='open'
        ).all()

        # Close each at last known price
        # (In a real implementation, we'd use the closing price of the last bar)
        for order in open_orders:
            # For now, close at entry price (no P&L)
            # TODO: Use actual closing bar price
            self._close_order(order, order.entry, 'eod')

    def _calculate_metrics(self) -> dict:
        """Calculate simulation metrics."""
        # Total opportunities
        total_opps = self.db.query(SimSignalLog).filter_by(
            sim_run_id=self.sim_run.id
        ).count()

        # Total trades
        trades = self.db.query(SimOrder).filter_by(
            sim_run_id=self.sim_run.id,
            status='closed'
        ).all()

        total_trades = len(trades)
        if total_trades == 0:
            return {
                'total_opportunities': total_opps,
                'total_trades': 0,
                'total_pnl': 0,
                'win_rate': 0,
                'expectancy_r': 0,
                'total_r': 0,
                'max_drawdown_r': 0
            }

        # Calculate metrics
        total_pnl = sum(t.pnl or 0 for t in trades)
        total_r = sum(t.result_r or 0 for t in trades)
        wins = [t for t in trades if (t.pnl or 0) > 0]
        win_rate = (len(wins) / total_trades) * 100 if total_trades > 0 else 0
        expectancy_r = total_r / total_trades if total_trades > 0 else 0

        # Max drawdown
        equity_curve = []
        cumulative_r = 0
        for t in sorted(trades, key=lambda x: x.created_at):
            cumulative_r += t.result_r or 0
            equity_curve.append(cumulative_r)

        max_drawdown_r = 0
        if equity_curve:
            peak = equity_curve[0]
            for r in equity_curve:
                if r > peak:
                    peak = r
                drawdown = peak - r
                if drawdown > max_drawdown_r:
                    max_drawdown_r = drawdown

        return {
            'total_opportunities': total_opps,
            'total_trades': total_trades,
            'total_pnl': total_pnl,
            'win_rate': win_rate,
            'expectancy_r': expectancy_r,
            'total_r': total_r,
            'max_drawdown_r': max_drawdown_r
        }


# ---- orphaned-run recovery ---------------------------------------------------------------------
# A sim is claimed and run by the sim-worker pod (server/sim_worker). If that pod dies mid-run the row
# is left non-terminal forever at its last progress, so this reconciler fails it once its heartbeat goes
# stale. A still-'pending' row is just queued (not orphaned) — see the long pending grace below.
_NONTERMINAL_SIM_STATUSES = ('pending', 'fetching_data', 'running')
_SIM_HEARTBEAT_STALE_SECONDS = 300   # a CLAIMED run stamps heartbeat_at per-symbol / per-10-timestamps;
#                                      stale => the pod executing it died mid-run.
# 'pending' is a durable queue entry the sim-worker will claim (server/sim_worker). The worker is a
# singleton that restarts in seconds and runs sims sequentially, so a long wait means it's truly down or
# the run is unclaimable — only then (2h) do we give up on it. Short enough and this would fight a
# routine worker restart or a backed-up queue.
_SIM_PENDING_GRACE_SECONDS = 7200


def _age_seconds(dt: datetime | None, assume_tz) -> float | None:
    """Seconds since `dt`, robust to this table's mixed tz conventions (heartbeat/started = aware IST
    via now_ist(); created = naive UTC via models._now). A naive value is read as `assume_tz`."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=assume_tz)
    return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()


def reconcile_orphaned_runs(db: Session) -> int:
    """Fail any sim left non-terminal by a dead executor, so it stops showing 'running' forever.

    A live run continuously stamps heartbeat_at; this marks 'failed' only a non-terminal run whose
    heartbeat has gone stale (or that never started and is past the grace window), so a sim still
    ticking on a sibling web replica is never touched. Idempotent — safe to call every scheduler tick."""
    runs = db.query(SimRun).filter(SimRun.status.in_(_NONTERMINAL_SIM_STATUSES)).all()
    n = 0
    for run in runs:
        hb_age = _age_seconds(run.heartbeat_at, IST)
        if hb_age is not None:
            if hb_age < _SIM_HEARTBEAT_STALE_SECONDS:
                continue                     # fresh heartbeat -> still running somewhere
        else:
            created_age = _age_seconds(run.created_at, timezone.utc)
            if created_age is not None and created_age < _SIM_PENDING_GRACE_SECONDS:
                continue                     # queued recently; its executor may not have started yet
        run.status = 'failed'
        run.error_message = ('Interrupted by a server restart before it finished. Your historical data '
                             'was cached, so re-running this simulation will be fast.')
        n += 1
    if n:
        db.commit()
    return n
