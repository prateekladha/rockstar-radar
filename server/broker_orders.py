"""Live order placement on the user's own broker (FYERS). Paper mode never reaches this module.

Safeguards live in the caller (server/routers/trading.py): own-broker required, risk-limit enforced,
user opt-in to live mode, and per-order confirmation. This module just translates a confirmed ticket
into a FYERS order and reports the result.
"""
from __future__ import annotations


class OrderError(RuntimeError):
    pass


def place_live_order(app_id: str, access_token: str, *, symbol: str, side: str, qty: int,
                     entry: float, stop: float | None, target: float | None,
                     order_type: str = 'limit') -> str:
    """Place an INTRADAY order on FYERS with bracket SL/target offsets. Returns the broker order id.
    Raises OrderError on rejection."""
    from fyers_apiv3 import fyersModel
    fy = fyersModel.FyersModel(client_id=app_id, token=f'{app_id}:{access_token}',
                               is_async=False, log_path='')
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
