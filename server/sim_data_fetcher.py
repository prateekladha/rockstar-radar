"""
Historical data fetcher for simulation/backtesting.

Fetches OHLCV data from FYERS API and caches it in sim_historical_bars table.

Two resolutions are cached, keyed by (symbol, date, bar_interval):
  - DAILY ('D')     — prior-session daily bars used to RANK the universe and pick the ~100 symbols
                      the live scanner would have traded that day (mirrors radar.selecting).
  - INTRADAY ('1'/'5') — the sim day (replayed through the engine) PLUS the prior sessions used to
                      build the RVOL baselines.
Everything is cached persistently, so the first run for a date pays the FYERS cost and every later
run for the same date makes zero FYERS calls.
"""
from __future__ import annotations

import logging
import tempfile
import time
from datetime import datetime, timedelta
from typing import Callable, List, Optional

from sqlalchemy.orm import Session

from radar.utils import IST, market_dt
from .crypto import decrypt
from .models import BrokerConnection, SimHistoricalBar, SimRun

logger = logging.getLogger(__name__)

# FYERS Standard plan caps history at 5 requests/second. Pace at <5/s (this gap plus per-call latency
# keeps us comfortably under the cap); _history() also backs off and retries on a rate-limit trip.
_REQUEST_GAP_S = 0.22
# Max span per intraday history request. FYERS allows a large intraday range, but we chunk to stay
# safely within provider limits for 1-minute data.
_INTRADAY_CHUNK_DAYS = 30


class HistoricalDataFetcher:
    """Fetches and caches historical market data from FYERS API."""

    def __init__(self, db: Session, broker_conn: BrokerConnection):
        self.db = db
        self.broker_conn = broker_conn
        self.app_id = broker_conn.app_id
        self.token = decrypt(broker_conn.token_enc)
        self._client = None  # built once, reused

    # ---- FYERS client + low-level fetch ---------------------------------------------------------

    def _fyers(self):
        """Build the FYERS client once and reuse it.

        log_path MUST be a writable directory: the SDK writes fyersApi.log there, and an empty string
        makes it fall back to the process CWD (/app in the web pod), which the non-root container user
        cannot write — that PermissionError used to abort every history() call.
        """
        if self._client is None:
            from fyers_apiv3 import fyersModel
            self._client = fyersModel.FyersModel(
                client_id=self.app_id, token=self.token, is_async=False,
                log_path=tempfile.gettempdir())
        return self._client

    def _history(self, symbol: str, resolution: str, from_epoch: int, to_epoch: int) -> list:
        """Return raw FYERS candles [[ts, o, h, l, c, v], ...] for a range, or [] on failure.

        date_format "0" = epoch/Unix timestamp (FYERS convention; "1" = yyyy-mm-dd — passing epochs
        with "1" makes FYERS reject the request with "Invalid input"). Retries with backoff when the
        5 req/s limit is tripped.
        """
        data = {"symbol": symbol, "resolution": resolution, "date_format": "0",
                "range_from": str(int(from_epoch)), "range_to": str(int(to_epoch)), "cont_flag": "1"}
        try:
            fyers = self._fyers()
        except Exception as e:
            logger.error(f"FYERS client init failed: {e}")
            return []
        for attempt in range(4):
            try:
                resp = fyers.history(data=data)
            except Exception as e:
                logger.warning(f"history() raised for {symbol} [{resolution}]: {e}")
                return []
            msg = str(resp.get('message', '')).lower() if isinstance(resp, dict) else ''
            if isinstance(resp, dict) and resp.get('s') == 'ok':
                return resp.get('candles') or []
            if 'second' in msg or 'too many' in msg or 'rate' in msg:
                time.sleep(0.5 * (attempt + 1))  # 0.5s, 1s, 1.5s
                continue
            detail = resp.get('message', 'Unknown error') if isinstance(resp, dict) else resp
            logger.warning(f"FYERS API error for {symbol} [{resolution}]: {detail}")
            return []
        logger.warning(f"FYERS rate-limited after retries for {symbol} [{resolution}]")
        return []

    def _store_candles(self, symbol: str, interval: str, candles: list) -> int:
        """Insert candles into sim_historical_bars, skipping any (symbol, date, interval) already
        present so an overlapping re-fetch can't duplicate/double-count bars. Returns # of new dates."""
        if not candles:
            return 0
        existing = {d for (d,) in self.db.query(SimHistoricalBar.date).filter(
            SimHistoricalBar.symbol == symbol,
            SimHistoricalBar.bar_interval == interval).distinct().all()}
        rows, new_dates = [], set()
        for c in candles:
            try:
                ts_dt = datetime.fromtimestamp(int(c[0]), tz=IST)
            except (TypeError, ValueError, OSError):
                continue
            d = ts_dt.date().isoformat()
            if d in existing:
                continue
            rows.append(SimHistoricalBar(
                symbol=symbol, date=d, bar_interval=interval, timestamp=ts_dt.isoformat(),
                open=c[1], high=c[2], low=c[3], close=c[4], volume=int(c[5] or 0)))
            new_dates.add(d)
        if rows:
            self.db.bulk_save_objects(rows)
            self.db.commit()
        return len(new_dates)

    # ---- high-level fetch: selection (daily) + replay/baselines (intraday) ----------------------

    def fetch_daily_history(self, symbols: List[str], sim_date: str,
                            lookback_days: int = 90, min_sessions: int = 15,
                            on_heartbeat: Optional[Callable[[], None]] = None) -> None:
        """Cache DAILY ('D') bars for the window BEFORE sim_date, used to rank the universe for
        selection. One range call per symbol; skips symbols already holding >= min_sessions bars.

        on_heartbeat (optional) is called once per symbol so a long fetch keeps the SimRun liveness
        stamp fresh (the orphaned-run reconciler would otherwise fail a sim that's just slow to fetch)."""
        cutoff = datetime.fromisoformat(sim_date).date()
        start = cutoff - timedelta(days=lookback_days)
        frm = int(market_dt(start, '00:00').timestamp())
        to = int(market_dt(cutoff, '00:00').timestamp()) - 1  # exclude sim day (no lookahead)
        total = len(symbols)
        for i, symbol in enumerate(symbols, 1):
            if on_heartbeat:
                on_heartbeat()
            have = self.db.query(SimHistoricalBar).filter(
                SimHistoricalBar.symbol == symbol, SimHistoricalBar.bar_interval == 'D',
                SimHistoricalBar.date >= start.isoformat(),
                SimHistoricalBar.date < cutoff.isoformat()).count()
            if have >= min_sessions:
                continue
            self._store_candles(symbol, 'D', self._history(symbol, 'D', frm, to))
            time.sleep(_REQUEST_GAP_S)
            if i % 50 == 0:
                logger.info(f"Daily history: {i}/{total} symbols")

    def _fetch_intraday_window_one(self, symbol: str, interval: str,
                                   start_date, cutoff_date) -> None:
        """Fetch intraday bars for one symbol over [start_date, cutoff_date], chunked to stay within
        provider range limits. Cached; overlapping dates are skipped by _store_candles."""
        seg_start = start_date
        while seg_start <= cutoff_date:
            seg_end = min(seg_start + timedelta(days=_INTRADAY_CHUNK_DAYS), cutoff_date)
            frm = int(market_dt(seg_start, '09:00').timestamp())
            to = int(market_dt(seg_end, '15:30').timestamp())
            self._store_candles(symbol, interval, self._history(symbol, interval, frm, to))
            time.sleep(_REQUEST_GAP_S)
            seg_start = seg_end + timedelta(days=1)

    def fetch_intraday_window(self, symbols: List[str], sim_date: str, interval: str,
                              lookback_days: int = 45, min_prior: int = 2,
                              on_heartbeat: Optional[Callable[[], None]] = None) -> int:
        """Cache intraday bars for [sim_date - lookback, sim_date] for the SELECTED symbols — the sim
        day (replayed) plus prior sessions (RVOL baselines). Returns the number of symbols that have
        sim-day data. Skips a symbol that already holds sim-day + >= min_prior prior sessions.

        on_heartbeat (optional): called once per symbol to keep the SimRun liveness stamp fresh."""
        cutoff = datetime.fromisoformat(sim_date).date()
        start = cutoff - timedelta(days=lookback_days)
        have_simday = 0
        total = len(symbols)
        for i, symbol in enumerate(symbols, 1):
            if on_heartbeat:
                on_heartbeat()
            dates = {d for (d,) in self.db.query(SimHistoricalBar.date).filter(
                SimHistoricalBar.symbol == symbol, SimHistoricalBar.bar_interval == interval,
                SimHistoricalBar.date >= start.isoformat(),
                SimHistoricalBar.date <= cutoff.isoformat()).distinct().all()}
            prior = len([d for d in dates if d < sim_date])
            if sim_date in dates and prior >= min_prior:
                have_simday += 1
                continue
            self._fetch_intraday_window_one(symbol, interval, start, cutoff)
            if self.db.query(SimHistoricalBar).filter(
                    SimHistoricalBar.symbol == symbol, SimHistoricalBar.bar_interval == interval,
                    SimHistoricalBar.date == sim_date).count():
                have_simday += 1
            if i % 25 == 0:
                logger.info(f"Intraday window: {i}/{total} symbols")
        return have_simday

    # ---- cache getters --------------------------------------------------------------------------

    def get_bars_in_range(self, symbol: str, interval: str,
                          start_date: str, end_date: str) -> List[SimHistoricalBar]:
        """Cached bars for a symbol in [start_date, end_date) ordered by timestamp."""
        return self.db.query(SimHistoricalBar).filter(
            SimHistoricalBar.symbol == symbol, SimHistoricalBar.bar_interval == interval,
            SimHistoricalBar.date >= start_date, SimHistoricalBar.date < end_date
        ).order_by(SimHistoricalBar.timestamp).all()

    def get_cached_bars(self, symbol: str, date: str, interval: str) -> List[SimHistoricalBar]:
        """Cached bars for a symbol on a single date, ordered by timestamp."""
        return self.db.query(SimHistoricalBar).filter(
            SimHistoricalBar.symbol == symbol,
            SimHistoricalBar.date == date,
            SimHistoricalBar.bar_interval == interval
        ).order_by(SimHistoricalBar.timestamp).all()


def estimate_data_size(num_symbols: int, interval: str) -> str:
    """Rough storage estimate for a day's historical data (UI helper)."""
    if interval == "1":
        bars_per_symbol = 375  # one bar per minute, 09:15-15:30
    elif interval == "5":
        bars_per_symbol = 75
    else:
        bars_per_symbol = 375
    estimated_bytes = num_symbols * bars_per_symbol * 100  # ~100 bytes per bar (conservative)
    if estimated_bytes < 1024:
        return f"~{estimated_bytes} bytes"
    if estimated_bytes < 1024 * 1024:
        return f"~{estimated_bytes / 1024:.1f} KB"
    return f"~{estimated_bytes / (1024 * 1024):.1f} MB"
