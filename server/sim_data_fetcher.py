"""
Historical data fetcher for simulation/backtesting.

Fetches OHLCV data from FYERS API and caches it in sim_historical_bars table.
Supports both 1-minute and 5-minute bars.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import List

from sqlalchemy.orm import Session

from radar.utils import IST, now_ist
from .crypto import decrypt
from .models import BrokerConnection, SimHistoricalBar, SimRun

logger = logging.getLogger(__name__)


class HistoricalDataFetcher:
    """Fetches and caches historical market data from FYERS API."""

    def __init__(self, db: Session, broker_conn: BrokerConnection):
        self.db = db
        self.broker_conn = broker_conn
        self.app_id = broker_conn.app_id
        self.token = decrypt(broker_conn.token_enc)

    def fetch_day_data(self, sim_run: SimRun, symbols: List[str]) -> None:
        """
        Fetch all bars for a simulation run's date range.

        Args:
            sim_run: SimRun instance with date/time/interval config
            symbols: List of symbols to fetch (e.g., ["NSE:RELIANCE-EQ", ...])

        Updates sim_run status as it progresses.
        """
        try:
            # Mark as fetching data
            sim_run.status = 'fetching_data'
            sim_run.progress_pct = 0
            self.db.commit()

            date = sim_run.start_date
            interval = sim_run.bar_interval  # "1" or "5"
            total_symbols = len(symbols)

            logger.info(f"Fetching {interval}-min bars for {total_symbols} symbols on {date}")

            fetched_count = 0
            for idx, symbol in enumerate(symbols):
                # Check if already cached
                cached_count = self.db.query(SimHistoricalBar).filter(
                    SimHistoricalBar.symbol == symbol,
                    SimHistoricalBar.date == date,
                    SimHistoricalBar.bar_interval == interval
                ).count()

                if cached_count > 0:
                    logger.debug(f"Using cached data for {symbol}")
                    fetched_count += 1
                else:
                    # Fetch from FYERS
                    success = self._fetch_symbol_bars(symbol, date, interval)
                    if success:
                        fetched_count += 1

                # Update progress
                progress = int(((idx + 1) / total_symbols) * 100)
                sim_run.progress_pct = progress
                if idx % 10 == 0:  # Commit every 10 symbols
                    self.db.commit()

                # Rate limiting: FYERS allows ~100 requests/minute
                # Sleep briefly to avoid hitting limits
                time.sleep(0.1)

            sim_run.progress_pct = 100
            self.db.commit()

            # Verify data was actually saved
            total_bars = self.db.query(SimHistoricalBar).filter(
                SimHistoricalBar.date == date,
                SimHistoricalBar.bar_interval == interval
            ).count()
            logger.info(f"Data fetch completed: {fetched_count}/{total_symbols} symbols have data. Total bars: {total_bars}")

            if fetched_count == 0:
                raise ValueError(f"No data could be fetched for any symbols on {date}. Check broker connection and date validity.")

        except Exception as e:
            logger.error(f"Data fetch failed: {e}")
            sim_run.status = 'failed'
            sim_run.error_message = f"Data fetch failed: {str(e)}"
            self.db.commit()
            raise

    def _fetch_symbol_bars(self, symbol: str, date: str, interval: str) -> bool:
        """
        Fetch bars for a single symbol from FYERS API.

        Args:
            symbol: "NSE:RELIANCE-EQ"
            date: "2024-11-15"
            interval: "1" or "5" (minutes)

        Returns:
            True if data was fetched successfully, False otherwise
        """
        try:
            from fyers_apiv3 import fyersModel

            # Parse date
            date_obj = datetime.fromisoformat(date)

            # FYERS API range: 09:15 to 15:30 IST
            range_from = datetime(date_obj.year, date_obj.month, date_obj.day, 9, 15, 0).replace(tzinfo=IST)
            range_to = datetime(date_obj.year, date_obj.month, date_obj.day, 15, 30, 0).replace(tzinfo=IST)

            # Convert to epoch (FYERS uses seconds)
            from_epoch = int(range_from.timestamp())
            to_epoch = int(range_to.timestamp())

            # Initialize FYERS client
            fyers = fyersModel.FyersModel(
                client_id=self.app_id,
                token=self.token,
                is_async=False,
                log_path=""
            )

            # Fetch historical data
            # resolution: "1" for 1-min, "5" for 5-min
            data = {
                "symbol": symbol,
                "resolution": interval,  # "1" or "5"
                "date_format": "1",  # Unix timestamp
                "range_from": str(from_epoch),
                "range_to": str(to_epoch),
                "cont_flag": "1"
            }

            response = fyers.history(data=data)

            if response.get('s') != 'ok':
                logger.warning(f"FYERS API error for {symbol}: {response.get('message', 'Unknown error')}")
                return False

            if 'candles' not in response or not response['candles']:
                logger.warning(f"No candles returned for {symbol} on {date}")
                return False

            # Store bars in database
            bars_to_insert = []
            for candle in response['candles']:
                # candle = [timestamp, open, high, low, close, volume]
                ts_epoch = candle[0]
                ts_dt = datetime.fromtimestamp(ts_epoch, tz=IST)

                bar = SimHistoricalBar(
                    symbol=symbol,
                    date=date,
                    bar_interval=interval,
                    timestamp=ts_dt.isoformat(),
                    open=candle[1],
                    high=candle[2],
                    low=candle[3],
                    close=candle[4],
                    volume=candle[5]
                )
                bars_to_insert.append(bar)

            # Bulk insert
            if bars_to_insert:
                self.db.bulk_save_objects(bars_to_insert)
                self.db.commit()
                logger.info(f"Cached {len(bars_to_insert)} bars for {symbol}")
                return True
            else:
                return False

        except Exception as e:
            logger.error(f"Failed to fetch {symbol}: {e}")
            return False  # Continue with other symbols (don't raise)

    def get_cached_bars(self, symbol: str, date: str, interval: str) -> List[SimHistoricalBar]:
        """
        Get cached historical bars for a symbol.

        Args:
            symbol: "NSE:RELIANCE-EQ"
            date: "2024-11-15"
            interval: "1" or "5"

        Returns:
            List of SimHistoricalBar objects, ordered by timestamp
        """
        bars = self.db.query(SimHistoricalBar).filter(
            SimHistoricalBar.symbol == symbol,
            SimHistoricalBar.date == date,
            SimHistoricalBar.bar_interval == interval
        ).order_by(SimHistoricalBar.timestamp).all()

        return bars

    def get_all_cached_bars_for_run(self, sim_run: SimRun) -> dict:
        """
        Get all cached bars for a simulation run, grouped by symbol.

        Returns:
            Dict mapping symbol to list of bars:
            {
                "NSE:RELIANCE-EQ": [bar1, bar2, ...],
                "NSE:TCS-EQ": [bar1, bar2, ...],
                ...
            }
        """
        bars = self.db.query(SimHistoricalBar).filter(
            SimHistoricalBar.date == sim_run.start_date,
            SimHistoricalBar.bar_interval == sim_run.bar_interval
        ).order_by(SimHistoricalBar.symbol, SimHistoricalBar.timestamp).all()

        # Group by symbol
        bars_by_symbol = {}
        for bar in bars:
            if bar.symbol not in bars_by_symbol:
                bars_by_symbol[bar.symbol] = []
            bars_by_symbol[bar.symbol].append(bar)

        return bars_by_symbol


def estimate_data_size(num_symbols: int, interval: str) -> str:
    """
    Estimate storage size for historical data.

    Args:
        num_symbols: Number of symbols to fetch
        interval: "1" or "5"

    Returns:
        Human-readable estimate (e.g., "~15 MB")
    """
    # Trading session: 09:15 to 15:30 = 6 hours 15 minutes = 375 minutes
    if interval == "1":
        bars_per_symbol = 375  # One bar per minute
    elif interval == "5":
        bars_per_symbol = 75  # One bar per 5 minutes
    else:
        bars_per_symbol = 375

    total_bars = num_symbols * bars_per_symbol

    # Estimate ~100 bytes per bar (conservative)
    estimated_bytes = total_bars * 100

    # Convert to human-readable
    if estimated_bytes < 1024:
        return f"~{estimated_bytes} bytes"
    elif estimated_bytes < 1024 * 1024:
        return f"~{estimated_bytes / 1024:.1f} KB"
    else:
        return f"~{estimated_bytes / (1024 * 1024):.1f} MB"
