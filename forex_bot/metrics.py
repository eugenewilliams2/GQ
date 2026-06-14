"""
Performance metrics — including the statistics that expose overfitting.

A high backtest Sharpe means little on its own: if you tried 50 strategy variants
and kept the best, you'd expect a high Sharpe by luck alone. The Deflated Sharpe
Ratio (Bailey & López de Prado, 2014) corrects the bar for the number of trials,
the sample length, and non-normal returns. We report it so a "great" backtest
can be called out as probably-noise.

All inputs are simple return series (per-bar fractional returns) or trade P&Ls.
No scipy dependency — uses statistics.NormalDist from the stdlib.
"""

from __future__ import annotations
import math
from dataclasses import dataclass, asdict
from statistics import NormalDist

import numpy as np

_N = NormalDist()
_EULER = 0.5772156649015329          # Euler–Mascheroni constant

# Bars per year for annualization. 1H FX ≈ 24 * 252 trading days.
BARS_PER_YEAR_1H = 24 * 252


@dataclass
class Performance:
    n_trades:        int
    win_rate:        float
    profit_factor:   float
    expectancy:      float     # avg $ per trade
    total_return:    float     # fractional, over the whole period
    cagr:            float
    ann_vol:         float
    sharpe:          float
    sortino:         float
    max_drawdown:    float
    calmar:          float
    psr:             float     # Probabilistic Sharpe Ratio vs 0
    deflated_sharpe: float     # DSR given the number of trials
    n_trials:        int

    def as_dict(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in asdict(self).items()}


# ── Return / drawdown helpers ─────────────────────────────────────────────────

def returns_from_equity(equity: np.ndarray) -> np.ndarray:
    equity = np.asarray(equity, dtype=float)
    if len(equity) < 2:
        return np.array([])
    prev = equity[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(prev != 0, np.diff(equity) / prev, 0.0)
    return np.nan_to_num(r)


def max_drawdown(equity: np.ndarray) -> float:
    equity = np.asarray(equity, dtype=float)
    if len(equity) == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = np.where(peak > 0, (peak - equity) / peak, 0.0)
    return float(dd.max())


# ── Sharpe family ─────────────────────────────────────────────────────────────

def sharpe(returns: np.ndarray, periods_per_year: float = BARS_PER_YEAR_1H) -> float:
    r = np.asarray(returns, dtype=float)
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * math.sqrt(periods_per_year))


def sortino(returns: np.ndarray, periods_per_year: float = BARS_PER_YEAR_1H) -> float:
    r = np.asarray(returns, dtype=float)
    downside = r[r < 0]
    if len(r) < 2 or len(downside) == 0 or downside.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / downside.std(ddof=1) * math.sqrt(periods_per_year))


def probabilistic_sharpe_ratio(returns: np.ndarray, sr_benchmark: float = 0.0) -> float:
    """
    P(true Sharpe > benchmark) given the observed sample, adjusting for skew and
    kurtosis. Uses the *non-annualized* per-bar Sharpe, per the original paper.
    """
    r = np.asarray(returns, dtype=float)
    n = len(r)
    if n < 3 or r.std(ddof=1) == 0:
        return 0.0
    sr = r.mean() / r.std(ddof=1)                       # per-bar Sharpe
    skew = float(((r - r.mean()) ** 3).mean() / r.std(ddof=0) ** 3)
    kurt = float(((r - r.mean()) ** 4).mean() / r.std(ddof=0) ** 4)   # non-excess
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    z = (sr - sr_benchmark) * math.sqrt(n - 1) / denom
    return float(_N.cdf(z))


def deflated_sharpe_ratio(returns: np.ndarray, n_trials: int) -> float:
    """
    DSR = PSR evaluated at the Sharpe you'd expect from the BEST of `n_trials`
    independent strategies whose true Sharpe is zero. If your strategy can't clear
    the bar that pure luck sets after that many tries, DSR -> ~0.
    """
    r = np.asarray(returns, dtype=float)
    n = len(r)
    if n < 3 or n_trials < 1 or r.std(ddof=1) == 0:
        return 0.0
    sr = r.mean() / r.std(ddof=1)
    skew = float(((r - r.mean()) ** 3).mean() / r.std(ddof=0) ** 3)
    kurt = float(((r - r.mean()) ** 4).mean() / r.std(ddof=0) ** 4)

    # Variance of the Sharpe estimator (stand-in for cross-trial variance).
    var_sr = (1 - skew * sr + (kurt - 1) / 4 * sr ** 2) / (n - 1)
    sigma_sr = math.sqrt(max(var_sr, 1e-12))

    if n_trials == 1:
        sr0 = 0.0
    else:
        # Expected max of N standard normals (Gumbel approximation).
        e_max = ((1 - _EULER) * _N.inv_cdf(1 - 1.0 / n_trials)
                 + _EULER * _N.inv_cdf(1 - 1.0 / (n_trials * math.e)))
        sr0 = sigma_sr * e_max

    return probabilistic_sharpe_ratio(r, sr_benchmark=sr0)


# ── Trade-level ───────────────────────────────────────────────────────────────

def trade_stats(pnls: list[float]) -> tuple[float, float, float]:
    """Returns (win_rate, profit_factor, expectancy) from a list of trade P&Ls."""
    if not pnls:
        return 0.0, 0.0, 0.0
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_rate = len(wins) / len(pnls)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    expectancy = sum(pnls) / len(pnls)
    return win_rate, pf, expectancy


# ── Top-level summary ─────────────────────────────────────────────────────────

def summarize(equity: np.ndarray,
              trade_pnls: list[float],
              periods_per_year: float = BARS_PER_YEAR_1H,
              n_trials: int = 1) -> Performance:
    equity = np.asarray(equity, dtype=float)
    r = returns_from_equity(equity)
    win_rate, pf, expectancy = trade_stats(trade_pnls)

    total_return = float(equity[-1] / equity[0] - 1) if len(equity) > 1 and equity[0] else 0.0
    years = len(r) / periods_per_year if len(r) else 0.0
    cagr = float((1 + total_return) ** (1 / years) - 1) if years > 0 and total_return > -1 else 0.0
    ann_vol = float(r.std(ddof=1) * math.sqrt(periods_per_year)) if len(r) > 1 else 0.0
    mdd = max_drawdown(equity)
    shp = sharpe(r, periods_per_year)

    return Performance(
        n_trades=len(trade_pnls),
        win_rate=win_rate,
        profit_factor=pf,
        expectancy=expectancy,
        total_return=total_return,
        cagr=cagr,
        ann_vol=ann_vol,
        sharpe=shp,
        sortino=sortino(r, periods_per_year),
        max_drawdown=mdd,
        calmar=float(cagr / mdd) if mdd > 0 else 0.0,
        psr=probabilistic_sharpe_ratio(r),
        deflated_sharpe=deflated_sharpe_ratio(r, n_trials),
        n_trials=n_trials,
    )
