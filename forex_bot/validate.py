"""
Single-holdout out-of-sample validation — the clean test.

Walk-forward re-optimizes every fold, so its Deflated Sharpe is penalized for the
full grid each time. This module does the stricter, simpler thing:

  1. split each series into in-sample (first `train_frac`) and out-of-sample (rest)
  2. choose ONE parameter set on the in-sample data only
  3. evaluate that locked set ONCE on the untouched out-of-sample data

Because OOS was never used for selection, its Sharpe is unbiased and the Deflated
Sharpe is reported with n_trials=1 (a single locked evaluation). We also report
the IS->OOS degradation: a big drop is the fingerprint of overfitting.

`preregistered()` goes further — no grid at all, parameters fixed from theory —
which is the only test with literally zero selection bias.
"""

from __future__ import annotations
from dataclasses import dataclass

import numpy as np

from forex_bot import metrics
from forex_bot.engine import backtest
from forex_bot.costs import CostModel
from forex_bot.risk import RiskConfig
from forex_bot.walkforward import param_combos


@dataclass
class HoldoutResult:
    params:   dict
    is_perf:  metrics.Performance
    oos_perf: metrics.Performance
    n_combos: int


def _pool(cls, params, pairs_data, cost, risk_cfg, which, train_frac):
    """Pool returns + trade pnls across pairs over the IS or OOS slice."""
    rets, pnls = [], []
    for _pair, (df1, _) in pairs_data.items():
        cut = int(len(df1) * train_frac)
        seg = df1.iloc[:cut] if which == "is" else df1.iloc[cut:]
        if len(seg) < 60:
            continue
        res = backtest(seg, cls(**params), _pair, cost, risk_cfg)
        rets.append(metrics.returns_from_equity(res.equity))
        pnls += res.trade_pnls
    r = np.concatenate(rets) if rets else np.array([])
    return r, pnls


def holdout_validate(cls, grid, data, cost=None, risk_cfg=None,
                     train_frac=0.7, ppy=252) -> HoldoutResult:
    cost = cost or CostModel()
    risk_cfg = risk_cfg or RiskConfig(risk_per_trade=0.01, max_leverage=30)
    combos = param_combos(grid)

    # 1-2. select the single best param set on IN-SAMPLE pooled Sharpe
    best_p, best_sh = combos[0], -np.inf
    for p in combos:
        r, _ = _pool(cls, p, data, cost, risk_cfg, "is", train_frac)
        sh = metrics.sharpe(r, ppy)
        if sh > best_sh:
            best_sh, best_p = sh, p

    # 3. evaluate the locked set ONCE on each slice
    r_is, pnl_is = _pool(cls, best_p, data, cost, risk_cfg, "is", train_frac)
    r_oos, pnl_oos = _pool(cls, best_p, data, cost, risk_cfg, "oos", train_frac)
    eq_is = 10_000 * np.cumprod(1 + r_is) if len(r_is) else np.array([10_000.0])
    eq_oos = 10_000 * np.cumprod(1 + r_oos) if len(r_oos) else np.array([10_000.0])

    return HoldoutResult(
        params=best_p,
        is_perf=metrics.summarize(eq_is, pnl_is, ppy, n_trials=len(combos)),
        oos_perf=metrics.summarize(eq_oos, pnl_oos, ppy, n_trials=1),
        n_combos=len(combos),
    )


def preregistered(cls, params, data, cost=None, risk_cfg=None,
                  train_frac=0.7, ppy=252) -> metrics.Performance:
    """Fixed params, no search — evaluated once on OOS. Zero selection bias."""
    cost = cost or CostModel()
    risk_cfg = risk_cfg or RiskConfig(risk_per_trade=0.01, max_leverage=30)
    r, pnl = _pool(cls, params, data, cost, risk_cfg, "oos", train_frac)
    eq = 10_000 * np.cumprod(1 + r) if len(r) else np.array([10_000.0])
    return metrics.summarize(eq, pnl, ppy, n_trials=1)
