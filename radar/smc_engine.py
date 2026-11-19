"""Smart Money Concepts (SMC) engine for identifying institutional trading opportunities.

Implements structure detection, order blocks, premium/discount zones based on SMC methodology.
"""
from __future__ import annotations
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from .models import (
    Candle, Instrument, Tick, SMCPivot, SMCOrderBlock, SMCZone,
    SMCStructure, SMCOpportunity, SMCSymbolState
)


def calculate_atr(candles: list[Candle], period: int = 14) -> float:
    """Calculate Average True Range for volatility measurement"""
    if len(candles) < period:
        return 0.0

    true_ranges = []
    for i in range(1, min(len(candles), period + 1)):
        high = candles[-i].high
        low = candles[-i].low
        prev_close = candles[-i-1].close if i < len(candles) else candles[-i].close

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        true_ranges.append(tr)

    return sum(true_ranges) / len(true_ranges) if true_ranges else 0.0


def detect_leg(candles: list[Candle], size: int = 5) -> int:
    """Detect current market leg (0 = bearish, 1 = bullish)"""
    if len(candles) < size + 1:
        return 0

    # Check if we have a new leg high (bearish leg)
    pivot_high = candles[-size-1].high
    recent_highs = [c.high for c in candles[-size:]]
    new_leg_high = pivot_high > max(recent_highs)

    # Check if we have a new leg low (bullish leg)
    pivot_low = candles[-size-1].low
    recent_lows = [c.low for c in candles[-size:]]
    new_leg_low = pivot_low < min(recent_lows)

    if new_leg_high:
        return 0  # Bearish leg
    elif new_leg_low:
        return 1  # Bullish leg

    return 0


def detect_pivot(candles: list[Candle], size: int = 5) -> tuple[Optional[SMCPivot], Optional[SMCPivot]]:
    """Detect swing high and low pivots"""
    if len(candles) < size * 2 + 1:
        return None, None

    pivot_high = None
    pivot_low = None

    # Check for pivot high
    pivot_idx = -size - 1
    pivot_candle = candles[pivot_idx]

    left_highs = [c.high for c in candles[pivot_idx - size:pivot_idx]]
    right_highs = [c.high for c in candles[pivot_idx + 1:pivot_idx + size + 1]]

    if left_highs and right_highs:
        if pivot_candle.high >= max(left_highs) and pivot_candle.high >= max(right_highs):
            pivot_high = SMCPivot(
                level=pivot_candle.high,
                time=pivot_candle.at,
                bar_index=len(candles) + pivot_idx,
                pivot_type='HIGH'
            )

    # Check for pivot low
    left_lows = [c.low for c in candles[pivot_idx - size:pivot_idx]]
    right_lows = [c.low for c in candles[pivot_idx + 1:pivot_idx + size + 1]]

    if left_lows and right_lows:
        if pivot_candle.low <= min(left_lows) and pivot_candle.low <= min(right_lows):
            pivot_low = SMCPivot(
                level=pivot_candle.low,
                time=pivot_candle.at,
                bar_index=len(candles) + pivot_idx,
                pivot_type='LOW'
            )

    return pivot_high, pivot_low


def detect_order_block(candles: list[Candle], pivot: SMCPivot, bias: str) -> Optional[SMCOrderBlock]:
    """Detect order block around a pivot point"""
    if len(candles) < 3:
        return None

    # Find the candle that created the pivot
    pivot_idx = None
    for i, candle in enumerate(candles):
        if abs((candle.at - pivot.time).total_seconds()) < 300:  # Within 5 minutes
            pivot_idx = i
            break

    if pivot_idx is None or pivot_idx == 0:
        return None

    # Order block is typically the candle before the pivot
    ob_candle = candles[pivot_idx - 1]

    return SMCOrderBlock(
        high=ob_candle.high,
        low=ob_candle.low,
        time=ob_candle.at,
        bias=bias,
        block_type='SWING'
    )


def calculate_zones(trailing_high: float, trailing_low: float) -> list[SMCZone]:
    """Calculate Premium, Equilibrium, and Discount zones"""
    if trailing_high <= trailing_low:
        return []

    range_size = trailing_high - trailing_low

    # Premium: top 25% of range
    premium = SMCZone(
        zone_type='PREMIUM',
        high=trailing_high,
        low=trailing_high - (0.25 * range_size)
    )

    # Equilibrium: middle 50% of range
    equilibrium = SMCZone(
        zone_type='EQUILIBRIUM',
        high=trailing_high - (0.25 * range_size),
        low=trailing_low + (0.25 * range_size)
    )

    # Discount: bottom 25% of range
    discount = SMCZone(
        zone_type='DISCOUNT',
        high=trailing_low + (0.25 * range_size),
        low=trailing_low
    )

    return [premium, equilibrium, discount]


def get_current_zone(price: float, zones: list[SMCZone]) -> Optional[SMCZone]:
    """Determine which zone the current price is in"""
    for zone in zones:
        if zone.low <= price <= zone.high:
            return zone
    return None


def calculate_smc_score(state: SMCSymbolState, current_price: float) -> int:
    """Calculate SMC opportunity score (0-100) based on confluence factors.

    Scoring logic:
    - Premium + Strong High: 90-100
    - Discount + Strong Low: 90-100
    - Premium + Weak High: 70-85
    - Discount + Weak Low: 70-85
    - Equilibrium + any structure: 40-60
    - Other combinations: 0-40
    """
    if not state.trailing_high or not state.trailing_low:
        return 0

    zones = calculate_zones(state.trailing_high, state.trailing_low)
    current_zone = get_current_zone(current_price, zones)

    if not current_zone:
        return 0

    score = 0

    # Base score from zone
    if current_zone.zone_type == 'PREMIUM':
        score = 60
    elif current_zone.zone_type == 'DISCOUNT':
        score = 60
    else:  # EQUILIBRIUM
        score = 30

    # Bonus for strong/weak highs and lows
    if current_zone.zone_type == 'PREMIUM':
        if state.swing_high and state.swing_high.is_strong:
            score += 35  # Strong high in premium = bearish setup
        elif state.swing_high:
            score += 20  # Weak high in premium

    elif current_zone.zone_type == 'DISCOUNT':
        if state.swing_low and state.swing_low.is_strong:
            score += 35  # Strong low in discount = bullish setup
        elif state.swing_low:
            score += 20  # Weak low in discount

    # Bonus for order blocks nearby
    ob_bonus = 0
    for ob in state.order_blocks[-3:]:  # Check last 3 order blocks
        if abs(current_price - ob.low) / current_price < 0.02:  # Within 2%
            ob_bonus += 5
        if abs(current_price - ob.high) / current_price < 0.02:
            ob_bonus += 5

    score += min(ob_bonus, 15)

    # Bonus for recent structure breaks
    if state.structures:
        recent_structure = state.structures[-1]
        if current_zone.zone_type == 'PREMIUM' and recent_structure.bias == 'BEARISH':
            score += 10
        elif current_zone.zone_type == 'DISCOUNT' and recent_structure.bias == 'BULLISH':
            score += 10

    return min(score, 100)


class SMCEngine:
    """Engine for Smart Money Concepts analysis across multiple symbols"""

    def __init__(self, instruments: list[Instrument], config: dict):
        self.config = config
        self.lock = threading.RLock()
        self.states: dict[str, SMCSymbolState] = {
            info.symbol: SMCSymbolState(info=info)
            for info in instruments
        }
        # Keep more candles for proper swing detection (50 left + 50 right + buffer)
        self.max_candles = 150

    def load_historical_candles(self, symbol: str, candles: list[Candle]):
        """Pre-load historical candles for a symbol to enable proper swing detection"""
        with self.lock:
            if symbol not in self.states:
                return

            state = self.states[symbol]
            # Sort by time and keep most recent candles
            all_candles = sorted(candles, key=lambda c: c.at)
            state.candles = all_candles[-self.max_candles:] if len(all_candles) > self.max_candles else all_candles

            # Initialize trailing extremes from historical data
            if state.candles:
                highs = [c.high for c in state.candles]
                lows = [c.low for c in state.candles]
                state.trailing_high = max(highs)
                state.trailing_low = min(lows)
                # Find when these extremes occurred
                for c in reversed(state.candles):
                    if c.high == state.trailing_high:
                        state.trailing_high_time = c.at
                    if c.low == state.trailing_low:
                        state.trailing_low_time = c.at

            # Calculate initial ATR
            state.atr = calculate_atr(state.candles)

            # Initial analysis if we have enough data
            if len(state.candles) >= 101:  # Minimum for swing detection with size=50
                self._analyze_symbol(state)

    def _analyze_symbol(self, state: SMCSymbolState):
        """Internal method to analyze a symbol's candles for SMC patterns"""
        if len(state.candles) < 101:  # Need 101 candles for proper swing detection (50+1+50)
            return

        # Update ATR
        state.atr = calculate_atr(state.candles)

        # Detect pivots
        swing_high, swing_low = detect_pivot(state.candles, size=50)
        internal_high, internal_low = detect_pivot(state.candles, size=5)

        # Update swing pivots
        if swing_high:
            # Determine if strong or weak high
            if state.swing_high:
                swing_high.is_strong = swing_high.level > state.swing_high.level
            else:
                swing_high.is_strong = True
            state.swing_high = swing_high

            # Detect order block
            ob = detect_order_block(state.candles, swing_high, 'BEARISH')
            if ob:
                state.order_blocks.append(ob)
                if len(state.order_blocks) > 10:
                    state.order_blocks.pop(0)

        if swing_low:
            # Determine if strong or weak low
            if state.swing_low:
                swing_low.is_strong = swing_low.level < state.swing_low.level
            else:
                swing_low.is_strong = True
            state.swing_low = swing_low

            # Detect order block
            ob = detect_order_block(state.candles, swing_low, 'BULLISH')
            if ob:
                state.order_blocks.append(ob)
                if len(state.order_blocks) > 10:
                    state.order_blocks.pop(0)

        # Update internal pivots
        if internal_high:
            state.internal_high = internal_high
        if internal_low:
            state.internal_low = internal_low

        # Detect structure (simplified - full BOS/CHoCH detection would be more complex)
        if len(state.candles) >= 2:
            current_candle = state.candles[-1]
            prev_candle = state.candles[-2]

            # Bullish structure break
            if state.swing_high and current_candle.close > state.swing_high.level > prev_candle.close:
                structure = SMCStructure(
                    structure_type='BOS' if state.trend == 'BULLISH' else 'CHOCH',
                    bias='BULLISH',
                    level=state.swing_high.level,
                    time=current_candle.at
                )
                state.structures.append(structure)
                state.trend = 'BULLISH'
                if len(state.structures) > 10:
                    state.structures.pop(0)

            # Bearish structure break
            if state.swing_low and current_candle.close < state.swing_low.level < prev_candle.close:
                structure = SMCStructure(
                    structure_type='BOS' if state.trend == 'BEARISH' else 'CHOCH',
                    bias='BEARISH',
                    level=state.swing_low.level,
                    time=current_candle.at
                )
                state.structures.append(structure)
                state.trend = 'BEARISH'
                if len(state.structures) > 10:
                    state.structures.pop(0)

    def process_candle(self, symbol: str, candle: Candle):
        """Process a new candle for SMC analysis"""
        with self.lock:
            if symbol not in self.states:
                return

            state = self.states[symbol]

            # Add candle to history
            state.candles.append(candle)
            if len(state.candles) > self.max_candles:
                state.candles.pop(0)

            # Update trailing extremes with new candle
            if not state.trailing_high or candle.high > state.trailing_high:
                state.trailing_high = candle.high
                state.trailing_high_time = candle.at

            if not state.trailing_low or candle.low < state.trailing_low:
                state.trailing_low = candle.low
                state.trailing_low_time = candle.at

            # Perform full analysis
            self._analyze_symbol(state)

    def process_tick(self, symbol: str, tick: Tick):
        """Update current price from tick data"""
        with self.lock:
            if symbol not in self.states:
                return

            state = self.states[symbol]
            state.last_tick = tick

            # Update opportunity if we have enough data
            if len(state.candles) >= 50:
                self._update_opportunity(state, tick.price)

    def _update_opportunity(self, state: SMCSymbolState, current_price: float):
        """Calculate and update SMC opportunity for a symbol"""
        if not state.trailing_high or not state.trailing_low:
            return

        zones = calculate_zones(state.trailing_high, state.trailing_low)
        current_zone = get_current_zone(current_price, zones)
        score = calculate_smc_score(state, current_price)

        # Filter out low-score opportunities
        if score < 40:
            state.opportunity = None
            return

        # Create opportunity
        state.opportunity = SMCOpportunity(
            symbol=state.info.symbol,
            price=current_price,
            score=score,
            zone=current_zone,
            strong_high=state.swing_high.level if state.swing_high and state.swing_high.is_strong else None,
            strong_low=state.swing_low.level if state.swing_low and state.swing_low.is_strong else None,
            weak_high=state.swing_high.level if state.swing_high and not state.swing_high.is_strong else None,
            weak_low=state.swing_low.level if state.swing_low and not state.swing_low.is_strong else None,
            bullish_order_blocks=[ob for ob in state.order_blocks if ob.bias == 'BULLISH'][-3:],
            bearish_order_blocks=[ob for ob in state.order_blocks if ob.bias == 'BEARISH'][-3:],
            recent_structure=state.structures[-1] if state.structures else None,
            time=datetime.now(),
            note=self._generate_note(state, current_zone)
        )

    def _generate_note(self, state: SMCSymbolState, zone: Optional[SMCZone]) -> str:
        """Generate descriptive note for the opportunity"""
        if not zone:
            return ""

        notes = []

        if zone.zone_type == 'PREMIUM':
            notes.append("In premium zone")
            if state.swing_high and state.swing_high.is_strong:
                notes.append("near strong high - potential reversal")
            elif state.swing_high:
                notes.append("near weak high")
        elif zone.zone_type == 'DISCOUNT':
            notes.append("In discount zone")
            if state.swing_low and state.swing_low.is_strong:
                notes.append("near strong low - potential reversal")
            elif state.swing_low:
                notes.append("near weak low")
        else:
            notes.append("In equilibrium zone")

        if state.order_blocks:
            recent_ob = state.order_blocks[-1]
            notes.append(f"{recent_ob.bias.lower()} order block nearby")

        if state.structures:
            recent_structure = state.structures[-1]
            notes.append(f"{recent_structure.bias.lower()} {recent_structure.structure_type}")

        return " · ".join(notes)

    def get_opportunities(self) -> list[SMCOpportunity]:
        """Get all current SMC opportunities sorted by score"""
        with self.lock:
            opportunities = []
            for state in self.states.values():
                if state.opportunity and state.opportunity.score >= 40:
                    opportunities.append(state.opportunity)

            # Sort by score descending
            opportunities.sort(key=lambda x: x.score, reverse=True)
            return opportunities

    def get_state(self, symbol: str) -> Optional[SMCSymbolState]:
        """Get SMC state for a specific symbol"""
        with self.lock:
            return self.states.get(symbol)
