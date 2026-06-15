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
from forex_bot import config, metrics, costs, risk
from forex_bot.engine import backtest
from forex_bot.compare import compare, REGISTRY

_BARS_PER_DAY = {"1h": 24, "6h": 4, "4h": 6, "1d": 1, "1wk": 1 / 7}


def _load(args):
    return data_mod.load(pairs=config.pairs_for(getattr(args, "asset", "forex")),
                         source=args.source, interval=args.interval,
                         refresh=getattr(args, "refresh", False))


def _cost(args, use_cost: bool = True):
    """Asset- and execution-appropriate cost model. Maker = you post liquidity:
    no spread/slippage paid, only a small maker fee (optimistic — ignores fill
    probability / adverse selection, so it's the favourable bound)."""
    crypto = getattr(args, "asset", "forex") == "crypto"
    if not use_cost:
        return costs.CRYPTO_ZERO_COST if crypto else costs.ZERO_COST
    maker = getattr(args, "execution", "taker") == "maker"
    if crypto:
        return costs.CryptoCostModel(spread_bps=0.0, slippage_bps=0.0, fee_bps=2.0) if maker \
            else costs.CryptoCostModel()
    return costs.CostModel(spread_pips=0.1, slippage_pips=0.0, commission_per_lot=2.0) if maker \
        else costs.CostModel()


def _ppy(args) -> float:
    """Annualization factor: crypto trades 365 days, FX 252; scaled by interval."""
    per_day = _BARS_PER_DAY.get(getattr(args, "interval", "1h"), 24)
    return config.ASSET_DAYS.get(getattr(args, "asset", "forex"), 252) * per_day


def _backtest_one(args, name: str, use_cost: bool, data: dict, ppy: float) -> None:
    cls, _ = REGISTRY[name]
    cost = _cost(args, use_cost)
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
    print(f"\n{name} — {args.asset}, full-sample, default params ({tag})")
    print("-" * 50)
    for k, v in perf.as_dict().items():
        print(f"  {k:16}: {v}")
    if use_cost and perf.sharpe <= 0:
        print("  -> no edge after costs.")


def _add_source_args(p):
    p.add_argument("--asset", default="forex", choices=["forex", "crypto"],
                   help="forex (=X pairs) or crypto (BTC-USD ...)")
    p.add_argument("--source", default="yfinance",
                   choices=["yfinance", "coinbase", "csv", "stooq"])
    p.add_argument("--interval", default="1h", choices=["1h", "6h", "4h", "1d", "1wk"])
    p.add_argument("--execution", default="taker", choices=["taker", "maker"],
                   help="taker = pay spread+fees; maker = post liquidity (optimistic)")


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
    pp.add_argument("--strategy", "-s", choices=list(REGISTRY) + ["ml"], default="fvg")
    pp.add_argument("--name", help="session name (separate state file; omit for default)")
    pp.add_argument("--aggressive", action="store_true", help="conviction-scaled sizing (ml)")
    pp.add_argument("--reset", action="store_true", help="start a fresh paper session")
    pp.add_argument("--status", action="store_true", help="show state without ticking")
    _add_source_args(pp)

    db = sub.add_parser("dashboard", help="generate + serve the live desktop dashboard")
    db.add_argument("--port", type=int, default=8000)
    db.add_argument("--no-serve", action="store_true", help="just write the files")

    sub.add_parser("app", help="launch the fully native desktop window (pywebview)")

    fc = sub.add_parser("funding", help="funding-rate carry (structural, market-neutral) via OKX")
    fc.add_argument("--financing", type=float, default=0.05, help="annual borrow/financing drag")

    ln = sub.add_parser("learn", help="self-test the strategy space; update the leaderboard")
    ln.add_argument("--show", action="store_true", help="just print the current leaderboard")
    _add_source_args(ln)

    ml = sub.add_parser("ml", help="train + walk-forward test the neural-net strategy")
    ml.add_argument("--thr", type=float, default=0.06, help="confidence margin to trade")
    ml.add_argument("--aggressive", action="store_true",
                    help="size up high-conviction trades (capped)")
    ml.add_argument("--holdout", action="store_true",
                    help="strict single train/test split instead of walk-forward")
    _add_source_args(ml)

    args = ap.parse_args()
    if args.cmd is None:
        ap.print_help()
        return

    ppy = _ppy(args) if hasattr(args, "interval") else 252

    if args.cmd == "compare":
        compare(_load(args), cost=_cost(args), periods_per_year=ppy)
    elif args.cmd == "backtest":
        _backtest_one(args, args.strategy, not args.no_cost, _load(args), ppy)
    elif args.cmd == "fetch":
        d = _load(args)
        print(f"[{args.asset}/{args.source}/{args.interval}] cached {len(d)} pairs: "
              f"{', '.join(d) or '(none)'}")
    elif args.cmd == "report":
        from forex_bot.report import generate
        path = generate(_load(args), args.out, periods_per_year=ppy)
        print(f"report written -> {path}")
    elif args.cmd == "validate":
        from forex_bot.validate import holdout_validate
        cls, grid = REGISTRY[args.strategy]
        res = holdout_validate(cls, grid, _load(args), cost=_cost(args),
                               train_frac=args.train_frac, ppy=ppy)
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
        (a, b, corr), isp, oosp, ntr = oos_pairs(_load(args), cost=_cost(args),
                                                 train_frac=args.train_frac, ppy=ppy)
        print(f"\nPAIRS TRADING — {args.source}/{args.interval} (train_frac={args.train_frac})")
        print(f"  most-correlated pair (in-sample): {a} / {b}  corr={corr:.2f}")
        print(f"  IS   sharpe={isp.sharpe:+.2f} maxDD={isp.max_drawdown*100:.1f}%")
        print(f"  OOS  sharpe={oosp.sharpe:+.2f} maxDD={oosp.max_drawdown*100:.1f}% "
              f"trades={ntr} DSR={oosp.deflated_sharpe:.2f}")
    elif args.cmd == "paper":
        from forex_bot import paper
        if args.reset:
            paper.reset(args.strategy, args.interval, name=args.name, aggressive=args.aggressive,
                        asset=args.asset, source=args.source)
            agg = " aggressive" if args.aggressive else ""
            print(f"new paper session '{args.name or 'default'}': {args.asset}/{args.strategy}{agg} "
                  f"on {args.source}/{args.interval} (start $10,000)")
        if args.status:
            st = paper.load_state(args.name)
            print(paper.render(st) if st else "no paper session — run with --reset")
        else:
            st = paper.tick(source=args.source, name=args.name)
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
    elif args.cmd == "app":
        from forex_bot.native_app import main as run_app
        run_app()
    elif args.cmd == "funding":
        from forex_bot.funding import run_funding
        print("fetching OKX funding + perp/spot candles (carry w/ basis + borrow)...")
        perf, coins, tail, periods = run_funding(financing_apr=args.financing)
        if perf is None:
            print("  no data fetched (OKX unreachable here?).")
        else:
            print(f"\nFUNDING CARRY — cash-and-carry w/ basis P&L + borrow ({len(coins)} coins: {', '.join(coins)})")
            print(f"  {periods} funding periods (~8h each)")
            for k, v in perf.as_dict().items():
                print(f"  {k:16}: {v}")
            print(f"  worst period   : {tail['worst_period']*100:+.2f}%   "
                  f"5% CVaR: {tail['cvar5']*100:+.2f}%   basis vol: {tail['basis_vol']*100:.2f}%")
            print("  CAVEAT: still ignores liquidation/exchange-blowup risk; carry has negative skew.")
            edge = perf.deflated_sharpe >= 0.95 and perf.sharpe > 0
            print(f"  VERDICT: {'clears DSR bar — validate live (small) before trusting' if edge else 'no clear edge after costs+basis'}")
    elif args.cmd == "learn":
        from forex_bot import autolearn
        if args.show:
            print(autolearn.render(autolearn.load_leaderboard()))
        else:
            print(f"self-testing strategy space on {args.asset}/{args.source}/{args.interval}...")
            lb = autolearn.run_round(_load(args), args.asset, args.interval, args.source,
                                     ppy, execution=args.execution)
            print(autolearn.render(lb))
    elif args.cmd == "ml":
        from forex_bot.ml import run_ml, holdout_ml
        mode = "AGGRESSIVE (conviction-scaled)" if args.aggressive else "flat 1% sizing"
        test = "strict single holdout" if args.holdout else "4-fold walk-forward"
        print(f"\nNEURAL NET (MLP) — {test}, after costs — {mode} ({args.asset}/{args.source}/{args.interval})")
        print("training per-pair nets... (pure-numpy, no GPU)")
        if args.holdout:
            perf = holdout_ml(_load(args), cost=_cost(args), thr=args.thr, ppy=ppy,
                              aggressive=args.aggressive)
        else:
            perf, _ = run_ml(_load(args), cost=_cost(args), n_splits=4, thr=args.thr,
                             ppy=ppy, aggressive=args.aggressive)
        for k, v in perf.as_dict().items():
            print(f"  {k:16}: {v}")
        verdict = ("crosses the DSR bar on THIS test — forward-validate before trusting"
                   if perf.deflated_sharpe >= 0.95 and perf.sharpe > 0
                   else "no credible edge (indistinguishable from luck after costs)")
        print(f"  VERDICT: {verdict}")


if __name__ == "__main__":
    main()
