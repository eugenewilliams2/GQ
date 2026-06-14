"""
Paper trading — forward simulation, no real money, no broker orders.

Each `tick()` fetches the latest data, advances a PERSISTED simulated portfolio:
  • marks open positions against every new bar since they opened (so stops/targets
    are honored even if you don't tick every bar), realizing P&L through the cost
    model and correct position sizing;
  • asks the chosen strategy for a signal on the newest bar and opens a position
    if flat on that pair and risk gates pass;
  • saves state to .paper_state.json so the run accumulates over days/weeks.

This is SIMULATION only. It never contacts a broker. And given the harness found
no edge, expect it to bleed — the value here is watching behaviour in forward
time, not making money.
"""

from __future__ import annotations
import datetime as dt
import json
import os

import pandas as pd

from forex_bot import config, risk as risk_mod
from forex_bot.costs import CostModel
from forex_bot.datasource import get_source
from forex_bot.compare import REGISTRY

_DIR = os.path.join(os.path.dirname(__file__), os.pardir)
_RECENT_BARS = {"1d": 800, "4h": 1500, "1h": 1500, "1wk": 400}


# ── State (named sessions; default name=None keeps the original files) ─────────

def _paths(name: str | None) -> tuple[str, str]:
    """Return (tracked dotfile, servable non-dot copy) for a session name."""
    if name is None:
        return os.path.join(_DIR, ".paper_state.json"), os.path.join(_DIR, "paper_state.json")
    return (os.path.join(_DIR, f".paper_state_{name}.json"),
            os.path.join(_DIR, f"paper_state_{name}.json"))


def _new_state(strategy: str, interval: str, balance: float, aggressive: bool,
               asset: str, source: str) -> dict:
    return {"strategy": strategy, "interval": interval, "aggressive": aggressive,
            "asset": asset, "source": source, "balance": balance, "peak": balance,
            "open": {}, "closed": [], "history": [], "created": _now()}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_state(name: str | None = None) -> dict | None:
    path, _ = _paths(name)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def save_state(st: dict, name: str | None = None) -> None:
    path, servable = _paths(name)
    with open(path, "w") as f:
        json.dump(st, f, indent=2)
    try:
        with open(servable, "w") as f:        # non-dot copy for the web dashboard
            json.dump(st, f)
    except OSError:
        pass


def reset(strategy: str, interval: str, balance: float = 10_000.0,
          name: str | None = None, aggressive: bool = False,
          asset: str = "forex", source: str = "yfinance") -> dict:
    st = _new_state(strategy, interval, balance, aggressive, asset, source)
    save_state(st, name)
    return st


# ── Data ──────────────────────────────────────────────────────────────────────

def _fetch_recent(pairs, source: str, interval: str) -> dict[str, pd.DataFrame]:
    src = get_source(source, interval)
    bars = _RECENT_BARS.get(interval, 1500)
    days = bars if interval == "1d" else max(60, bars // 24 + 5)
    start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=int(days * 1.6))).strftime("%Y-%m-%d")
    end = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).strftime("%Y-%m-%d")
    out = {}
    for p in pairs:
        df = src.fetch(p, start, end)
        if df is not None and len(df):
            out[p] = df
    return out


# ── Per-pair signal provider (rule-based or neural net), causal ───────────────

class _Provider:
    """Wraps a prepared strategy so signal(i) is O(1). For the NN, the model is
    trained ONLY on bars before `new_start`, so replaying bars >= new_start is
    causal (no training on the bars being acted on)."""

    def __init__(self, st, df, new_start):
        if st["strategy"] == "ml":
            import numpy as np
            from forex_bot.ml import build_features, build_labels, MLP, MLStrategy, WARMUP
            X, _ = build_features(df)
            y = build_labels(df, 1)
            n = len(df)
            rows = np.arange(WARMUP, max(WARMUP, new_start))
            rows = rows[np.isfinite(X[rows]).all(1) & np.isfinite(y[rows])]
            preds = np.full(n, np.nan)
            if len(rows) >= 150:
                net = MLP([X.shape[1], 24, 12, 1]).fit(X[rows], y[rows])
                te = np.arange(new_start, n)
                te = te[np.isfinite(X[te]).all(1)]
                preds[te] = net.predict_proba(X[te])
            self.strat = MLStrategy(preds, aggressive=st.get("aggressive", False))
        else:
            cls, _ = REGISTRY[st["strategy"]]
            self.strat = cls()
        self.strat.prepare(df)
        self.wu = self.strat.warmup()

    def signal(self, i):
        return self.strat.signal_at(i) if i >= self.wu else None


def _exit_on_bar(st, pair, row, ts, cost):
    """Close the open position on `pair` if this bar hits its stop/target."""
    pos = st["open"][pair]
    d, stop, tgt, units, entry = pos["dir"], pos["stop"], pos["target"], pos["units"], pos["entry"]
    exit_px = reason = None
    if d == 1:
        if row["open"] <= stop:   exit_px, reason = row["open"], "gap_stop"
        elif row["low"] <= stop:  exit_px, reason = stop, "stop"
        elif row["high"] >= tgt:  exit_px, reason = tgt, "target"
    else:
        if row["open"] >= stop:   exit_px, reason = row["open"], "gap_stop"
        elif row["high"] >= stop: exit_px, reason = stop, "stop"
        elif row["low"] <= tgt:   exit_px, reason = tgt, "target"
    if exit_px is None:
        return
    fill = cost.fill_price(exit_px, d, pair, is_entry=False)
    pnl = (fill - entry) * d * units - cost.commission(units)
    st["balance"] += pnl
    st["peak"] = max(st["peak"], st["balance"])
    st["closed"].append({**pos, "exit": fill, "pnl": round(pnl, 2),
                         "closed_at": ts.isoformat(), "reason": reason})
    del st["open"][pair]


# ── Tick ──────────────────────────────────────────────────────────────────────

def tick(source: str = "yfinance", pairs=None, cost: CostModel | None = None,
         risk_cfg: risk_mod.RiskConfig | None = None, name: str | None = None) -> dict:
    st = load_state(name)
    if st is None:
        raise RuntimeError("no paper session — run `paper --reset` first")
    asset = st.get("asset", "forex")
    if cost is None:
        from forex_bot.costs import CryptoCostModel
        cost = CryptoCostModel() if asset == "crypto" else CostModel()
    risk_cfg = risk_cfg or risk_mod.RiskConfig(risk_per_trade=0.01, max_leverage=30)
    pairs = pairs or config.pairs_for(asset)
    source = st.get("source", source)
    interval = st["interval"]

    data = _fetch_recent(pairs, source, interval)
    if not data:
        st["history"].append({"t": _now(), "note": "no data fetched"})
        save_state(st, name)
        return st

    # Replay every NEW bar since the last tick, in chronological order across all
    # pairs. This lets a single (e.g. daily) tick open/close intraday trades at
    # their actual hours — "trade more often, at different times of day". On the
    # first tick (no last_bar) only the latest bar is acted on, so we don't flood
    # the log by replaying all history as trades.
    last_ts = pd.to_datetime(st["last_bar"], utc=True) if st.get("last_bar") else None
    events, provs = [], {}
    for pair, df in data.items():
        idx = df.index
        new_start = len(df) - 1 if last_ts is None else int(idx.searchsorted(last_ts, side="right"))
        new_start = max(new_start, 0)
        provs[pair] = _Provider(st, df, new_start)
        for i in range(new_start, len(df)):
            events.append((idx[i], pair, i))
    events.sort(key=lambda e: e[0])

    max_ts = last_ts
    for ts, pair, i in events:
        row = data[pair].iloc[i]
        if pair in st["open"]:
            _exit_on_bar(st, pair, row, ts, cost)
        if pair not in st["open"] and risk_mod.drawdown_ok(st["balance"], st["peak"], risk_cfg):
            sig = provs[pair].signal(i)
            if sig is not None and sig.direction in (1, -1):
                entry = cost.fill_price(float(row["close"]), sig.direction, pair, is_entry=True)
                units = risk_mod.position_units(st["balance"], entry, sig.stop, risk_cfg,
                                                risk_scale=getattr(sig, "risk_scale", 1.0))
                if units > 0:
                    st["open"][pair] = {"pair": pair, "dir": sig.direction,
                                        "entry": round(entry, 6), "stop": round(sig.stop, 6),
                                        "target": round(sig.target, 6), "units": units,
                                        "opened_at": ts.isoformat()}
        if max_ts is None or ts > max_ts:
            max_ts = ts
    if max_ts is not None:
        st["last_bar"] = max_ts.isoformat()

    # mark-to-market on the latest close per pair
    equity = st["balance"]
    for pair, pos in st["open"].items():
        df = data.get(pair)
        if df is not None:
            equity += (float(df["close"].iloc[-1]) - pos["entry"]) * pos["dir"] * pos["units"]
    st["history"].append({"t": _now(), "balance": round(st["balance"], 2),
                          "equity": round(equity, 2), "open": len(st["open"])})
    save_state(st, name)
    return st


# ── Reporting ─────────────────────────────────────────────────────────────────

def render(st: dict) -> str:
    closed = st["closed"]
    pnls = [c["pnl"] for c in closed]
    wins = [p for p in pnls if p > 0]
    wr = len(wins) / len(pnls) * 100 if pnls else 0.0
    dd = (st["peak"] - st["balance"]) / st["peak"] * 100 if st["peak"] else 0.0
    tag = st["strategy"] + (" aggressive" if st.get("aggressive") else "")
    lines = [
        "═" * 56,
        f"  PAPER TRADING  [{tag} · {st['interval']}]  (simulated)",
        "═" * 56,
        f"  Balance        : ${st['balance']:,.2f}   (start $10,000)",
        f"  Open positions : {len(st['open'])}",
        f"  Closed trades  : {len(closed)}   win rate {wr:.0f}%",
        f"  Total P&L      : ${st['balance']-10_000:+,.2f}",
        f"  Drawdown       : {dd:.1f}%",
        f"  Ticks          : {len(st['history'])}   since {st['created'][:10]}",
    ]
    if st["open"]:
        lines.append("  " + "-" * 52)
        for pair, p in st["open"].items():
            side = "BUY " if p["dir"] == 1 else "SELL"
            lines.append(f"  {side} {pair.replace('=X',''):8} entry {p['entry']:.5f} "
                         f"SL {p['stop']:.5f} TP {p['target']:.5f} u={p['units']:,}")
    lines.append("═" * 56)
    return "\n".join(lines)
