"""Per-trade feature + outcome logging (Phase 2 plumbing).

At entry we stash the confluence signals/score on the Order (`features`, JSON). At exit the Order
already carries the outcome (pnl, result_r). Pairing the two gives a clean training table to
RE-WEIGHT the confluence score later on real results — the honest "learning" (NOT per-tick ML).

`feature_row` is a PURE extractor (no DB) so it's unit-testable; `record_features` / `export_training_rows`
are thin DB helpers around it.
"""
from __future__ import annotations

import json
from typing import Optional


def record_features(order, payload: dict) -> None:
    """Attach the entry-time confluence payload (signals + score + components) to the order."""
    try:
        order.features = json.dumps(payload, default=float)
    except (TypeError, ValueError):
        order.features = None


def feature_row(order) -> Optional[dict]:
    """A flat training row from a CLOSED order that has features, else None.

    Returns the logged features merged with the realised outcome:
      {..features.., 'pnl', 'result_r', 'won'(bool), 'symbol', 'side', 'source'}.
    Pure: `order` may be any object with these attributes (ORM row or a stub).
    """
    raw = getattr(order, 'features', None)
    if not raw or getattr(order, 'status', None) != 'closed':
        return None
    try:
        feats = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(feats, dict):
        return None
    pnl = getattr(order, 'pnl', None)
    row = dict(feats)
    row.update({
        'symbol': getattr(order, 'symbol', None),
        'side': getattr(order, 'side', None),
        'source': getattr(order, 'source', None),
        'pnl': pnl,
        'result_r': getattr(order, 'result_r', None),
        'won': (pnl is not None and pnl > 0),
    })
    return row


def export_training_rows(db, sources=('auto', 'auto_smc')) -> list[dict]:
    """All closed auto-trade rows that have logged features — the re-weighting training set."""
    from .models import Order   # lazy: keeps feature_row/record_features importable without SQLAlchemy
    q = (db.query(Order)
         .filter(Order.status == 'closed', Order.features.isnot(None),
                 Order.source.in_(tuple(sources)))
         .order_by(Order.closed_at.asc()))
    rows = []
    for o in q.all():
        r = feature_row(o)
        if r is not None:
            rows.append(r)
    return rows
