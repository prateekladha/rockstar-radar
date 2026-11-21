#!/usr/bin/env python3
"""Learn confluence weights from REAL backtest outcomes (Phase 2 "learning", honestly).

Runs the backtest at a low score gate to harvest every candidate trade with its full feature vector
and realised outcome, splits TRAIN (first half of the window) / TEST (second half) by date — no
look-ahead — fits a logistic regression (stdlib gradient descent) to predict a winning trade, and then
on the held-out TEST set gates entries by the model's win-probability and compares P&L to the raw
strategy and the hand-weighted confluence. Shows which signals actually predict wins.

Usage:  python3 tools/learn_weights.py <history.json> [--gate 50]
"""
import json
import math
import os
import sys
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

import backtest as bt          # noqa: E402

FEATURES = ['zone_strength', 'ob_strength', 'fvg_strength', 'structure', 'rvol', 'rsi', 'vp_support',
            'is_long', 'score']


def featurize(t: dict) -> list:
    s = t.get('sig') or {}
    rvol = s.get('rvol')
    return [
        float(s.get('zone_strength') or 0),
        float(s.get('ob_strength') or 0),
        float(s.get('fvg_strength') or 0),
        float(s.get('structure') or 0),
        0.0 if rvol is None else min(max(rvol - 1.0, 0.0), 2.0) / 2.0,   # participation 0..1
        float(s.get('rsi') or 50) / 100.0,
        float(s.get('vp_support') or 0.5),
        1.0 if t.get('side') == 'LONG' else 0.0,
        float(t.get('score') or 0) / 100.0,
    ]


def standardize(rows):
    n = len(rows); m = len(rows[0])
    mean = [sum(r[j] for r in rows) / n for j in range(m)]
    std = [(sum((r[j] - mean[j]) ** 2 for r in rows) / n) ** 0.5 or 1.0 for j in range(m)]
    return mean, std


def apply_std(r, mean, std):
    return [(r[j] - mean[j]) / std[j] for j in range(len(r))]


def train_logreg(X, y, epochs=3000, lr=0.3, l2=1e-3):
    m = len(X[0]); w = [0.0] * m; b = 0.0; n = len(X)
    for _ in range(epochs):
        gw = [0.0] * m; gb = 0.0
        for xi, yi in zip(X, y):
            z = b + sum(w[j] * xi[j] for j in range(m))
            p = 1.0 / (1.0 + math.exp(-max(-30, min(30, z))))
            e = p - yi
            for j in range(m):
                gw[j] += e * xi[j]
            gb += e
        for j in range(m):
            w[j] -= lr * (gw[j] / n + l2 * w[j])
        b -= lr * gb / n
    return w, b


def predict(w, b, x):
    z = b + sum(w[j] * x[j] for j in range(len(x)))
    return 1.0 / (1.0 + math.exp(-max(-30, min(30, z))))


def pnl(trades):
    return round(sum(t['pnl'] for t in trades))


def main():
    path = sys.argv[1]
    gate = int(sys.argv[sys.argv.index('--gate') + 1]) if '--gate' in sys.argv else 50
    hist = bt.load_history(path)
    cfg = json.loads(open(os.path.join(os.path.dirname(__file__), '..', 'config.json')).read())
    trades = bt.run(hist, cfg, gate, 1960, use_exit_engine=False, entry_mode='raw')
    trades = [t for t in trades if t.get('sig')]
    days = sorted({t['day'] for t in trades})
    split = days[len(days) // 2]
    train = [t for t in trades if t['day'] < split]
    test = [t for t in trades if t['day'] >= split]
    print(f'{len(trades)} trades  |  train {len(train)} (<{split})  test {len(test)} (>={split})')

    Xtr_raw = [featurize(t) for t in train]
    ytr = [1 if t['pnl'] > 0 else 0 for t in train]
    mean, std = standardize(Xtr_raw)
    Xtr = [apply_std(r, mean, std) for r in Xtr_raw]
    w, b = train_logreg(Xtr, ytr)

    print('\nLearned signal importance (standardised logreg coef; + => predicts a WIN):')
    for name, coef in sorted(zip(FEATURES, w), key=lambda kv: -abs(kv[1])):
        print(f'  {name:14} {coef:+.2f}')

    # baselines on TEST
    print(f'\nTEST-set P&L ({len(test)} candidate trades):')
    print(f'  raw (take all):              trades={len(test):4d}  P&L=₹{pnl(test):>10,.0f}')
    hc = [t for t in test if t['conf'] >= 50]
    print(f'  hand-confluence>=50:         trades={len(hc):4d}  P&L=₹{pnl(hc):>10,.0f}')

    print('\n  LEARNED model — gate by predicted win-probability:')
    for thr in (0.35, 0.40, 0.45, 0.50, 0.55):
        kept = [t for t in test if predict(w, b, apply_std(featurize(t), mean, std)) >= thr]
        wins = sum(1 for t in kept if t['pnl'] > 0)
        print(f'    P(win)>={thr:.2f}:  trades={len(kept):4d}  win%={100*wins//max(len(kept),1):3d}  '
              f'P&L=₹{pnl(kept):>10,.0f}')


if __name__ == '__main__':
    main()
