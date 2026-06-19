"""
Self-testing research loop — the bot's own "training": it searches the strategy
and parameter space, tests every candidate through the honest gauntlet (out-of-
sample, after costs), and keeps a persistent leaderboard.

The anti-overfitting trick that makes this safe rather than a curve-fitting
machine: the Deflated Sharpe of EVERY entry is recomputed against the GRAND TOTAL
of candidates ever tried (stored in the leaderboard). The harder the bot searches,
the higher the statistical bar each result must clear. A candidate is only flagged
for human review if it clears DSR >= 0.95 after that penalty AND has positive
Sharpe — and even then it's a lead for a person to validate, never an auto-deploy.

What this DOES NOT do: download or execute new strategy code from the web. That
would be remote code execution. "Learning" = systematically exploring the known,
audited strategy space and scoring it honestly.
"""

from __future__ import annotations
import itertools
import json
import os
import datetime as dt

import numpy as np

from fx_bot import config, metrics
from fx_bot.engine import backtest
from fx_bot.costs import CostModel, CryptoCostModel
from fx_bot.risk import RiskConfig
from fx_bot.compare import REGISTRY

LEADERBOARD = os.path.join(os.path.dirname(__file__), ".leaderboard.json")


def _candidates():
    """Every (strategy, params) from the registry grids — individual configs."""
    for name, (cls, grid) in REGISTRY.items():
        keys = list(grid)
        for combo in itertools.product(*(grid[k] for k in keys)):
            yield name, cls, dict(zip(keys, combo))


def _oos_returns(cls, params, data, cost, risk_cfg, train_frac):
    """Pooled out-of-sample returns + trade P&Ls for a FIXED param set (no IS
    optimization, so the OOS slice is untouched by fitting)."""
    rets, pnls = [], []
    for pair, (df, _) in data.items():
        if len(df) < 200:
            continue
        cut = int(len(df) * train_frac)
        res = backtest(df, cls(**params), pair, cost, risk_cfg)
        rets.append(metrics.returns_from_equity(res.equity[cut:]))
        pnls += [t.pnl for t in res.trades if t.exit_i >= cut]
    r = np.concatenate(rets) if rets else np.array([])
    return r, pnls


def run_round(data: dict, asset: str, interval: str, source: str,
              ppy: float, train_frac: float = 0.7, execution: str = "taker") -> dict:
    if execution == "maker":
        cost = CryptoCostModel(spread_bps=0.0, slippage_bps=0.0, fee_bps=2.0) if asset == "crypto" \
            else CostModel(spread_pips=0.1, slippage_pips=0.0, commission_per_lot=2.0)
    else:
        cost = CryptoCostModel() if asset == "crypto" else CostModel()
    risk_cfg = RiskConfig(risk_per_trade=0.01, max_leverage=30)
    lb = load_leaderboard()

    cands = list(_candidates())
    grand_total = lb["total_trials"] + len(cands)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    for name, cls, params in cands:
        r, pnls = _oos_returns(cls, params, data, cost, risk_cfg, train_frac)
        if len(r) < 30:
            continue
        sr, n, skew, kurt = metrics.sharpe_moments(r)
        ann = sr * (ppy ** 0.5)
        wr, pf, _ = metrics.trade_stats(pnls)
        lb["entries"].append({
            "strategy": name, "params": params, "asset": asset, "interval": interval,
            "sharpe": round(ann, 3), "sr": sr, "n": n, "skew": skew, "kurt": kurt,
            "trades": len(pnls), "win_rate": round(wr, 3), "profit_factor": round(pf, 3),
            "when": now,
        })

    lb["total_trials"] = grand_total
    # re-judge EVERY entry against the grand total of trials ever run
    for e in lb["entries"]:
        e["dsr"] = round(metrics.dsr_from_moments(e["sr"], e["n"], e["skew"],
                                                  e["kurt"], grand_total), 3)
    lb["entries"].sort(key=lambda e: e["dsr"], reverse=True)
    lb["entries"] = lb["entries"][:40]                  # keep the top 40
    lb["updated"] = now
    save_leaderboard(lb)
    return lb


def load_leaderboard() -> dict:
    if os.path.exists(LEADERBOARD):
        try:
            with open(LEADERBOARD) as f:
                return json.load(f)
        except Exception:
            pass
    return {"total_trials": 0, "entries": [], "updated": None}


def save_leaderboard(lb: dict) -> None:
    with open(LEADERBOARD, "w") as f:
        json.dump(lb, f, indent=2)


def render(lb: dict, top: int = 12) -> str:
    lines = [
        "═" * 76,
        f"  STRATEGY LEADERBOARD  (self-tested, OOS, after costs)",
        f"  {lb['total_trials']} candidates ever tried — DSR penalized for all of them",
        "═" * 76,
        f"  {'strategy':9} {'sharpe':>7} {'PF':>5} {'win%':>5} {'trades':>6} {'DSR':>6}  params",
        "  " + "-" * 72,
    ]
    for e in lb["entries"][:top]:
        p = ",".join(f"{k}={v}" for k, v in e["params"].items())
        lines.append(f"  {e['strategy']:9} {e['sharpe']:>7.2f} {e['profit_factor']:>5.2f} "
                     f"{e['win_rate']*100:>4.0f}% {e['trades']:>6} {e['dsr']:>6.2f}  {p[:34]}")
    lines.append("  " + "-" * 72)
    winners = [e for e in lb["entries"] if e["dsr"] >= 0.95 and e["sharpe"] > 0]
    if winners:
        lines.append(f"  ⚑ {len(winners)} candidate(s) clear DSR>=0.95 after the trial penalty "
                     f"— FLAGGED for human validation (not auto-deployed).")
    else:
        lines.append("  No candidate clears DSR>=0.95 after the multiple-testing penalty. "
                     "Honest result: keep looking.")
    lines.append("═" * 76)
    return "\n".join(lines)
