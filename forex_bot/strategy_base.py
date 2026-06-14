"""
Strategy interface for the research harness.

Two-phase design — this is what makes the backtest both fast and honest:

  prepare(df)   : compute every indicator ONCE over the full series, vectorized.
                  O(n) total instead of recomputing each bar (the old O(n²) trap).
  signal_at(i)  : an O(1) decision for bar i.

CAUSALITY CONTRACT — the one rule that keeps a backtest from lying:
  signal_at(i) may only use information available at the CLOSE of bar i. Any
  indicator that peeks ahead (e.g. a centered swing window that needs future
  bars to confirm) MUST be lagged in prepare() so bar i never sees the future.
  Helpers below (causal_swing_high/low) do exactly that.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class StratSignal:
    direction: int                       # +1 long, -1 short
    stop:      float                     # stop-loss price
    target:    float                     # take-profit price
    meta:      dict = field(default_factory=dict)


class Strategy(ABC):
    """Subclass and implement prepare() + signal_at(). Keep params in self.params
    so the walk-forward optimizer can sweep them."""

    name: str = "base"

    def __init__(self, **params):
        self.params: dict = params
        self.df: pd.DataFrame | None = None

    @abstractmethod
    def prepare(self, df: pd.DataFrame) -> None:
        """Vectorized, causal precompute over the full 1H series."""

    @abstractmethod
    def signal_at(self, i: int) -> StratSignal | None:
        """O(1) decision at bar i, using only precomputed values from bars <= i."""

    def warmup(self) -> int:
        """Bars required before signals are valid."""
        return 50

    def __repr__(self) -> str:
        p = ", ".join(f"{k}={v}" for k, v in self.params.items())
        return f"{self.name}({p})"


# ── Causal indicator helpers ──────────────────────────────────────────────────

def causal_swing_high(high: pd.Series, n: int) -> pd.Series:
    """
    Swing high confirmed n bars AFTER it forms. A centered window needs n future
    bars to know bar k was a local max — so the information only exists at k+n.
    We shift the confirmation forward by n: the returned series at index i carries
    the most recent swing-high *price that was confirmed by bar i*. Forward-filled
    so signal_at(i) can read "the last known swing high" with no look-ahead.
    """
    win = 2 * n + 1
    is_high = high == high.rolling(win, center=True).max()
    confirmed = high.where(is_high).shift(n)        # known only n bars later
    return confirmed.ffill()


def causal_swing_low(low: pd.Series, n: int) -> pd.Series:
    win = 2 * n + 1
    is_low = low == low.rolling(win, center=True).min()
    confirmed = low.where(is_low).shift(n)
    return confirmed.ffill()
