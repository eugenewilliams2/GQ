"""
Walk-forward analysis — the antidote to the overfitting in the old commits.

Procedure (rolling, anchored):
  the timeline is cut into sequential folds. For each fold we optimize the
  strategy's parameters on everything BEFORE it (in-sample), then measure the
  chosen parameters on the fold itself (out-of-sample). Only the stitched-together
  OOS results count. Parameters that only worked because they were fitted to the
  data they were tested on get exposed immediately.

We also return the number of parameter combinations searched, so the caller can
deflate the Sharpe ratio for the multiple-testing this optimization performed.
"""

from __future__ import annotations
import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from forex_bot import metrics
from forex_bot.engine import backtest
from forex_bot.costs import CostModel
from forex_bot.risk import RiskConfig


def param_combos(grid: dict[str, list]) -> list[dict]:
    if not grid:
        return [{}]
    keys = list(grid)
    return [dict(zip(keys, vals)) for vals in itertools.product(*(grid[k] for k in keys))]


@dataclass
class WalkForwardResult:
    oos_returns: np.ndarray
    oos_pnls:    list[float]
    n_trials:    int
    chosen:      list[dict]      # winning params per fold (drift = instability)


def walk_forward(df: pd.DataFrame,
                 strat_cls,
                 grid: dict[str, list],
                 pair: str,
                 cost: CostModel,
                 risk_cfg: RiskConfig,
                 n_splits: int = 4,
                 min_test_bars: int = 100) -> WalkForwardResult:
    combos = param_combos(grid)
    n = len(df)
    fold = n // (n_splits + 1)
    oos_returns: list[np.ndarray] = []
    oos_pnls: list[float] = []
    chosen: list[dict] = []

    for k in range(1, n_splits + 1):
        train = df.iloc[: fold * k]
        test = df.iloc[fold * k: fold * (k + 1)]
        if len(test) < min_test_bars or len(train) < min_test_bars:
            continue

        # ── in-sample optimization: pick params with the best train Sharpe ────
        best_p, best_sh = combos[0], -np.inf
        for p in combos:
            res = backtest(train, strat_cls(**p), pair, cost, risk_cfg)
            sh = metrics.sharpe(metrics.returns_from_equity(res.equity))
            if sh > best_sh:
                best_sh, best_p = sh, p

        # ── out-of-sample: apply the chosen params to the unseen fold ──────────
        res = backtest(test, strat_cls(**best_p), pair, cost, risk_cfg)
        oos_returns.append(metrics.returns_from_equity(res.equity))
        oos_pnls += res.trade_pnls
        chosen.append(best_p)

    rets = np.concatenate(oos_returns) if oos_returns else np.array([])
    return WalkForwardResult(rets, oos_pnls, len(combos), chosen)
