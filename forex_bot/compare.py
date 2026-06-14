"""
Strategy comparison — the honest scoreboard.

Runs every registered strategy through walk-forward across all pairs, pools the
out-of-sample returns, and ranks by the OUT-OF-SAMPLE Deflated Sharpe Ratio
(penalized for how many parameter combinations the optimization tried). A
strategy "wins" only if it survives costs, out-of-sample testing, AND the
multiple-testing correction. The expected, honest default outcome on free hourly
FX data is "none of them have a real edge" — and the table will say so.
"""

from __future__ import annotations

import numpy as np

from forex_bot import metrics
from forex_bot.costs import CostModel
from forex_bot.risk import RiskConfig
from forex_bot.walkforward import walk_forward
from forex_bot.strategies.momentum import MomentumBreakout
from forex_bot.strategies.meanrev import ZScoreMeanReversion
from forex_bot.strategies.ict import ICTStrategy


# (strategy class, parameter grid to search in-sample)
REGISTRY = {
    "momentum": (MomentumBreakout, {
        "lookback": [24, 48, 96], "atr_mult": [1.5, 2.0, 3.0], "rr": [1.5, 2.0]}),
    "meanrev": (ZScoreMeanReversion, {
        "period": [10, 20, 40], "entry_z": [1.5, 2.0, 2.5], "atr_mult": [1.5, 2.0]}),
    "ict": (ICTStrategy, {
        "swing_n": [3, 5, 8], "atr_buffer": [0.3, 0.5, 1.0]}),
}


def compare(data: dict,
            cost: CostModel | None = None,
            risk_cfg: RiskConfig | None = None,
            n_splits: int = 4) -> list[metrics.Performance]:
    cost = cost or CostModel()
    risk_cfg = risk_cfg or RiskConfig(risk_per_trade=0.01, max_leverage=30)

    rows: list[tuple[str, metrics.Performance]] = []
    for name, (cls, grid) in REGISTRY.items():
        pooled_rets, pooled_pnls, n_trials = [], [], 1
        for pair, (df1, _) in data.items():
            wf = walk_forward(df1, cls, grid, pair, cost, risk_cfg, n_splits=n_splits)
            if len(wf.oos_returns):
                pooled_rets.append(wf.oos_returns)
            pooled_pnls += wf.oos_pnls
            n_trials = wf.n_trials
        rets = np.concatenate(pooled_rets) if pooled_rets else np.array([])
        # build a pooled equity curve from OOS returns for drawdown/Sharpe
        equity = 10_000 * np.cumprod(1 + rets) if len(rets) else np.array([10_000.0])
        perf = metrics.summarize(equity, pooled_pnls, n_trials=n_trials)
        rows.append((name, perf))

    rows.sort(key=lambda x: x[1].deflated_sharpe, reverse=True)
    _print_table(rows)
    return [p for _, p in rows]


def _print_table(rows) -> None:
    print("\n" + "=" * 78)
    print("  OUT-OF-SAMPLE STRATEGY COMPARISON  (walk-forward, after costs)")
    print("=" * 78)
    print(f"  {'strategy':10} {'trades':>7} {'win%':>6} {'PF':>5} "
          f"{'sharpe':>7} {'maxDD':>6} {'PSR':>5} {'DSR':>5} {'trials':>6}")
    print("  " + "-" * 74)
    for name, p in rows:
        print(f"  {name:10} {p.n_trades:>7} {p.win_rate*100:>5.1f} {p.profit_factor:>5.2f} "
              f"{p.sharpe:>7.2f} {p.max_drawdown*100:>5.1f} {p.psr:>5.2f} "
              f"{p.deflated_sharpe:>5.2f} {p.n_trials:>6}")
    print("  " + "-" * 74)
    best = rows[0][1] if rows else None
    if best is None or best.deflated_sharpe < 0.95 or best.sharpe <= 0:
        print("  VERDICT: no strategy shows a credible edge out-of-sample after costs.")
        print("           (DSR < 0.95 / non-positive Sharpe = indistinguishable from luck.)")
    else:
        print(f"  VERDICT: {rows[0][0]} clears the bar (DSR={best.deflated_sharpe:.2f}) — "
              f"worth deeper validation, not blind trust.")
    print("=" * 78)
