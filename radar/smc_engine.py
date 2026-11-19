"""Smart Money Concepts (SMC) engine for identifying institutional trading opportunities.

Implements structure detection, order blocks, premium/discount zones based on SMC methodology.
Enhanced with institutional-grade OB and FVG detection.
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
from .smc_detection import (
    detect_order_block_enhanced,
    detect_fair_value_gaps,
    update_order_block_mitigation,
    update_fvg_fill_status
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
    """Detect swing high and low pivots by scanning recent candles.

    Returns the most recent confirmed pivot high and pivot low found in the lookback window.
    A pivot is confirmed when it has 'size' candles on both left and right that don't exceed/break it.
    """
    if len(candles) < size * 2 + 1:
        return None, None

    pivot_high = None
    pivot_low = None

    # Scan from most recent possible pivot position backwards
    # Start from position -(size+1) and go back up to 50 candles
    # This finds the most recent pivots, not just one fixed position
    scan_start = min(len(candles) - size - 1, 50)  # Don't scan too far back

    for i in range(size, scan_start):
        pivot_idx = -(i + 1)  # Negative index from end
        pivot_candle = candles[pivot_idx]

        # Get left and right context for this potential pivot
        left_start = pivot_idx - size
        left_end = pivot_idx
        right_start = pivot_idx + 1
        right_end = pivot_idx + size + 1

        # Check for pivot high (only if we haven't found one yet)
        if pivot_high is None:
            left_highs = [c.high for c in candles[left_start:left_end]]
            right_highs = [c.high for c in candles[right_start:right_end]]

            if left_highs and right_highs:
                if pivot_candle.high >= max(left_highs) and pivot_candle.high >= max(right_highs):
                    pivot_high = SMCPivot(
                        level=pivot_candle.high,
                        time=pivot_candle.at,
                        bar_index=len(candles) + pivot_idx,
                        pivot_type='HIGH'
                    )

        # Check for pivot low (only if we haven't found one yet)
        if pivot_low is None:
            left_lows = [c.low for c in candles[left_start:left_end]]
            right_lows = [c.low for c in candles[right_start:right_end]]

            if left_lows and right_lows:
                if pivot_candle.low <= min(left_lows) and pivot_candle.low <= min(right_lows):
                    pivot_low = SMCPivot(
                        level=pivot_candle.low,
                        time=pivot_candle.at,
                        bar_index=len(candles) + pivot_idx,
                        pivot_type='LOW'
                    )

        # If we found both, we can stop scanning
        if pivot_high and pivot_low:
            break

    return pivot_high, pivot_low


def detect_order_block(candles: list[Candle], pivot: SMCPivot, bias: str) -> Optional[SMCOrderBlock]:
    """DEPRECATED: Basic order block detection - replaced by detect_order_block_enhanced().

    This function is kept for backwards compatibility but is no longer used.
    Use detect_order_block_enhanced() from smc_detection.py instead.
    """
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

    Enhanced scoring system with 6 components (0-115 total, capped at 100):

    1. ZONE PROXIMITY (0-35 points):
       - Premium/Discount depth: 25-35 points (deeper = higher)
       - Equilibrium: 15 points (neutral zone, lower score)

    2. KEY LEVEL PROXIMITY (0-30 points):
       - Within 0.5% of strong high/low: 30/20 points
       - Within 1% of strong high/low: 25/15 points
       - Within 2% of strong high/low: 20/10 points
       - Further away: 10/5 points

    3. ORDER BLOCK CONFLUENCE (0-20 points) ⭐ ENHANCED:
       - Fresh OB (not mitigated):
         * IN 50% body zone + strong (>0.7): 20 points
         * IN 50% body zone + decent (>0.5): 15 points
         * IN 50% body zone + weak: 10 points
         * IN full OB range: 5-10 points
         * NEAR OB (<0.5%): 8 * strength
       - Mitigated OBs: 0 points (ignored)

    3B. FAIR VALUE GAP CONFLUENCE (0-15 points) ⭐ NEW:
       - Unfilled FVG:
         * IN large gap (>1%): 15 points
         * IN medium gap (>0.5%): 10 points
         * IN small gap: 5 points
         * NEAR gap (<0.5%): 5-8 points
       - Filled FVGs (>80%): 0 points (ignored)

    4. STRUCTURE ALIGNMENT (0-10 points):
       - Structure matches zone bias: 10 points
       - Structure present but misaligned: 5 points

    5. RECENCY FACTOR (-5 to +15 points):
       Pivot age (market-hours aware):
         - < 2 hours: +10 points
         - < 6 hours: +7 points
         - < 1 day: +5 points
         - < 2 days: +3 points
         - < 5 days: 0 points (neutral)
         - > 5 days: -5 points (penalty)
       Zone entry age:
         - < 15 minutes: +5 points
         - < 30 minutes: +3 points
         - < 60 minutes: +1 point

    This creates meaningful differentiation:
    - Premium + Strong High + Fresh OB + FVG: 95-100 (perfect setup)
    - Discount + Strong Low + Fresh OB + FVG: 95-100 (perfect setup)
    - Premium + Weak High + Aligned OB: 70-85 (good setup)
    - Discount + Mitigated OB (ignored): 35-55 (correctly lower)
    - Equilibrium setups: 40-60 (marginal)
    - Old setups get penalized progressively
    """
    if not state.trailing_high or not state.trailing_low:
        return 0

    zones = calculate_zones(state.trailing_high, state.trailing_low)
    current_zone = get_current_zone(current_price, zones)

    if not current_zone:
        return 0

    score = 0
    range_size = state.trailing_high - state.trailing_low

    # === 1. ZONE PROXIMITY SCORING (0-35 points) ===
    # How deep into the premium/discount zone?
    if current_zone.zone_type == 'PREMIUM':
        # Higher score when deeper into premium (closer to top)
        zone_depth = (current_price - current_zone.low) / (current_zone.high - current_zone.low)
        score += int(25 + (zone_depth * 10))  # 25-35 points

    elif current_zone.zone_type == 'DISCOUNT':
        # Higher score when deeper into discount (closer to bottom)
        zone_depth = (current_zone.high - current_price) / (current_zone.high - current_zone.low)
        score += int(25 + (zone_depth * 10))  # 25-35 points

    else:  # EQUILIBRIUM
        # Lower base score for equilibrium
        score += 15  # 15 points

    # === 2. KEY LEVEL PROXIMITY (0-30 points) ===
    # Closer to strong/weak highs/lows = higher score
    proximity_bonus = 0

    if current_zone.zone_type == 'PREMIUM' and state.swing_high:
        # Distance to swing high (bearish setup)
        distance_pct = abs(current_price - state.swing_high.level) / state.swing_high.level

        if distance_pct < 0.005:  # Within 0.5%
            proximity_bonus = 30 if state.swing_high.is_strong else 20
        elif distance_pct < 0.01:  # Within 1%
            proximity_bonus = 25 if state.swing_high.is_strong else 15
        elif distance_pct < 0.02:  # Within 2%
            proximity_bonus = 20 if state.swing_high.is_strong else 10
        else:
            proximity_bonus = 10 if state.swing_high.is_strong else 5

    elif current_zone.zone_type == 'DISCOUNT' and state.swing_low:
        # Distance to swing low (bullish setup)
        distance_pct = abs(current_price - state.swing_low.level) / state.swing_low.level

        if distance_pct < 0.005:  # Within 0.5%
            proximity_bonus = 30 if state.swing_low.is_strong else 20
        elif distance_pct < 0.01:  # Within 1%
            proximity_bonus = 25 if state.swing_low.is_strong else 15
        elif distance_pct < 0.02:  # Within 2%
            proximity_bonus = 20 if state.swing_low.is_strong else 10
        else:
            proximity_bonus = 10 if state.swing_low.is_strong else 5

    score += proximity_bonus

    # === 3. ORDER BLOCK CONFLUENCE (0-20 points) ===
    # Enhanced: Uses mitigation status, strength, and 50% body zones
    ob_bonus = 0
    for ob in state.order_blocks[-5:]:  # Check last 5 order blocks
        # Skip mitigated OBs (they've been touched and are less valuable)
        if ob.mitigated:
            continue

        # Check if price is within the enhanced body zone (50% retracement)
        in_body_zone = False
        if ob.body_low is not None and ob.body_high is not None:
            in_body_zone = ob.body_low <= current_price <= ob.body_high

        if in_body_zone:
            # Price IS in the key institutional zone (50% body)
            base_score = 20 if ob.strength > 0.7 else (15 if ob.strength > 0.5 else 10)

            # Apply zone alignment multiplier
            if current_zone.zone_type == 'PREMIUM' and ob.bias == 'BEARISH':
                ob_bonus += base_score  # Perfect alignment
            elif current_zone.zone_type == 'DISCOUNT' and ob.bias == 'BULLISH':
                ob_bonus += base_score  # Perfect alignment
            else:
                ob_bonus += base_score * 0.5  # Some confluence but not aligned

        # Check if price is within the full OB range (but not body zone)
        elif ob.low <= current_price <= ob.high:
            # In OB but not at optimal 50% zone
            base_score = 10 if ob.strength > 0.6 else 5
            ob_bonus += base_score

        # Check if price is near the OB (within 0.5%)
        elif ob.low > 0:
            distance_pct = min(abs(current_price - ob.low) / current_price,
                             abs(current_price - ob.high) / current_price)
            if distance_pct < 0.005:  # Within 0.5%
                ob_bonus += 8 * ob.strength

        # Only count the best OB, don't stack
        if ob_bonus > 0:
            break

    score += min(ob_bonus, 20)  # Cap at 20 points

    # === 3B. FAIR VALUE GAP CONFLUENCE (0-15 points) ===
    # NEW: Scores unfilled FVGs (institutional price imbalances)
    fvg_bonus = 0
    if hasattr(state, 'fair_value_gaps') and state.fair_value_gaps:
        for fvg in state.fair_value_gaps[-10:]:  # Check last 10 FVGs
            # Skip filled FVGs (no longer valid)
            if fvg.filled:
                continue

            # Check if price is within the FVG
            if fvg.low <= current_price <= fvg.high:
                # Price IS in the unfilled gap - high value setup
                if fvg.gap_size_pct > 1.0:
                    base_score = 15  # Large gap (>1%)
                elif fvg.gap_size_pct > 0.5:
                    base_score = 10  # Medium gap
                else:
                    base_score = 5   # Small gap

                # Apply zone alignment bonus
                if current_zone.zone_type == 'PREMIUM' and fvg.bias == 'BEARISH':
                    fvg_bonus += base_score  # Bearish FVG in premium
                elif current_zone.zone_type == 'DISCOUNT' and fvg.bias == 'BULLISH':
                    fvg_bonus += base_score  # Bullish FVG in discount
                else:
                    fvg_bonus += base_score * 0.6  # Some value but not aligned

            # Check if price is near the FVG (within 0.5%)
            elif fvg.low > 0:
                distance_pct = min(abs(current_price - fvg.low) / current_price,
                                 abs(current_price - fvg.high) / current_price)
                if distance_pct < 0.005:  # Within 0.5%
                    fvg_bonus += 8 if fvg.gap_size_pct > 0.5 else 5

            # Only count the best FVG, don't stack
            if fvg_bonus > 0:
                break

    score += min(fvg_bonus, 15)  # Cap at 15 points

    # === 4. STRUCTURE ALIGNMENT (0-10 points) ===
    if state.structures:
        recent_structure = state.structures[-1]
        if current_zone.zone_type == 'PREMIUM' and recent_structure.bias == 'BEARISH':
            score += 10  # Bearish structure in premium
        elif current_zone.zone_type == 'DISCOUNT' and recent_structure.bias == 'BULLISH':
            score += 10  # Bullish structure in discount
        elif recent_structure.bias == 'BEARISH' or recent_structure.bias == 'BULLISH':
            score += 5  # Some structure present

    # === 5. RECENCY FACTOR (0-15 points bonus/penalty) ===
    # Recent pivots and zone entries are more valuable
    from datetime import datetime, timedelta
    now = datetime.now()
    recency_bonus = 0

    # Check pivot recency (how recently the pivot was formed)
    # Use lenient thresholds to avoid filtering good setups during non-market hours
    if current_zone.zone_type == 'PREMIUM' and state.swing_high:
        pivot_age_hours = (now - state.swing_high.time).total_seconds() / 3600  # hours
        pivot_age_days = pivot_age_hours / 24  # days

        if pivot_age_hours < 2:  # Last 2 hours - very fresh
            recency_bonus += 10
        elif pivot_age_hours < 6:  # Last 6 hours - fresh
            recency_bonus += 7
        elif pivot_age_days < 1:  # Same calendar day - recent
            recency_bonus += 5
        elif pivot_age_days < 2:  # Yesterday - still relevant
            recency_bonus += 3
        elif pivot_age_days < 5:  # Last few days - aging but OK
            recency_bonus += 0  # neutral, don't penalize
        else:
            recency_bonus -= 5  # Multiple days old - penalize

    elif current_zone.zone_type == 'DISCOUNT' and state.swing_low:
        pivot_age_hours = (now - state.swing_low.time).total_seconds() / 3600  # hours
        pivot_age_days = pivot_age_hours / 24  # days

        if pivot_age_hours < 2:  # Last 2 hours - very fresh
            recency_bonus += 10
        elif pivot_age_hours < 6:  # Last 6 hours - fresh
            recency_bonus += 7
        elif pivot_age_days < 1:  # Same calendar day - recent
            recency_bonus += 5
        elif pivot_age_days < 2:  # Yesterday - still relevant
            recency_bonus += 3
        elif pivot_age_days < 5:  # Last few days - aging but OK
            recency_bonus += 0  # neutral, don't penalize
        else:
            recency_bonus -= 5  # Multiple days old - penalize

    # Check when price entered the current zone (MORE IMPORTANT)
    if state.zone_entry_time:
        zone_entry_age = (now - state.zone_entry_time).total_seconds() / 60  # minutes
        if zone_entry_age < 15:  # Last 15 minutes - VERY fresh setup
            recency_bonus += 5
        elif zone_entry_age < 30:  # Last 30 minutes - fresh
            recency_bonus += 3
        elif zone_entry_age < 60:  # Last hour - recent
            recency_bonus += 1
        # No penalty for older zone entries - just no bonus

    score += recency_bonus

    # === FINAL SCORE ===
    # Ensure score is between 0-100
    final_score = max(0, min(score, 100))

    return final_score


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

        # Update swing pivots - ONLY update if we found a NEW pivot
        # This ensures we always have the most recent pivot available
        if swing_high:
            # Check if this is a different pivot than what we have
            is_new_pivot = (state.swing_high is None or
                           state.swing_high.time != swing_high.time or
                           state.swing_high.level != swing_high.level)

            if is_new_pivot:
                # Determine if strong or weak high compared to previous
                if state.swing_high:
                    swing_high.is_strong = swing_high.level > state.swing_high.level
                else:
                    swing_high.is_strong = True

                state.swing_high = swing_high

                # Detect order block for new pivot (enhanced with 50% body zones)
                ob = detect_order_block_enhanced(state.candles, swing_high, 'BEARISH')
                if ob:
                    state.order_blocks.append(ob)
                    if len(state.order_blocks) > 10:
                        state.order_blocks.pop(0)

        if swing_low:
            # Check if this is a different pivot than what we have
            is_new_pivot = (state.swing_low is None or
                           state.swing_low.time != swing_low.time or
                           state.swing_low.level != swing_low.level)

            if is_new_pivot:
                # Determine if strong or weak low compared to previous
                if state.swing_low:
                    swing_low.is_strong = swing_low.level < state.swing_low.level
                else:
                    swing_low.is_strong = True

                state.swing_low = swing_low

                # Detect order block for new pivot (enhanced with 50% body zones)
                ob = detect_order_block_enhanced(state.candles, swing_low, 'BULLISH')
                if ob:
                    state.order_blocks.append(ob)
                    if len(state.order_blocks) > 10:
                        state.order_blocks.pop(0)

        # Update internal pivots (these can change more frequently)
        if internal_high:
            state.internal_high = internal_high
        if internal_low:
            state.internal_low = internal_low

        # Detect Fair Value Gaps (FVG) - 3-candle price imbalances
        if len(state.candles) >= 3:
            new_fvgs = detect_fair_value_gaps(state.candles)
            if new_fvgs:
                state.fair_value_gaps = new_fvgs
                # Update fill status for all FVGs
                update_fvg_fill_status(state.fair_value_gaps, state.candles)

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

            # Update opportunity only if we have enough candles for proper analysis
            # Need 101+ candles to have detected pivots
            if len(state.candles) >= 101:
                self._update_opportunity(state, tick.price)

    def _update_opportunity(self, state: SMCSymbolState, current_price: float):
        """Calculate and update SMC opportunity for a symbol"""
        if not state.trailing_high or not state.trailing_low:
            return

        zones = calculate_zones(state.trailing_high, state.trailing_low)
        current_zone = get_current_zone(current_price, zones)

        # Track zone changes for recency scoring
        if current_zone:
            zone_type = current_zone.zone_type
            if state.current_zone_type != zone_type:
                # Zone changed - record entry time
                state.current_zone_type = zone_type
                state.zone_entry_time = datetime.now()

        # Update order block mitigation status before scoring
        if state.order_blocks:
            update_order_block_mitigation(state.order_blocks, current_price, state.candles)

        score = calculate_smc_score(state, current_price)

        # Filter out low-score opportunities
        # Lower threshold (35) to avoid filtering good setups during non-market hours
        if score < 35:
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
                if state.opportunity and state.opportunity.score >= 35:
                    opportunities.append(state.opportunity)

            # Sort by score descending
            opportunities.sort(key=lambda x: x.score, reverse=True)
            return opportunities

    def get_state(self, symbol: str) -> Optional[SMCSymbolState]:
        """Get SMC state for a specific symbol"""
        with self.lock:
            return self.states.get(symbol)
