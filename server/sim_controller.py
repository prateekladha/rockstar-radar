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
from datetime import datetime, timedelta, date
from typing import List, Dict, Any

from sqlalchemy.orm import Session

from radar.engine import RadarEngine
from radar.models import Candle, Instrument
from radar.utils import IST, now_ist
from .models import SimRun, SimHistoricalBar, SimSignalLog, SimOrder
from .sim_data_fetcher import HistoricalDataFetcher

logger = logging.getLogger(__name__)


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

        # Will be initialized during replay
        self.engine: RadarEngine = None
        self.open_orders: Dict[str, SimOrder] = {}  # symbol -> order
        self.symbols: List[str] = []

    def run(self) -> None:
        """Main entry point - run the complete simulation."""
        try:
            logger.info(f"Starting simulation run {self.sim_run.id}: {self.sim_run.name}")

            # Update status
            self.sim_run.status = 'running'
            self.sim_run.started_at = now_ist()
            self.sim_run.progress_pct = 0
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
        """Initialize REAL ORB engine with simulation config."""
        logger.info(f"Initializing ORB engine with {len(symbols)} symbols...")

        self.symbols = symbols

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
        Process all bars at a specific timestamp using REAL ORB engine.

        Args:
            bars_at_time: List of (symbol, SimHistoricalBar) tuples
        """
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
                    entry=str(r.get('entry')) if r.get('entry') else None,
                    stop=str(r.get('stop')) if r.get('stop') else None,
                    target=str(r.get('target')) if r.get('target') else None,
                    net_rr=str(r.get('net_rr')) if r.get('net_rr') else None,
                    rvol=str(r.get('rvol')) if r.get('rvol') else None,
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
                prev.entry = str(r.get('entry')) if r.get('entry') else prev.entry
                prev.stop = str(r.get('stop')) if r.get('stop') else prev.stop
                prev.target = str(r.get('target')) if r.get('target') else prev.target
                prev.net_rr = str(r.get('net_rr')) if r.get('net_rr') else prev.net_rr
                prev.rvol = str(r.get('rvol')) if r.get('rvol') else prev.rvol
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
            if opp.get('state') != trigger:
                continue

            symbol = opp.get('symbol')
            if not symbol:
                continue

            # Check if already in position
            if symbol in self.open_orders:
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

            # Check if stop or target hit
            if order.side == 'LONG':
                # Long position
                if bar.low <= order.stop:
                    # Stop hit
                    self._close_order(order, order.stop, 'stop')
                elif bar.high >= order.target:
                    # Target hit
                    self._close_order(order, order.target, 'target')

            elif order.side == 'SHORT':
                # Short position
                if bar.high >= order.stop:
                    # Stop hit
                    self._close_order(order, order.stop, 'stop')
                elif bar.low <= order.target:
                    # Target hit
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
