"""Enhanced SMC detection logic for Order Blocks and Fair Value Gaps.

Implements institutional-grade OB and FVG detection with:
- Proper last-candle identification for OBs
- Body-based OB zones (50% retracement)
- Mitigation tracking
- FVG detection and fill tracking
"""
from __future__ import annotations
from typing import Optional
from datetime import datetime

from .models import Candle, SMCOrderBlock, SMCFairValueGap, SMCPivot


def detect_order_block_enhanced(candles: list[Candle], pivot: SMCPivot, bias: str) -> Optional[SMCOrderBlock]:
    """Enhanced order block detection using proper SMC methodology.

    Key improvements:
    1. Finds last opposite-direction candle before breakout (not just previous candle)
    2. Uses 50% of candle body as the OB zone (institutional retracement level)
    3. Validates candle strength (body > 40% of range)
    4. Calculates strength score based on candle quality

    Args:
        candles: Historical candles
        pivot: The swing pivot point
        bias: 'BULLISH' or 'BEARISH' - direction of expected move FROM the OB

    Returns:
        Enhanced SMCOrderBlock or None
    """
    if len(candles) < 5:
        return None

    # Find the pivot candle
    pivot_idx = None
    for i, candle in enumerate(candles):
        if abs((candle.at - pivot.time).total_seconds()) < 300:  # Within 5 minutes
            pivot_idx = i
            break

    if pivot_idx is None or pivot_idx < 2:
        return None

    # Search backwards from pivot to find last opposite-direction candle
    # For bullish OB: find last bearish candle before bullish breakout
    # For bearish OB: find last bullish candle before bearish breakout

    ob_candle_idx = None
    for i in range(pivot_idx - 1, max(0, pivot_idx - 10), -1):
        candle = candles[i]

        # Calculate candle properties
        candle_range = candle.high - candle.low
        if candle_range == 0:
            continue

        candle_body = abs(candle.close - candle.open)
        body_ratio = candle_body / candle_range

        # Check if this is an opposite-direction candle with decent body
        if bias == 'BULLISH':
            # Looking for last bearish candle (close < open)
            if candle.close < candle.open and body_ratio > 0.4:
                ob_candle_idx = i
                break
        else:  # BEARISH
            # Looking for last bullish candle (close > open)
            if candle.close > candle.open and body_ratio > 0.4:
                ob_candle_idx = i
                break

    # Fallback: if no suitable candle found, use candle before pivot
    if ob_candle_idx is None:
        ob_candle_idx = pivot_idx - 1

    ob_candle = candles[ob_candle_idx]

    # Calculate candle metrics
    candle_range = ob_candle.high - ob_candle.low
    candle_body = abs(ob_candle.close - ob_candle.open)
    body_ratio = candle_body / candle_range if candle_range > 0 else 0

    # Calculate 50% retracement level of the body (key institutional level)
    if bias == 'BULLISH':
        # For bullish OB (bearish candle), we care about the low half
        body_high = max(ob_candle.open, ob_candle.close)
        body_low = ob_candle.low
        mid_body = body_low + ((body_high - body_low) * 0.5)
    else:  # BEARISH
        # For bearish OB (bullish candle), we care about the high half
        body_low = min(ob_candle.open, ob_candle.close)
        body_high = ob_candle.high
        mid_body = body_low + ((body_high - body_low) * 0.5)

    # Calculate OB strength (0-1)
    strength = body_ratio * 0.7  # Body ratio is 70% of strength

    # Add 30% for candle size relative to recent ATR (if significant)
    if len(candles) > ob_candle_idx + 14:
        recent_candles = candles[max(0, ob_candle_idx - 14):ob_candle_idx]
        if recent_candles:
            avg_range = sum(c.high - c.low for c in recent_candles) / len(recent_candles)
            if avg_range > 0:
                size_ratio = min(candle_range / avg_range, 2.0) / 2.0  # Cap at 2x average
                strength += size_ratio * 0.3

    strength = min(strength, 1.0)  # Cap at 1.0

    return SMCOrderBlock(
        high=ob_candle.high,
        low=ob_candle.low,
        body_high=mid_body if bias == 'BULLISH' else body_high,
        body_low=body_low if bias == 'BEARISH' else mid_body,
        time=ob_candle.at,
        bias=bias,
        block_type='SWING',
        strength=strength,
        mitigated=False,
        touch_count=0
    )


def detect_fair_value_gaps(candles: list[Candle]) -> list[SMCFairValueGap]:
    """Detect Fair Value Gaps (FVG) - 3-candle price imbalances.

    FVG occurs when there's a gap between candle[0] and candle[2]:
    - Bullish FVG: candle[0].high < candle[2].low (gap up, unfilled demand)
    - Bearish FVG: candle[0].low > candle[2].high (gap down, unfilled supply)

    Returns:
        List of detected FVGs (most recent 20)
    """
    if len(candles) < 3:
        return []

    fvgs = []

    # Scan through recent candles looking for 3-candle FVG patterns
    for i in range(len(candles) - 2):
        candle_0 = candles[i]
        candle_1 = candles[i + 1]  # Middle candle (creates the gap)
        candle_2 = candles[i + 2]

        # Bullish FVG: gap between candle[0] high and candle[2] low
        if candle_0.high < candle_2.low:
            gap_high = candle_2.low
            gap_low = candle_0.high
            gap_size = gap_high - gap_low
            gap_size_pct = (gap_size / candle_2.low) * 100

            # Only consider significant gaps (> 0.1%)
            if gap_size_pct > 0.1:
                fvg = SMCFairValueGap(
                    high=gap_high,
                    low=gap_low,
                    time=candle_1.at,  # Gap formed by middle candle
                    bias='BULLISH',
                    gap_size_pct=gap_size_pct,
                    filled=False,
                    fill_percentage=0.0
                )
                fvgs.append(fvg)

        # Bearish FVG: gap between candle_2] high and candle[0] low
        elif candle_0.low > candle_2.high:
            gap_high = candle_0.low
            gap_low = candle_2.high
            gap_size = gap_high - gap_low
            gap_size_pct = (gap_size / candle_0.low) * 100

            # Only consider significant gaps (> 0.1%)
            if gap_size_pct > 0.1:
                fvg = SMCFairValueGap(
                    high=gap_high,
                    low=gap_low,
                    time=candle_1.at,  # Gap formed by middle candle
                    bias='BEARISH',
                    gap_size_pct=gap_size_pct,
                    filled=False,
                    fill_percentage=0.0
                )
                fvgs.append(fvg)

    # Return most recent 20 FVGs
    return fvgs[-20:] if len(fvgs) > 20 else fvgs


def update_order_block_mitigation(order_blocks: list[SMCOrderBlock], current_price: float,
                                   candles: list[Candle]) -> None:
    """Update mitigation status for order blocks.

    An OB is mitigated when price returns to it and trades through the 50% level.
    Mitigated OBs are less valuable for future reactions.

    Args:
        order_blocks: List of tracked order blocks
        current_price: Current market price
        candles: Recent candles for checking touches
    """
    if not candles:
        return

    recent_candles = candles[-20:]  # Check last 20 candles for touches

    for ob in order_blocks:
        if ob.mitigated:
            continue  # Already mitigated, skip

        # Check if price has touched the OB body zone
        for candle in recent_candles:
            # For bullish OB, check if price traded down into it
            if ob.bias == 'BULLISH' and ob.body_low and ob.body_high:
                if candle.low <= ob.body_high:
                    ob.touch_count += 1
                    # Mitigated if price traded through 50% of body
                    if candle.low <= ob.body_low:
                        ob.mitigated = True
                        break

            # For bearish OB, check if price traded up into it
            elif ob.bias == 'BEARISH' and ob.body_low and ob.body_high:
                if candle.high >= ob.body_low:
                    ob.touch_count += 1
                    # Mitigated if price traded through 50% of body
                    if candle.high >= ob.body_high:
                        ob.mitigated = True
                        break


def update_fvg_fill_status(fvgs: list[SMCFairValueGap], candles: list[Candle]) -> None:
    """Update fill status for Fair Value Gaps.

    A FVG is filled when price returns and trades through it.
    Filled FVGs are less valuable for future opportunities.

    Args:
        fvgs: List of tracked FVGs
        candles: Recent candles for checking fills
    """
    if not candles:
        return

    recent_candles = candles[-50:]  # Check last 50 candles

    for fvg in fvgs:
        if fvg.filled:
            continue  # Already filled, skip

        gap_size = fvg.high - fvg.low

        for candle in recent_candles:
            # Only check candles after the FVG was formed
            if candle.at <= fvg.time:
                continue

            # For bullish FVG, check if price returned down into gap
            if fvg.bias == 'BULLISH':
                if candle.low <= fvg.high:
                    # Calculate how much of gap is filled
                    filled_amount = min(fvg.high - candle.low, gap_size)
                    fill_pct = (filled_amount / gap_size) * 100
                    fvg.fill_percentage = max(fvg.fill_percentage, fill_pct)

                    # Consider filled if > 80% is filled
                    if fill_pct >= 80:
                        fvg.filled = True
                        break

            # For bearish FVG, check if price returned up into gap
            elif fvg.bias == 'BEARISH':
                if candle.high >= fvg.low:
                    # Calculate how much of gap is filled
                    filled_amount = min(candle.high - fvg.low, gap_size)
                    fill_pct = (filled_amount / gap_size) * 100
                    fvg.fill_percentage = max(fvg.fill_percentage, fill_pct)

                    # Consider filled if > 80% is filled
                    if fill_pct >= 80:
                        fvg.filled = True
                        break
