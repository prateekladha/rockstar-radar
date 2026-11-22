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
                         force: bool = False, prereq_config: Optional[PrerequisiteConfig] = None,
                         rvol_cfg=None, ema_cfg=None) -> dict:
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

            return _run_smc_analysis(symbol, candles, config, prereq_config, from_cache=True,
                                     rvol_cfg=rvol_cfg, ema_cfg=ema_cfg)

        except Exception as e:
            print(f'[Debug] Cache load failed: {type(e).__name__}: {e}')
            # Fall through to fetch

    # Fetch from FYERS API.
    # RVOL's same_time_baseline needs >=10 prior sessions (ideally ~20, matching its
    # lookback_sessions default) before it returns ANY baseline — otherwise baseline_volume is
    # None, RVOL is None, and the prerequisite check fails for every symbol. A 5-day window only
    # covers ~3 trading sessions, so fetch ~40 calendar days (~20 sessions after weekends/holidays).
    print(f'[Debug] Fetching historical data for {symbol}...')
    from_dt = market_dt(today - timedelta(days=40), '09:15')
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

        return _run_smc_analysis(symbol, candles, config, prereq_config, from_cache=False,
                                 rvol_cfg=rvol_cfg, ema_cfg=ema_cfg)

    except Exception as e:
        return {
            'success': False,
            'error': 'Fetch failed',
            'message': f'{type(e).__name__}: {e}'
        }


def _orb_status(symbol: str, candles: list[Candle], config: dict) -> dict:
    """Replay the latest session's bars through the REAL ORB RadarEngine and report its final state.

    Builds the instrument context (prior-session support/resistance + daily ATR%) and the RVOL
    baseline from the fetched history, then feeds the latest session's 5m bars (the same bar-driven
    path the backtest uses to reach CONFIRMED/RETEST_READY). Returns the engine's resulting ORB stage
    and levels. Best-effort: any failure yields {'available': False, 'reason': ...} so the rest of the
    Debug analysis is unaffected.
    """
    from collections import defaultdict
    try:
        from .engine import RadarEngine
        from .rvol import build_baseline, RvolConfig

        by_day: dict = defaultdict(list)
        for c in candles:
            if c.at.hour in range(9, 16):
                by_day[c.at.date()].append(c)
        days = sorted(by_day)
        if len(days) < 11:
            return {'available': False, 'reason': 'Needs ≥10 prior sessions for ORB context.'}
        day = days[-1]
        prior = days[:-1]
        daily = {}
        for d in days:
            cs = sorted(by_day[d], key=lambda x: x.at)
            daily[d] = (cs[0].open, max(x.high for x in cs), min(x.low for x in cs), cs[-1].close)
        dl = [daily[d] for d in prior]
        trs = [max(dl[i][1] - dl[i][2], abs(dl[i][1] - dl[i - 1][3]), abs(dl[i][2] - dl[i - 1][3]))
               for i in range(1, len(dl))]
        atr = (sum(trs[-14:]) / min(14, len(trs))) if trs else 0.0
        last_close = dl[-1][3]
        atr_pct = (atr / last_close * 100) if last_close else 0.0
        pd20 = [daily[d] for d in prior[-20:]]
        turns = sorted(sum(x.close * x.volume for x in by_day[d]) / 1e7 for d in prior[-20:])
        med_turn = turns[len(turns) // 2] if turns else 0.0

        inst = Instrument(symbol=symbol, daily_atr_pct=atr_pct, previous_close=daily[prior[-1]][3],
                          resistance=sorted(x[1] for x in pd20), support=sorted(x[2] for x in pd20),
                          median_turnover_cr=med_turn)
        eng = RadarEngine([inst], config, session=day, mode='SIM')
        eng.set_baseline(symbol, build_baseline(candles, day, RvolConfig.from_config(config).length))
        session_bars = sorted(by_day[day], key=lambda x: x.at)
        for bar in session_bars:
            eng.ingest_closed_bar(symbol, bar)

        st = eng.states[symbol]
        op = st.opening
        # A bar-only replay that never breaks out leaves the initial WAIT_OR; label it clearly.
        no_breakout = st.state in ('WAIT_OR', 'NONE')
        return {
            'available': True,
            'session': day.isoformat(),
            'state': 'NO_BREAKOUT' if (no_breakout and op) else st.state,
            'or_formed': bool(op),
            'or_high': round(op.high, 2) if op else None,
            'or_low': round(op.low, 2) if op else None,
            'side': st.side or None,
            'score': st.score,
            'rvol': round(st.rvol, 2) if st.rvol is not None else None,
            'vwap': round(st.vwap, 2) if st.vwap else None,
            'entry': round(st.entry, 2) if st.entry else None,
            'stop': round(st.stop, 2) if st.stop else None,
            'target': round(st.target, 2) if st.target else None,
            'net_rr': round(st.net_rr, 2) if st.net_rr else None,
            'reason': st.reason or ('Opening range formed; no 5-minute close beyond it.'
                                    if (no_breakout and op) else ''),
        }
    except Exception as e:
        return {'available': False, 'reason': f'{type(e).__name__}: {e}'}


def _run_smc_analysis(symbol: str, candles: list[Candle], config: dict,
                     prereq_config: Optional[PrerequisiteConfig] = None,
                     from_cache: bool = False, rvol_cfg=None, ema_cfg=None) -> dict:
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
        # RVOL via the ONE product-wide metric (radar.rvol), in the user's configured mode/length,
        # over the FULL fetched history — so the Debug tab and the live radar report the same number.
        from .rvol import RvolConfig, rvol_from_candles
        rvol = rvol_from_candles(rvol_cfg or RvolConfig.from_config(config), candles)

        # Run prerequisite check
        checker = PrerequisiteChecker(prereq_config)
        prereq_result = checker.check(symbol, {
            'rvol': rvol,
            'price': current_price,
            'liquidity_cr': getattr(state.instrument, 'median_turnover_cr', None) if hasattr(state, 'instrument') else None
        })

        # If prerequisites fail, return early with error. Include from_cache + the RVOL mode so the
        # UI can still offer Refetch (force a fresh pull) and show WHY it failed — otherwise a stale
        # cache that fails the gate traps the user with no way to refresh.
        if not prereq_result.passed:
            cfg = rvol_cfg or RvolConfig.from_config(config)
            return {
                'success': False,
                'error': 'Pre-requisite checks failed',
                'message': prereq_result.error_message,
                'failed_checks': prereq_result.failed_checks,
                'prereq_details': prereq_result.details,
                'symbol': symbol,
                'current_price': current_price,
                'rvol': rvol,
                'rvol_mode': cfg.mode,
                'candles_count': len(candles),
                'from_cache': from_cache,
            }

    # Build response
    opportunity = state.opportunity

    # Calculate score breakdown for detailed analysis
    score, breakdown = calculate_smc_score_with_breakdown(state, current_price)

    # EMA crossover trend, per the user's EMA settings (fast/slow length, source, offset). Gated
    # behind the prerequisite checks (RVOL) like the rest of strategy evaluation — we only reach here
    # when the prereq passed (a failure returns early above).
    from .indicators import ema_cross
    ec = ema_cfg or {}
    fast = int(ec.get('fast_length', 5) or 5)
    slow = int(ec.get('slow_length', 20) or 20)
    source = (ec.get('source') or 'close').lower()
    offset = int(ec.get('offset', 0) or 0)
    _src = {
        'close': lambda c: c.close, 'open': lambda c: c.open,
        'high': lambda c: c.high, 'low': lambda c: c.low,
        'hl2': lambda c: (c.high + c.low) / 2,
        'hlc3': lambda c: (c.high + c.low + c.close) / 3,
        'ohlc4': lambda c: (c.open + c.high + c.low + c.close) / 4,
    }.get(source, lambda c: c.close)
    ema_info = ema_cross([_src(c) for c in candles], fast, slow, offset)
    ema_info['source'] = source

    # ORB status — replay the latest session through the real ORB engine (gated behind prereqs too).
    # Use the user's RVOL mode/length so the ORB RVOL + gates match their live radar.
    orb_cfg = dict(config)
    if rvol_cfg is not None:
        orb_cfg['rvol_mode'] = rvol_cfg.mode
        orb_cfg['rvol_length'] = rvol_cfg.length
    orb_info = _orb_status(symbol, candles, orb_cfg)

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
        'ema': ema_info,               # EMA 5 / EMA 20 crossover trend (only when prereqs pass)
        'orb': orb_info,               # ORB engine status for the latest session (only when prereqs pass)
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
