"""Live order placement on the user's own broker (FYERS). Paper mode never reaches this module.

Safeguards live in the caller (server/routers/trading.py): own-broker required, risk-limit enforced,
user opt-in to live mode, and per-order confirmation. This module just translates a confirmed ticket
into a FYERS order and reports the result.
"""
from __future__ import annotations

import tempfile

# The FYERS SDK writes fyersApi.log into log_path (falling back to the process CWD when empty). In the
# web pod the CWD is /app, which the non-root container user cannot write, so an empty log_path raises
# PermissionError at client construction and breaks every live-order/broker call. Point it at the temp
# dir, which is always writable.
_FYERS_LOG_DIR = tempfile.gettempdir()


class OrderError(RuntimeError):
    pass


def place_live_order(app_id: str, access_token: str, *, symbol: str, side: str, qty: int,
                     entry: float, stop: float | None, target: float | None,
                     order_type: str = 'limit') -> str:
    """Place an INTRADAY order on FYERS with bracket SL/target offsets. Returns the broker order id.
    Raises OrderError on rejection."""
    from fyers_apiv3 import fyersModel
    fy = fyersModel.FyersModel(client_id=app_id, token=f'{app_id}:{access_token}',
                               is_async=False, log_path=_FYERS_LOG_DIR)
    data = {
        'symbol': symbol,
        'qty': int(qty),
        'type': 1 if order_type == 'limit' else 2,   # 1 = limit, 2 = market
        'side': 1 if side == 'LONG' else -1,          # 1 buy, -1 sell
        'productType': 'INTRADAY',
        'limitPrice': float(entry) if order_type == 'limit' else 0,
        'stopPrice': 0,
        'validity': 'DAY',
        'disclosedQty': 0,
        'offlineOrder': False,
    }
    # FYERS takes SL/target as OFFSETS from entry (bracket legs).
    if stop:
        data['stopLoss'] = round(abs(float(entry) - float(stop)), 2)
    if target:
        data['takeProfit'] = round(abs(float(target) - float(entry)), 2)
    try:
        resp = fy.place_order(data)
    except Exception as e:
        raise OrderError(f'{type(e).__name__}: {e}'[:160]) from e
    if not isinstance(resp, dict) or resp.get('s') != 'ok' or not resp.get('id'):
        raise OrderError(str((resp or {}).get('message', 'Broker rejected the order'))[:160])
    return str(resp['id'])


def _model(app_id: str, access_token: str):
    from fyers_apiv3 import fyersModel
    return fyersModel.FyersModel(client_id=app_id, token=f'{app_id}:{access_token}',
                                 is_async=False, log_path=_FYERS_LOG_DIR)


# FYERS order status codes.
_FY_STATUS = {1: 'cancelled', 2: 'filled', 4: 'pending', 5: 'rejected', 6: 'pending'}


def fetch_orderbook(app_id: str, access_token: str) -> dict:
    """{broker_order_id -> {status, traded_price}} for the day. Read-only."""
    try:
        resp = _model(app_id, access_token).orderbook()
    except Exception as e:
        raise OrderError(f'{type(e).__name__}: {e}'[:160]) from e
    if not isinstance(resp, dict) or resp.get('s') != 'ok':
        raise OrderError(str((resp or {}).get('message', 'orderbook failed'))[:160])
    out = {}
    for o in (resp.get('orderBook') or []):
        oid = str(o.get('id') or '')
        if not oid:
            continue
        out[oid] = {'status': _FY_STATUS.get(o.get('status'), 'pending'),
                    'traded_price': o.get('tradedPrice') or o.get('tradePrice') or None}
    return out


def fetch_positions(app_id: str, access_token: str) -> dict:
    """{bare symbol -> {net_qty, last_price}} from net positions. Read-only."""
    try:
        resp = _model(app_id, access_token).positions()
    except Exception as e:
        raise OrderError(f'{type(e).__name__}: {e}'[:160]) from e
    if not isinstance(resp, dict) or resp.get('s') != 'ok':
        raise OrderError(str((resp or {}).get('message', 'positions failed'))[:160])
    out = {}
    for p in (resp.get('netPositions') or []):
        sym = (p.get('symbol') or '').replace('NSE:', '').replace('-EQ', '')
        if sym:
            out[sym] = {'net_qty': p.get('netQty', p.get('qty', 0)), 'last_price': p.get('ltp')}
    return out


def fetch_funds(app_id: str, access_token: str) -> float:
    """Available trading balance (₹) from the broker, for live position sizing + eligibility.
    Returns the usable cash; raises OrderError if the broker call fails."""
    try:
        resp = _model(app_id, access_token).funds()
    except Exception as e:
        raise OrderError(f'{type(e).__name__}: {e}'[:160]) from e
    if not isinstance(resp, dict) or resp.get('s') != 'ok':
        raise OrderError(str((resp or {}).get('message', 'funds lookup failed'))[:160])
    rows = resp.get('fund_limit') or []
    avail = clear = None
    for r in rows:
        title = (r.get('title') or '').lower()
        amt = r.get('equityAmount', r.get('amount'))
        if amt is None:
            continue
        if 'available' in title:
            avail = float(amt)
        elif 'clear' in title:
            clear = float(amt)
    val = avail if avail is not None else clear
    if val is None:
        raise OrderError('Could not read available balance from the broker.')
    return round(float(val), 2)


def fetch_order_margin(app_id: str, access_token: str, *, symbol: str, qty: int, side: str,
                       product: str = 'INTRADAY') -> dict:
    """Real broker margin for ONE intraday order, via the FYERS Multi-order Margin Calculator.

    This is the *actual* per-stock INTRADAY margin (so leverage/eligibility come from FYERS, not a
    made-up multiplier). The calculator is NOT wrapped in the Python SDK, so we call the v3 REST
    endpoint directly with the same ``{app_id}:{access_token}`` auth the SDK uses.
    Returns {'margin_total': ₹ this order needs, 'margin_avail': ₹ available balance}.
    Raises OrderError on any failure — the caller skips the trade (we never trade on an unknown pool).

    Note (documented FYERS behaviour): the calculator does not validate product eligibility, so a
    non-MIS stock still returns an INTRADAY margin. We approximate eligibility via the implied
    leverage (notional / margin_total) in the caller — see docs/PAPER_LIVE_PARITY.md."""
    import requests
    url = 'https://api-t1.fyers.in/api/v3/multiorder/margin'
    body = {'data': [{
        'symbol': symbol, 'qty': int(qty), 'side': 1 if side == 'LONG' else -1, 'type': 2,
        'productType': product, 'limitPrice': 0.0, 'stopPrice': 0.0, 'stopLoss': 0.0, 'takeProfit': 0.0,
    }]}
    try:
        resp = requests.post(url, json=body, timeout=8, headers={
            'Authorization': f'{app_id}:{access_token}', 'Content-Type': 'application/json'})
        j = resp.json()
    except Exception as e:
        raise OrderError(f'{type(e).__name__}: {e}'[:160]) from e
    if not isinstance(j, dict) or j.get('s') != 'ok':
        raise OrderError(str((j or {}).get('message', 'margin lookup failed'))[:160])
    d = j.get('data') or {}
    mt, ma = d.get('margin_total'), d.get('margin_avail')
    if mt is None or ma is None:
        raise OrderError('margin response missing margin_total/margin_avail')
    return {'margin_total': round(float(mt), 2), 'margin_avail': round(float(ma), 2)}


def cancel_live_order(app_id: str, access_token: str, broker_order_id: str) -> None:
    """Cancel a working order at the broker. User-initiated only."""
    try:
        resp = _model(app_id, access_token).cancel_order({'id': broker_order_id})
    except Exception as e:
        raise OrderError(f'{type(e).__name__}: {e}'[:160]) from e
    if not isinstance(resp, dict) or resp.get('s') != 'ok':
        raise OrderError(str((resp or {}).get('message', 'Broker rejected the cancel'))[:160])


def square_off_live(app_id: str, access_token: str, *, symbol: str, side: str, qty: int) -> str:
    """Exit a live position with an opposite MARKET order. User-initiated only (manual Close)."""
    fy = _model(app_id, access_token)
    data = {'symbol': symbol, 'qty': int(qty), 'type': 2,            # market
            'side': -1 if side == 'LONG' else 1,                     # opposite of the entry
            'productType': 'INTRADAY', 'limitPrice': 0, 'stopPrice': 0,
            'validity': 'DAY', 'disclosedQty': 0, 'offlineOrder': False}
    try:
        resp = fy.place_order(data)
    except Exception as e:
        raise OrderError(f'{type(e).__name__}: {e}'[:160]) from e
    if not isinstance(resp, dict) or resp.get('s') != 'ok' or not resp.get('id'):
        raise OrderError(str((resp or {}).get('message', 'Broker rejected the square-off'))[:160])
    return str(resp['id'])
