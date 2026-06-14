"""
Research-harness CLI.

  python run.py compare                       # walk-forward, all strategies, ranked
  python run.py backtest --strategy momentum  # single strategy, full-sample, w/ costs
  python run.py backtest --strategy ict --no-cost   # show how much cost matters
  python run.py fetch --refresh               # rebuild the data cache

This is a research tool. It reports whether a strategy has a measurable edge
out-of-sample after costs — it does NOT place trades.
"""

from __future__ import annotations
import argparse

import numpy as np

from forex_bot import data as data_mod
from forex_bot import metrics, costs, risk
from forex_bot.engine import backtest
from forex_bot.compare import compare, REGISTRY


def _backtest_one(name: str, use_cost: bool) -> None:
    cls, _ = REGISTRY[name]
    cost = costs.CostModel() if use_cost else costs.ZERO_COST
    cfg = risk.RiskConfig(risk_per_trade=0.01, max_leverage=30)
    data = data_mod.load()

    pooled_rets, pooled_pnls = [], []
    for pair, (df1, _) in data.items():
        res = backtest(df1, cls(), pair, cost, cfg, 10_000.0)
        pooled_rets.append(metrics.returns_from_equity(res.equity))
        pooled_pnls += res.trade_pnls
    rets = np.concatenate(pooled_rets) if pooled_rets else np.array([])
    equity = 10_000 * np.cumprod(1 + rets) if len(rets) else np.array([10_000.0])
    perf = metrics.summarize(equity, pooled_pnls, n_trials=1)

    tag = "with costs" if use_cost else "ZERO cost"
    print(f"\n{name} — full-sample, default params ({tag})")
    print("-" * 50)
    for k, v in perf.as_dict().items():
        print(f"  {k:16}: {v}")
    if use_cost and perf.sharpe <= 0:
        print("  -> no edge after costs.")


def main() -> None:
    ap = argparse.ArgumentParser(prog="python run.py",
                                 description="Forex strategy research harness")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("compare", help="walk-forward comparison of all strategies")

    bt = sub.add_parser("backtest", help="single-strategy backtest")
    bt.add_argument("--strategy", "-s", choices=list(REGISTRY), default="momentum")
    bt.add_argument("--no-cost", action="store_true", help="run frictionless")

    f = sub.add_parser("fetch", help="populate/refresh the data cache")
    f.add_argument("--refresh", action="store_true")

    rp = sub.add_parser("report", help="walk-forward comparison -> HTML dashboard")
    rp.add_argument("--out", "-o", default="comparison_report.html")

    args = ap.parse_args()

    if args.cmd == "compare":
        compare(data_mod.load())
    elif args.cmd == "backtest":
        _backtest_one(args.strategy, use_cost=not args.no_cost)
    elif args.cmd == "fetch":
        d = data_mod.load(refresh=args.refresh)
        print(f"cached {len(d)} pairs: {', '.join(d)}")
    elif args.cmd == "report":
        from forex_bot.report import generate
        path = generate(data_mod.load(), args.out)
        print(f"report written -> {path}")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
