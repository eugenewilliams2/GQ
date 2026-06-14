"""
Research-harness CLI.

  python run.py compare                              # walk-forward, all strategies, ranked
  python run.py compare --source yfinance --interval 1d   # daily data instead of hourly
  python run.py compare --source csv                 # your own data in ./data/<PAIR>.csv
  python run.py backtest --strategy momentum         # single strategy, with realistic costs
  python run.py backtest -s ict --no-cost            # frictionless, to show cost impact
  python run.py report                               # HTML dashboard
  python run.py fetch --source yfinance --interval 1d --refresh

Sources: yfinance (1h/1d), csv (drop OHLCV+volume files in ./data/), stooq (daily).
Research tool only — reports whether a strategy has edge after costs; places no trades.
"""

from __future__ import annotations
import argparse

import numpy as np

from forex_bot import data as data_mod
from forex_bot import metrics, costs, risk
from forex_bot.datasource import bars_per_year
from forex_bot.engine import backtest
from forex_bot.compare import compare, REGISTRY


def _load(args):
    return data_mod.load(source=args.source, interval=args.interval,
                         refresh=getattr(args, "refresh", False))


def _backtest_one(name: str, use_cost: bool, data: dict, ppy: float) -> None:
    cls, _ = REGISTRY[name]
    cost = costs.CostModel() if use_cost else costs.ZERO_COST
    cfg = risk.RiskConfig(risk_per_trade=0.01, max_leverage=30)

    pooled_rets, pooled_pnls = [], []
    for pair, (df1, _) in data.items():
        res = backtest(df1, cls(), pair, cost, cfg, 10_000.0)
        pooled_rets.append(metrics.returns_from_equity(res.equity))
        pooled_pnls += res.trade_pnls
    rets = np.concatenate(pooled_rets) if pooled_rets else np.array([])
    equity = 10_000 * np.cumprod(1 + rets) if len(rets) else np.array([10_000.0])
    perf = metrics.summarize(equity, pooled_pnls, ppy, n_trials=1)

    tag = "with costs" if use_cost else "ZERO cost"
    print(f"\n{name} — full-sample, default params ({tag})")
    print("-" * 50)
    for k, v in perf.as_dict().items():
        print(f"  {k:16}: {v}")
    if use_cost and perf.sharpe <= 0:
        print("  -> no edge after costs.")


def _add_source_args(p):
    p.add_argument("--source", default="yfinance", choices=["yfinance", "csv", "stooq"])
    p.add_argument("--interval", default="1h", choices=["1h", "4h", "1d", "1wk"])


def main() -> None:
    ap = argparse.ArgumentParser(prog="python run.py",
                                 description="Forex strategy research harness")
    sub = ap.add_subparsers(dest="cmd")

    c = sub.add_parser("compare", help="walk-forward comparison of all strategies")
    _add_source_args(c)

    bt = sub.add_parser("backtest", help="single-strategy backtest")
    bt.add_argument("--strategy", "-s", choices=list(REGISTRY), default="momentum")
    bt.add_argument("--no-cost", action="store_true", help="run frictionless")
    _add_source_args(bt)

    f = sub.add_parser("fetch", help="populate/refresh the data cache")
    f.add_argument("--refresh", action="store_true")
    _add_source_args(f)

    rp = sub.add_parser("report", help="walk-forward comparison -> HTML dashboard")
    rp.add_argument("--out", "-o", default="comparison_report.html")
    _add_source_args(rp)

    args = ap.parse_args()
    if args.cmd is None:
        ap.print_help()
        return

    ppy = bars_per_year(args.interval)

    if args.cmd == "compare":
        compare(_load(args), periods_per_year=ppy)
    elif args.cmd == "backtest":
        _backtest_one(args.strategy, not args.no_cost, _load(args), ppy)
    elif args.cmd == "fetch":
        d = _load(args)
        print(f"[{args.source}/{args.interval}] cached {len(d)} pairs: {', '.join(d) or '(none)'}")
    elif args.cmd == "report":
        from forex_bot.report import generate
        path = generate(_load(args), args.out, periods_per_year=ppy)
        print(f"report written -> {path}")


if __name__ == "__main__":
    main()
