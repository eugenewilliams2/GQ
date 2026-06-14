"""
Event-driven backtest engine — single instrument, O(n), cost-aware.

Models what actually happens to money:
  • entries fill at the close of the signal bar, degraded by spread + slippage
  • exits trigger intrabar on the bar's high/low (gaps fill at the open — worse)
  • when stop and target are both touched in one bar, the STOP is assumed first
    (conservative; you can't know which came first from OHLC)
  • commission charged round-trip on close
  • position size from risk.position_units — risk a fixed % at the stop, no more

Risk *halts* (max-drawdown / daily-loss circuit breakers) are OFF by default:
for research you want the strategy's unfiltered behaviour. Turn them on to model
a live risk overlay.
"""

from __future__ import annotations
from dataclasses import dataclass

import numpy as np
import pandas as pd

from forex_bot import risk as risk_mod
from forex_bot.costs import CostModel
from forex_bot.strategy_base import Strategy


@dataclass
class Trade:
    entry_i:   int
    exit_i:    int
    direction: int
    entry:     float
    exit:      float
    units:     int
    pnl:       float
    reason:    str


@dataclass
class BacktestResult:
    equity:  np.ndarray          # mark-to-market equity per bar
    trades:  list[Trade]
    pair:    str

    @property
    def trade_pnls(self) -> list[float]:
        return [t.pnl for t in self.trades]


def backtest(df: pd.DataFrame,
             strategy: Strategy,
             pair: str,
             cost: CostModel,
             risk_cfg: risk_mod.RiskConfig,
             starting_balance: float = 10_000.0,
             apply_risk_halts: bool = False) -> BacktestResult:
    strategy.prepare(df)
    warmup = strategy.warmup()

    open_ = df["open"].to_numpy(float)
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    close = df["close"].to_numpy(float)
    dates = df.index.normalize().to_numpy()       # for daily-loss tracking

    balance = starting_balance
    peak = balance
    equity = np.empty(len(df))
    trades: list[Trade] = []

    pos = None                                    # active position dict or None
    halted = False
    day = None
    daily_pnl = 0.0

    for i in range(len(df)):
        # daily reset for the optional daily-loss halt
        if dates[i] != day:
            day, daily_pnl = dates[i], 0.0

        # ── manage an open position against THIS bar ──────────────────────────
        if pos is not None:
            d, stop, tgt, units, entry_px = (
                pos["dir"], pos["stop"], pos["tgt"], pos["units"], pos["entry"])
            exit_px = reason = None

            if d == 1:
                if open_[i] <= stop:   exit_px, reason = open_[i], "gap_stop"
                elif low[i] <= stop:   exit_px, reason = stop, "stop"
                elif high[i] >= tgt:   exit_px, reason = tgt, "target"
            else:
                if open_[i] >= stop:   exit_px, reason = open_[i], "gap_stop"
                elif high[i] >= stop:  exit_px, reason = stop, "stop"
                elif low[i] <= tgt:    exit_px, reason = tgt, "target"

            if exit_px is not None:
                fill = cost.fill_price(exit_px, d, pair, is_entry=False)
                gross = (fill - entry_px) * d * units
                pnl = gross - cost.commission(units)
                balance += pnl
                daily_pnl += pnl
                peak = max(peak, balance)
                trades.append(Trade(pos["i"], i, d, entry_px, fill, units, pnl, reason))
                pos = None

        # ── mark-to-market equity at this close ───────────────────────────────
        if pos is not None:
            unreal = (close[i] - pos["entry"]) * pos["dir"] * pos["units"]
            equity[i] = balance + unreal
        else:
            equity[i] = balance

        # ── optional risk halts ───────────────────────────────────────────────
        if apply_risk_halts:
            if not risk_mod.drawdown_ok(balance, peak, risk_cfg):
                halted = True
            day_ok = risk_mod.daily_loss_ok(daily_pnl, balance, risk_cfg)
        else:
            day_ok = True

        # ── consider a new entry at this close (flat only) ────────────────────
        if pos is None and not halted and day_ok and i >= warmup and i < len(df) - 1:
            sig = strategy.signal_at(i)
            if sig is not None and sig.direction in (1, -1):
                entry_fill = cost.fill_price(close[i], sig.direction, pair, is_entry=True)
                units = risk_mod.position_units(balance, entry_fill, sig.stop, risk_cfg,
                                                risk_scale=getattr(sig, "risk_scale", 1.0))
                if units > 0:
                    pos = {"dir": sig.direction, "entry": entry_fill, "stop": sig.stop,
                           "tgt": sig.target, "units": units, "i": i}

    # close any residual position at the final close
    if pos is not None:
        i = len(df) - 1
        fill = cost.fill_price(close[i], pos["dir"], pair, is_entry=False)
        pnl = (fill - pos["entry"]) * pos["dir"] * pos["units"] - cost.commission(pos["units"])
        balance += pnl
        trades.append(Trade(pos["i"], i, pos["dir"], pos["entry"], fill, pos["units"], pnl, "eod"))
        equity[i] = balance

    return BacktestResult(equity=equity, trades=trades, pair=pair)
