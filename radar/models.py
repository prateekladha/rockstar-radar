from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from .utils import IST


@dataclass(frozen=True)
class Candle:
    at: datetime              # start of 5-minute candle, IST
    open: float
    high: float
    low: float
    close: float
    volume: int

    @staticmethod
    def from_fyers(arr) -> 'Candle':
        if len(arr) < 6:
            raise ValueError('FYERS candle must have six fields')
        ts, o, h, l, c, volume = arr[:6]
        candle = Candle(datetime.fromtimestamp(int(ts), IST),
                        float(o), float(h), float(l), float(c), int(volume))
        if (min(o, h, l, c) <= 0 or volume < 0 or
            candle.high < max(candle.open, candle.close) or
            candle.low > min(candle.open, candle.close)):
            raise ValueError('Invalid OHLCV candle')
        return candle


@dataclass
class Instrument:
    symbol: str
    industry: str = 'Unclassified'
    median_turnover_cr: float = 0
    daily_atr_pct: float = 0
    previous_close: float = 0
    resistance: list[float] = field(default_factory=list)
    support: list[float] = field(default_factory=list)
    selection_score: float = 0
    source: str = 'AUTO'  # MORNING or AUTO; not used to bias trade scoring


@dataclass
class Tick:
    symbol: str
    price: float
    time: datetime
    daily_volume: int = 0
    avg_trade_price: float = 0
    bid_price: float = 0
    ask_price: float = 0


@dataclass
class Signal:
    time: str
    symbol: str
    side: str
    state: str
    score: int
    price: float
    rvol: Optional[float]
    note: str
    level: float
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    net_rr: Optional[float] = None
    delivered_time_ist: str = ''
    detection_lag_seconds: Optional[float] = None
    provisional: bool = False  # live-aggregated signal awaiting authoritative REST reconciliation


@dataclass
class SymbolState:
    info: Instrument
    opening: Optional[Candle] = None
    completed: dict[int, Candle] = field(default_factory=dict)
    last_tick: Optional[Tick] = None
    state: str = 'WAIT_OR'
    side: str = ''
    score: int = 0
    rvol: Optional[float] = None
    vwap: Optional[float] = None
    distance_pct: Optional[float] = None
    confirmed_at: Optional[datetime] = None
    confirmed_low: Optional[float] = None
    confirmed_high: Optional[float] = None
    confirmed_side: str = ''
    last_confirmed_bar_ts: int = 0
    entry: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    net_rr: Optional[float] = None
    reason: str = ''
    last_event_key: str = ''
    last_signal_time: Optional[datetime] = None
    stale: bool = True
    # --- realtime provisional / reconciliation bookkeeping ---
    provisional_ts: set = field(default_factory=set)  # bar ts whose stored candle is live-provisional
    confirm_bar_ts: int = 0            # ts of the 5m bar that produced CONFIRMED
    confirm_provisional: bool = False  # the confirmation is live-provisional, pending REST
    retest_provisional: bool = False   # the RETEST_READY/RISK_FAIL is live-provisional, pending REST
    retest_bar_ts: int = 0             # ts of the 5m bar that produced the retest outcome
