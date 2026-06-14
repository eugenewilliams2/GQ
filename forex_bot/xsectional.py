"""
Cross-sectional momentum — a portfolio strategy.

Rather than time each pair alone, rank ALL pairs by trailing return each
rebalance, go long the strongest `k` and short the weakest `k`, equal risk per
leg. Cross-sectional FX momentum has solid academic support (Menkhoff, Sarno,
Schmeling & Schrimpf, 2012). Because it's inherently portfolio-level it can't run
through the single-instrument engine, so it has its own backtest here — but it
reuses the same cost model and metrics, and the same walk-forward discipline.

Costs are approximated as a per-unit-turnover fraction derived from the cost
model at a representative price (good enough for relative comparison).
"""

from __future__ import annotations
from dataclasses import dataclass

import numpy as np
import pandas as pd

from forex_bot import metrics
from forex_bot.costs import CostModel
from forex_bot.walkforward import param_combos


def _turnover_cost_fraction(cost: CostModel, ref_price: float = 1.1) -> float:
    """Cost (as a fraction of notional) to change one unit of portfolio weight."""
    pip = 0.0001
    spread = (cost.spread_pips / 2 + cost.slippage_pips) * pip / ref_price
    comm = cost.commission_per_lot / cost.standard_lot / ref_price
    return spread + comm


@dataclass
class XSResult:
    equity: np.ndarray
    returns: np.ndarray


def backtest_xsmom(closes: pd.DataFrame,
                   lookback: int = 240,
                   k: int = 2,
                   rebalance: int = 24,
                   cost: CostModel | None = None,
                   starting: float = 10_000.0) -> XSResult:
    cost = cost or CostModel()
    cost_unit = _turnover_cost_fraction(cost)
    rets = closes.pct_change().fillna(0.0).to_numpy()
    px = closes.to_numpy()
    n, m = px.shape
    k = min(k, m // 2) or 1

    weights = np.zeros(m)
    eq = starting
    equity = np.empty(n)

    for t in range(n):
        equity[t] = eq
        eq *= 1 + float(weights @ rets[t])           # apply current weights to this bar
        if t >= lookback and t % rebalance == 0:
            trailing = px[t] / px[t - lookback] - 1
            order = np.argsort(trailing)
            new_w = np.zeros(m)
            new_w[order[-k:]] = 1.0 / (2 * k)         # long strongest
            new_w[order[:k]] = -1.0 / (2 * k)         # short weakest
            eq *= 1 - np.abs(new_w - weights).sum() * cost_unit
            weights = new_w

    return XSResult(equity=equity, returns=metrics.returns_from_equity(equity))


def walk_forward_xsmom(data: dict,
                       grid: dict[str, list],
                       cost: CostModel,
                       n_splits: int = 4):
    """OOS walk-forward for the portfolio strategy on the shared timeline."""
    pairs = list(data)
    closes = pd.DataFrame({p: data[p][0]["close"] for p in pairs}).dropna()
    combos = param_combos(grid)
    n = len(closes)
    fold = n // (n_splits + 1)
    oos_returns: list[np.ndarray] = []

    for s in range(1, n_splits + 1):
        train = closes.iloc[: fold * s]
        test = closes.iloc[fold * s: fold * (s + 1)]
        if len(test) < 100 or len(train) < 250:
            continue
        best_p, best_sh = combos[0], -np.inf
        for p in combos:
            r = backtest_xsmom(train, cost=cost, **p).returns
            sh = metrics.sharpe(r)
            if sh > best_sh:
                best_sh, best_p = sh, p
        oos_returns.append(backtest_xsmom(test, cost=cost, **best_p).returns)

    rets = np.concatenate(oos_returns) if oos_returns else np.array([])
    return rets, len(combos)
