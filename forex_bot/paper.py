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

STATE_PATH = os.path.join(os.path.dirname(__file__), os.pardir, ".paper_state.json")
_RECENT_BARS = {"1d": 800, "4h": 1500, "1h": 1500, "1wk": 400}


# ── State ─────────────────────────────────────────────────────────────────────

def _new_state(strategy: str, interval: str, balance: float) -> dict:
    return {"strategy": strategy, "interval": interval, "balance": balance,
            "peak": balance, "open": {}, "closed": [], "history": [], "created": _now()}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def load_state() -> dict | None:
    if not os.path.exists(STATE_PATH):
        return None
    with open(STATE_PATH) as f:
        return json.load(f)


def save_state(st: dict) -> None:
    with open(STATE_PATH, "w") as f:
        json.dump(st, f, indent=2)


def reset(strategy: str, interval: str, balance: float = 10_000.0) -> dict:
    st = _new_state(strategy, interval, balance)
    save_state(st)
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


# ── Tick ──────────────────────────────────────────────────────────────────────

def tick(source: str = "yfinance", pairs=None, cost: CostModel | None = None,
         risk_cfg: risk_mod.RiskConfig | None = None) -> dict:
    st = load_state()
    if st is None:
        raise RuntimeError("no paper session — run `paper --reset` first")
    cost = cost or CostModel()
    risk_cfg = risk_cfg or risk_mod.RiskConfig(risk_per_trade=0.01, max_leverage=30)
    pairs = pairs or config.PAIRS
    cls, _ = REGISTRY[st["strategy"]]
    interval = st["interval"]

    data = _fetch_recent(pairs, source, interval)
    if not data:
        st["history"].append({"t": _now(), "note": "no data fetched"})
        save_state(st)
        return st

    # 1) manage open positions against bars since they opened
    for pair in list(st["open"]):
        df = data.get(pair)
        if df is None:
            continue
        pos = st["open"][pair]
        opened = pd.to_datetime(pos["opened_at"], utc=True)
        future = df[df.index > opened]
        d, stop, tgt, units, entry = pos["dir"], pos["stop"], pos["target"], pos["units"], pos["entry"]
        for ts, row in future.iterrows():
            exit_px = reason = None
            if d == 1:
                if row["open"] <= stop:   exit_px, reason = row["open"], "gap_stop"
                elif row["low"] <= stop:  exit_px, reason = stop, "stop"
                elif row["high"] >= tgt:  exit_px, reason = tgt, "target"
            else:
                if row["open"] >= stop:   exit_px, reason = row["open"], "gap_stop"
                elif row["high"] >= stop: exit_px, reason = stop, "stop"
                elif row["low"] <= tgt:   exit_px, reason = tgt, "target"
            if exit_px is not None:
                fill = cost.fill_price(exit_px, d, pair, is_entry=False)
                pnl = (fill - entry) * d * units - cost.commission(units)
                st["balance"] += pnl
                st["peak"] = max(st["peak"], st["balance"])
                st["closed"].append({**pos, "exit": fill, "pnl": round(pnl, 2),
                                     "closed_at": ts.isoformat(), "reason": reason})
                del st["open"][pair]
                break

    # 2) look for new entries on the latest bar (flat pairs only)
    for pair, df in data.items():
        if pair in st["open"] or len(df) < cls().warmup() + 2:
            continue
        if not risk_mod.drawdown_ok(st["balance"], st["peak"], risk_cfg):
            break
        strat = cls()
        strat.prepare(df)
        sig = strat.signal_at(len(df) - 1)
        if sig is None or sig.direction not in (1, -1):
            continue
        price = float(df["close"].iloc[-1])
        entry = cost.fill_price(price, sig.direction, pair, is_entry=True)
        units = risk_mod.position_units(st["balance"], entry, sig.stop, risk_cfg)
        if units <= 0:
            continue
        st["open"][pair] = {"pair": pair, "dir": sig.direction, "entry": round(entry, 6),
                            "stop": round(sig.stop, 6), "target": round(sig.target, 6),
                            "units": units, "opened_at": df.index[-1].isoformat()}

    # 3) mark-to-market equity snapshot
    equity = st["balance"]
    for pair, pos in st["open"].items():
        df = data.get(pair)
        if df is not None:
            px = float(df["close"].iloc[-1])
            equity += (px - pos["entry"]) * pos["dir"] * pos["units"]
    st["history"].append({"t": _now(), "balance": round(st["balance"], 2),
                          "equity": round(equity, 2), "open": len(st["open"])})
    save_state(st)
    return st


# ── Reporting ─────────────────────────────────────────────────────────────────

def render(st: dict) -> str:
    closed = st["closed"]
    pnls = [c["pnl"] for c in closed]
    wins = [p for p in pnls if p > 0]
    wr = len(wins) / len(pnls) * 100 if pnls else 0.0
    dd = (st["peak"] - st["balance"]) / st["peak"] * 100 if st["peak"] else 0.0
    lines = [
        "═" * 56,
        f"  PAPER TRADING  [{st['strategy']} · {st['interval']}]  (simulated)",
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
