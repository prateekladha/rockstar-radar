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
    # Authoritative bars covering the opening-range window, keyed by epoch. On the 5-minute setting
    # that is a single candle; on 1-minute it is five, merged into `opening` once all have arrived.
    or_bars: dict[int, Candle] = field(default_factory=dict)
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
    confirm_bar_ts: int = 0            # ts of the signal bar that produced CONFIRMED
    confirm_provisional: bool = False  # the confirmation is live-provisional, pending REST
    retest_provisional: bool = False   # the RETEST_READY/RISK_FAIL is live-provisional, pending REST
    retest_bar_ts: int = 0             # ts of the signal bar that produced the retest outcome


# SMC (Smart Money Concepts) models
@dataclass
class SMCPivot:
    """Represents a swing high or low pivot point"""
    level: float
    time: datetime
    bar_index: int
    pivot_type: str  # 'HIGH' or 'LOW'
    is_strong: bool = False  # Strong high/low vs weak high/low


@dataclass
class SMCOrderBlock:
    """Order block zone - institutional demand/supply area"""
    high: float
    low: float
    time: datetime
    bias: str  # 'BULLISH' or 'BEARISH'
    block_type: str  # 'SWING' or 'INTERNAL'
    # Enhanced fields for better tracking
    body_high: Optional[float] = None  # 50% retracement level (key OB zone)
    body_low: Optional[float] = None   # 50% retracement level
    strength: float = 0.0  # 0-1 score based on candle quality
    mitigated: bool = False  # Has price returned to OB?
    touch_count: int = 0  # How many times price touched OB


@dataclass
class SMCFairValueGap:
    """Fair Value Gap (FVG) - price imbalance zone"""
    high: float  # Top of the gap
    low: float   # Bottom of the gap
    time: datetime  # When gap was formed
    bias: str  # 'BULLISH' or 'BEARISH'
    gap_size_pct: float  # Gap size as % of price
    filled: bool = False  # Has gap been filled?
    fill_percentage: float = 0.0  # How much of gap is filled (0-100%)


@dataclass
class SMCZone:
    """Premium, Discount, or Equilibrium zone"""
    zone_type: str  # 'PREMIUM', 'DISCOUNT', 'EQUILIBRIUM'
    high: float
    low: float


@dataclass
class SMCStructure:
    """Market structure - BOS or CHoCH"""
    structure_type: str  # 'BOS' or 'CHOCH'
    bias: str  # 'BULLISH' or 'BEARISH'
    level: float
    time: datetime
    internal: bool = False  # Internal vs swing structure


@dataclass
class SMCOpportunity:
    """SMC-based trading opportunity with scoring"""
    symbol: str
    price: float
    score: int  # 0-100 based on confluence of factors
    zone: Optional[SMCZone] = None
    strong_high: Optional[float] = None
    strong_low: Optional[float] = None
    weak_high: Optional[float] = None
    weak_low: Optional[float] = None
    bullish_order_blocks: list[SMCOrderBlock] = field(default_factory=list)
    bearish_order_blocks: list[SMCOrderBlock] = field(default_factory=list)
    recent_structure: Optional[SMCStructure] = None
    time: Optional[datetime] = None
    note: str = ''
    # Derived auto-trade plan (None when the setup isn't tradeable). Keys when present:
    # side ('LONG'/'SHORT'), in_fresh_ob (bool), and — only once in a fresh OB with a target —
    # entry, stop, target, rr (net reward:risk after costs). The order engine trades it only when
    # in_fresh_ob is True and rr clears the configured minimum.
    trade: Optional[dict] = None
    # Decision-support confluence stack (RSI, fib pivots, volume profile, cumulative RVOL, structure,
    # weighted score) computed for the trader to read on the radar. Context only — never an auto gate.
    confluence: Optional[dict] = None


@dataclass
class SMCSymbolState:
    """State tracking for SMC analysis of a symbol"""
    info: Instrument
    candles: list[Candle] = field(default_factory=list)  # Recent candles for analysis
    last_tick: Optional[Tick] = None

    # Swing structure tracking
    swing_high: Optional[SMCPivot] = None
    swing_low: Optional[SMCPivot] = None
    internal_high: Optional[SMCPivot] = None
    internal_low: Optional[SMCPivot] = None

    # Extremes for premium/discount calculation
    trailing_high: Optional[float] = None
    trailing_low: Optional[float] = None
    trailing_high_time: Optional[datetime] = None
    trailing_low_time: Optional[datetime] = None

    # Zone tracking for recency
    current_zone_type: Optional[str] = None  # 'PREMIUM', 'DISCOUNT', 'EQUILIBRIUM'
    zone_entry_time: Optional[datetime] = None  # When price entered current zone

    # Current trend
    trend: str = 'NEUTRAL'  # 'BULLISH', 'BEARISH', 'NEUTRAL'

    # Order blocks
    order_blocks: list[SMCOrderBlock] = field(default_factory=list)

    # Fair Value Gaps
    fair_value_gaps: list[SMCFairValueGap] = field(default_factory=list)

    # Recent structures
    structures: list[SMCStructure] = field(default_factory=list)

    # Current opportunity
    opportunity: Optional[SMCOpportunity] = None

    # ATR for volatility measurement
    atr: float = 0.0
