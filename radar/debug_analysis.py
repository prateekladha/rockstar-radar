"""Debug single-stock SMC analysis — fetch historical data and run SMC engine for one symbol."""
from __future__ import annotations
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from .fyers import FyersAdapter
from .models import Candle, Instrument, Tick
from .selecting import normalize_morning_symbol
from .service import baseline_history, signal_bar_minutes
from .smc_engine import SMCEngine, calculate_smc_score_with_breakdown
from .utils import ROOT, market_dt, now_ist
from .prerequisites import PrerequisiteChecker, PrerequisiteConfig


def debug_cache_path(symbol: str, day: date, bar_minutes: int = 5) -> Path:
    """Path for debug cache file (per symbol, per day, per resolution)."""
    # Clean symbol name for filesystem
    clean_symbol = symbol.replace('NSE:', '').replace('-EQ', '').replace(':', '_')
    debug_dir = ROOT / 'data' / 'debug'
    debug_dir.mkdir(parents=True, exist_ok=True)
    return debug_dir / f'{clean_symbol}_{day.isoformat()}_{int(bar_minutes)}m.json'


def analyze_single_stock(adapter: FyersAdapter, symbol_input: str, config: dict,
                         force: bool = False, prereq_config: Optional[PrerequisiteConfig] = None) -> dict:
    """Fetch historical data and run SMC analysis for a single stock.

    Args:
        adapter: FYERS adapter for API calls
        symbol_input: User input (e.g., "RELIANCE", "TCS", "NSE:INFY-EQ")
        config: Radar config
        force: If True, refetch even if cache exists

    Returns:
        Dict with status, opportunity, and metadata
    """
    today = now_ist().date()
    bar_minutes = signal_bar_minutes(config)
    resolution = str(bar_minutes)

    # Normalize symbol to FYERS format
    try:
        symbol = normalize_morning_symbol(symbol_input)
    except Exception as e:
        return {
            'success': False,
            'error': f'Invalid symbol: {symbol_input}',
            'message': str(e)
        }

    cache_path = debug_cache_path(symbol, today, bar_minutes)

    # Check cache first (unless force=True)
    if cache_path.exists() and not force:
        try:
            cached_data = json.loads(cache_path.read_text(encoding='utf-8'))
            print(f'[Debug] Loading {symbol} from cache: {cache_path.name}')

            # Reconstruct candles from cache
            candles = [
                Candle(
                    at=datetime.fromisoformat(c['at']),
                    open=c['open'],
                    high=c['high'],
                    low=c['low'],
                    close=c['close'],
                    volume=c['volume']
                )
                for c in cached_data['candles']
            ]

            return _run_smc_analysis(symbol, candles, config, prereq_config, from_cache=True)

        except Exception as e:
            print(f'[Debug] Cache load failed: {type(e).__name__}: {e}')
            # Fall through to fetch

    # Fetch from FYERS API
    print(f'[Debug] Fetching historical data for {symbol}...')
    from_dt = market_dt(today - timedelta(days=5), '09:15')
    to_dt = market_dt(today, '15:30')

    try:
        candles = baseline_history(adapter, symbol, resolution, from_dt, to_dt)

        if not candles:
            return {
                'success': False,
                'error': 'No data available',
                'message': f'No historical data found for {symbol}'
            }

        # Cache the fetched data
        cache_data = {
            'symbol': symbol,
            'fetched_at': now_ist().isoformat(),
            'date': today.isoformat(),
            'resolution': bar_minutes,
            'candles': [
                {
                    'at': c.at.isoformat(),
                    'open': c.open,
                    'high': c.high,
                    'low': c.low,
                    'close': c.close,
                    'volume': c.volume
                }
                for c in candles
            ]
        }

        cache_path.write_text(json.dumps(cache_data, indent=2), encoding='utf-8')
        print(f'[Debug] Cached data to: {cache_path.name}')

        return _run_smc_analysis(symbol, candles, config, prereq_config, from_cache=False)

    except Exception as e:
        return {
            'success': False,
            'error': 'Fetch failed',
            'message': f'{type(e).__name__}: {e}'
        }


def _run_smc_analysis(symbol: str, candles: list[Candle], config: dict,
                     prereq_config: Optional[PrerequisiteConfig] = None,
                     from_cache: bool = False) -> dict:
    """Run SMC engine analysis on historical candles."""
    if len(candles) < 101:
        return {
            'success': False,
            'error': 'Insufficient data',
            'message': f'Only {len(candles)} candles available. Need at least 101 for swing detection.'
        }

    # Create a minimal instrument for this symbol
    instrument = Instrument(
        symbol=symbol
    )

    # Initialize SMC engine with single stock
    smc_engine = SMCEngine([instrument], config)

    # Load historical candles
    smc_engine.load_historical_candles(symbol, candles)

    # Get current price (last candle close)
    current_price = candles[-1].close

    # Simulate a tick to trigger opportunity calculation
    tick = Tick(
        symbol=symbol,
        price=current_price,
        time=candles[-1].at,
        daily_volume=sum(c.volume for c in candles[-50:])  # Approx daily volume
    )
    smc_engine.process_tick(symbol, tick)

    # Get the state and opportunity
    state = smc_engine.get_state(symbol)

    if not state:
        return {
            'success': False,
            'error': 'Analysis failed',
            'message': 'Could not analyze symbol'
        }

    # PRE-REQUISITE CHECKS (run before strategy evaluation)
    prereq_result = None
    if prereq_config:
        # Calculate RVOL for prerequisite check
        # Use same logic as ORB radar: compare current bar volume to historical baseline
        from .engine import same_time_baseline
        today = now_ist().date()

        # Build baseline from historical data
        baseline_dict = same_time_baseline(candles, today, lookback_sessions=20)
        current_time_key = candles[-1].at.strftime('%H:%M')
        baseline_volume = baseline_dict.get(current_time_key)

        # Calculate RVOL
        rvol = None
        if baseline_volume and baseline_volume > 0:
            rvol = candles[-1].volume / baseline_volume

        # Run prerequisite check
        checker = PrerequisiteChecker(prereq_config)
        prereq_result = checker.check(symbol, {
            'rvol': rvol,
            'price': current_price,
            'liquidity_cr': getattr(state.instrument, 'median_turnover_cr', None) if hasattr(state, 'instrument') else None
        })

        # If prerequisites fail, return early with error
        if not prereq_result.passed:
            return {
                'success': False,
                'error': 'Pre-requisite checks failed',
                'message': prereq_result.error_message,
                'failed_checks': prereq_result.failed_checks,
                'prereq_details': prereq_result.details,
                'symbol': symbol,
                'current_price': current_price,
                'rvol': rvol
            }

    # Build response
    opportunity = state.opportunity

    # Calculate score breakdown for detailed analysis
    score, breakdown = calculate_smc_score_with_breakdown(state, current_price)

    result = {
        'success': True,
        'symbol': symbol,
        'from_cache': from_cache,
        'candles_count': len(candles),
        'current_price': current_price,
        'trailing_high': state.trailing_high,
        'trailing_low': state.trailing_low,
        'atr': state.atr,
        'trend': state.trend,
        'score_breakdown': breakdown,  # Add detailed score breakdown
    }

    if opportunity:
        result['opportunity'] = {
            'symbol': opportunity.symbol,
            'price': opportunity.price,
            'score': opportunity.score,
            'zone': opportunity.zone.zone_type if opportunity.zone else None,
            'strong_high': opportunity.strong_high,
            'strong_low': opportunity.strong_low,
            'weak_high': opportunity.weak_high,
            'weak_low': opportunity.weak_low,
            'recent_structure': (
                f'{opportunity.recent_structure.bias} {opportunity.recent_structure.structure_type}'
                if opportunity.recent_structure else None
            ),
            'note': opportunity.note,
            'time': opportunity.time.isoformat() if opportunity.time else None
        }
    else:
        result['opportunity'] = None
        result['message'] = 'No opportunity found (score < 40 or insufficient confluence)'

    # Add pivot information
    if state.swing_high:
        result['swing_high'] = {
            'level': state.swing_high.level,
            'is_strong': state.swing_high.is_strong,
            'time': state.swing_high.time.isoformat()
        }

    if state.swing_low:
        result['swing_low'] = {
            'level': state.swing_low.level,
            'is_strong': state.swing_low.is_strong,
            'time': state.swing_low.time.isoformat()
        }

    return result
