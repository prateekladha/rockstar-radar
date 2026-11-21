#!/usr/bin/env python3
"""Train the confluence model on the trader's REAL logged trades — the honest auto-trade path, step 3.

Reads closed trades that carry a confluence snapshot (Order.features, logged at entry for manual AND
auto trades), flattens the confluence components into a feature vector, and — once enough trades have
accumulated — fits a logistic regression (train/test split) to predict a winning trade, reporting the
learned per-signal weights and held-out accuracy. Until there's enough data it just reports how many
more trades are needed. Run periodically on prod (needs the app DB).

This is how we reach real-money auto-trade honestly: learn from what actually works for the trader,
not from mechanical signals the backtest proved have no edge.

Usage (on the server):  python3 tools/learn_from_trades.py [--min 80]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from learn_weights import standardize, apply_std, train_logreg, predict  # noqa: E402

COMPONENTS = ['zone', 'order_block', 'fvg', 'structure', 'rvol', 'rsi', 'volume_profile']
FEATURES = COMPONENTS + ['is_long']


def flatten(row: dict):
    c = row.get('confluence') or {}
    comp = c.get('components') or {}
    feats = [float(comp.get(k, 0) or 0) for k in COMPONENTS]
    feats.append(1.0 if row.get('side') == 'LONG' else 0.0)
    return feats


def main():
    min_n = int(sys.argv[sys.argv.index('--min') + 1]) if '--min' in sys.argv else 80
    from server.db import SessionLocal
    from server.trade_features import export_training_rows
    db = SessionLocal()
    try:
        rows = [r for r in export_training_rows(db) if (r.get('confluence') or {}).get('components')]
    finally:
        db.close()
    print(f'{len(rows)} closed trades carry a confluence snapshot.')
    if len(rows) < min_n:
        print(f'Need >= {min_n} to train a trustworthy model — collect {min_n - len(rows)} more.')
        print('The edge is the trader; keep trading and logging. The model learns from YOU.')
        return

    X = [flatten(r) for r in rows]
    y = [1 if r.get('won') else 0 for r in rows]
    k = int(len(rows) * 0.7)
    mean, std = standardize(X[:k])
    Xtr = [apply_std(r, mean, std) for r in X[:k]]
    w, b = train_logreg(Xtr, y[:k])

    print('\nLearned signal weights (standardised; + => predicts a WIN for the trader):')
    for name, coef in sorted(zip(FEATURES, w), key=lambda kv: -abs(kv[1])):
        print(f'  {name:14} {coef:+.2f}')

    # held-out accuracy + win rate of the trades the model would greenlight
    test = list(zip(X[k:], y[k:], rows[k:]))
    correct = sum(1 for xi, yi, _ in test if (predict(w, b, apply_std(xi, mean, std)) >= 0.5) == bool(yi))
    greenlit = [r for xi, yi, r in test if predict(w, b, apply_std(xi, mean, std)) >= 0.5]
    gw = sum(1 for r in greenlit if r.get('won'))
    gp = sum(float(r.get('pnl') or 0) for r in greenlit)
    print(f'\nHeld-out ({len(test)} trades): accuracy {100*correct//max(len(test),1)}%')
    print(f'Model-greenlit trades: {len(greenlit)}  win% {100*gw//max(len(greenlit),1)}  P&L ₹{gp:,.0f}')
    print('\nWhen the greenlit win% and P&L beat take-all over many trades, this is a candidate for '
          'auto-trade — on paper first, always.')


if __name__ == '__main__':
    main()
