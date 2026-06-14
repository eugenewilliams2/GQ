"""
Position sizing & risk control — corrected.

The old risk_manager.position_size() multiplied units by LOT_SIZE
(`risk / sl_dist * LOT_SIZE`), inflating size ~1000× so arbitrary caps — not the
risk target — decided the position. Result: ~29% account swings per trade and a
44% drawdown from three trades.

Correct fixed-fractional sizing is dimensionally simple:

    risk_amount = balance * risk_per_trade          # e.g. 1% of $10k = $100
    units       = risk_amount / stop_distance        # price units, NOT lots

Then P&L if the stop is hit is exactly  units * stop_distance = risk_amount.
Leverage only ever *caps* the size; it never sets it.
"""

from __future__ import annotations
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade:   float = 0.01    # fraction of balance risked at the stop
    max_leverage:     float = 30.0    # hard cap on notional / balance
    max_open_trades:  int   = 5
    portfolio_heat:   float = 0.06    # max aggregate risk across open trades
    daily_loss_limit: float = 0.04    # halt new trades after this daily loss
    max_drawdown:     float = 0.20    # halt entirely beyond this peak-to-trough
    vol_target:       float | None = None  # if set, scale risk toward this annual vol


def position_units(balance: float,
                   entry: float,
                   stop: float,
                   cfg: RiskConfig) -> int:
    """
    Units (base currency) to risk exactly `risk_per_trade` of balance at the stop,
    capped by leverage. Returns 0 when inputs are degenerate so the caller skips
    the trade rather than taking a mis-sized one.
    """
    stop_dist = abs(entry - stop)
    if stop_dist <= 0 or balance <= 0 or entry <= 0:
        return 0

    risk_amount = balance * cfg.risk_per_trade
    units = risk_amount / stop_dist                      # <-- the correct formula

    max_units = cfg.max_leverage * balance / entry       # leverage only caps
    return int(max(0.0, min(units, max_units)))


def vol_scaled_risk(base_risk: float,
                    realized_vol: float,
                    target_vol: float) -> float:
    """
    Scale the risk fraction so the position contributes ~`target_vol` annualized.
    Lower position size when the market is wild, larger when it's calm — the
    single most reliable way professionals stabilize drawdowns.
    """
    if realized_vol <= 0:
        return base_risk
    scale = float(np.clip(target_vol / realized_vol, 0.25, 2.0))
    return base_risk * scale


# ── Pre-trade gates ──────────────────────────────────────────────────────────

def drawdown_ok(balance: float, peak: float, cfg: RiskConfig) -> bool:
    if peak <= 0:
        return True
    return (peak - balance) / peak <= cfg.max_drawdown


def daily_loss_ok(daily_pnl: float, balance: float, cfg: RiskConfig) -> bool:
    return not (daily_pnl < 0 and abs(daily_pnl) / balance > cfg.daily_loss_limit)


def heat_ok(open_risk: float, balance: float, cfg: RiskConfig) -> bool:
    """`open_risk` = sum of (stop distance * units) across open trades."""
    if balance <= 0:
        return False
    return open_risk / balance < cfg.portfolio_heat
