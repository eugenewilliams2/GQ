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

    v = sub.add_parser("validate", help="strict single-holdout OOS test of one strategy")
    v.add_argument("--strategy", "-s", choices=list(REGISTRY), default="tsmom")
    v.add_argument("--train-frac", type=float, default=0.7)
    _add_source_args(v)

    pr = sub.add_parser("pairs", help="market-neutral pairs trading, OOS")
    pr.add_argument("--train-frac", type=float, default=0.7)
    _add_source_args(pr)

    pp = sub.add_parser("paper", help="forward paper-trade a strategy (simulated)")
    pp.add_argument("--strategy", "-s", choices=list(REGISTRY), default="fvg")
    pp.add_argument("--reset", action="store_true", help="start a fresh paper session")
    pp.add_argument("--status", action="store_true", help="show state without ticking")
    _add_source_args(pp)

    db = sub.add_parser("dashboard", help="generate + serve the live desktop dashboard")
    db.add_argument("--port", type=int, default=8000)
    db.add_argument("--no-serve", action="store_true", help="just write the files")

    args = ap.parse_args()
    if args.cmd is None:
        ap.print_help()
        return

    ppy = bars_per_year(getattr(args, "interval", "1h"))

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
    elif args.cmd == "validate":
        from forex_bot.validate import holdout_validate
        cls, grid = REGISTRY[args.strategy]
        res = holdout_validate(cls, grid, _load(args), train_frac=args.train_frac, ppy=ppy)
        deg = res.is_perf.sharpe - res.oos_perf.sharpe
        print(f"\nSTRICT HOLDOUT — {args.strategy} ({args.source}/{args.interval}, "
              f"train_frac={args.train_frac})")
        print(f"  params chosen on in-sample ({res.n_combos} combos): {res.params}")
        for tag, p in (("IS", res.is_perf), ("OOS", res.oos_perf)):
            print(f"  {tag:4} trades={p.n_trades:4} PF={p.profit_factor:.2f} "
                  f"sharpe={p.sharpe:+.2f} maxDD={p.max_drawdown*100:.1f}% "
                  f"PSR={p.psr:.2f} DSR={p.deflated_sharpe:.2f}")
        print(f"  IS->OOS Sharpe degradation: {deg:+.2f}  "
              f"({'OVERFIT — edge did not survive' if deg > 0.4 else 'held up out-of-sample'})")
    elif args.cmd == "pairs":
        from forex_bot.pairs import oos_pairs
        (a, b, corr), isp, oosp, ntr = oos_pairs(_load(args), train_frac=args.train_frac, ppy=ppy)
        print(f"\nPAIRS TRADING — {args.source}/{args.interval} (train_frac={args.train_frac})")
        print(f"  most-correlated pair (in-sample): {a} / {b}  corr={corr:.2f}")
        print(f"  IS   sharpe={isp.sharpe:+.2f} maxDD={isp.max_drawdown*100:.1f}%")
        print(f"  OOS  sharpe={oosp.sharpe:+.2f} maxDD={oosp.max_drawdown*100:.1f}% "
              f"trades={ntr} DSR={oosp.deflated_sharpe:.2f}")
    elif args.cmd == "paper":
        from forex_bot import paper
        if args.reset:
            paper.reset(args.strategy, args.interval)
            print(f"new paper session: {args.strategy} on {args.interval} (start $10,000)")
        if args.status:
            st = paper.load_state()
            print(paper.render(st) if st else "no paper session — run with --reset")
        else:
            st = paper.tick(source=args.source)
            print(paper.render(st))
    elif args.cmd == "dashboard":
        from forex_bot import dashboard, paper
        import http.server, socketserver, functools
        dashboard.write("dashboard.html")
        st = paper.load_state()                      # refresh the servable JSON copy
        if st is not None:
            paper.save_state(st)
        url = f"http://localhost:{args.port}/dashboard.html"
        if args.no_serve:
            print(f"wrote dashboard.html — serve this dir and open {url}")
            return
        handler = functools.partial(http.server.SimpleHTTPRequestHandler)
        print(f"live dashboard -> {url}   (Ctrl+C to stop)")
        with socketserver.TCPServer(("", args.port), handler) as httpd:
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\nstopped.")


if __name__ == "__main__":
    main()
