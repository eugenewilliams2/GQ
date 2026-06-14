"""
Pairs trading — market-neutral statistical arbitrage.

The one genuinely different idea in the "advanced strategies" list, and the one
with real academic grounding. Take two highly correlated instruments; when the
spread between them stretches to a statistical extreme, short the rich one and
long the cheap one, betting the spread reverts to its mean. Being long one and
short the other neutralizes broad market direction — the edge (if any) is purely
relative mispricing.

Implementation (causal):
  • spread = log(p_a) - log(p_b)
  • rolling z-score of the spread (mean/std over a trailing window, known at t)
  • z >= +entry  -> short spread (short A, long B);  z <= -entry -> long spread
  • exit when |z| <= exit_z (reverted)
  • costs charged on both legs at entry and exit

Pair selection is done on IN-SAMPLE correlation only, then evaluated out-of-sample
(see oos_pairs) so the "best pair" isn't chosen with hindsight.
"""

from __future__ import annotations
from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd

from forex_bot import metrics
from forex_bot.costs import CostModel


@dataclass
class PairResult:
    a: str
    b: str
    equity: np.ndarray
    returns: np.ndarray
    n_trades: int


def _leg_cost_fraction(cost: CostModel, ref: float = 1.1) -> float:
    pip = 0.0001
    return (cost.spread_pips / 2 + cost.slippage_pips) * pip / ref + \
        cost.commission_per_lot / cost.standard_lot / ref


def backtest_pair(pa: pd.Series, pb: pd.Series,
                  window: int = 60, entry_z: float = 2.0, exit_z: float = 0.5,
                  cost: CostModel | None = None, starting: float = 10_000.0) -> PairResult:
    cost = cost or CostModel()
    cfrac = _leg_cost_fraction(cost)
    df = pd.concat([np.log(pa), np.log(pb)], axis=1).dropna()
    spread = (df.iloc[:, 0] - df.iloc[:, 1])
    mu = spread.rolling(window).mean()
    sd = spread.rolling(window).std()
    z = ((spread - mu) / sd.replace(0, np.nan)).to_numpy()
    ra = df.iloc[:, 0].diff().to_numpy()       # log returns ~ pct returns for small moves
    rb = df.iloc[:, 1].diff().to_numpy()
    n = len(df)

    eq = starting
    equity = np.empty(n)
    side = 0                                    # +1 long spread (long A/short B), -1 short spread
    trades = 0
    for i in range(n):
        equity[i] = eq
        if side != 0 and not np.isnan(ra[i]):
            # spread pnl: long spread profits when A up / B down
            eq *= 1 + side * (ra[i] - rb[i]) * 0.5      # half weight per leg
        if i < window or np.isnan(z[i]):
            continue
        if side == 0:
            if z[i] >= entry_z:
                side, trades = -1, trades + 1; eq *= 1 - 2 * cfrac
            elif z[i] <= -entry_z:
                side, trades = 1, trades + 1; eq *= 1 - 2 * cfrac
        elif abs(z[i]) <= exit_z:
            side = 0; eq *= 1 - 2 * cfrac                # close both legs

    return PairResult(pa.name, pb.name, equity, metrics.returns_from_equity(equity), trades)


def oos_pairs(data: dict, cost: CostModel | None = None,
              window: int = 60, entry_z: float = 2.0, exit_z: float = 0.5,
              train_frac: float = 0.7, ppy: float = 252):
    """Select the most-correlated pair on in-sample, evaluate it out-of-sample."""
    cost = cost or CostModel()
    closes = pd.DataFrame({p: data[p][0]["close"] for p in data}).dropna()
    cut = int(len(closes) * train_frac)
    is_df, oos_df = closes.iloc[:cut], closes.iloc[cut:]

    # pick the pair with highest in-sample return correlation
    rets_is = is_df.pct_change().dropna()
    best, best_c = None, -np.inf
    for a, b in combinations(closes.columns, 2):
        c = rets_is[a].corr(rets_is[b])
        if c > best_c:
            best_c, best = c, (a, b)
    a, b = best

    is_res = backtest_pair(is_df[a], is_df[b], window, entry_z, exit_z, cost)
    oos_res = backtest_pair(oos_df[a], oos_df[b], window, entry_z, exit_z, cost)
    is_perf = metrics.summarize(is_res.equity, [], ppy, n_trials=1)
    oos_perf = metrics.summarize(oos_res.equity, [], ppy, n_trials=1)
    return (a, b, best_c), is_perf, oos_perf, oos_res.n_trades
