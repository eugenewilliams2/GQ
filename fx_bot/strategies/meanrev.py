"""
Z-score mean reversion.

FX majors spend much of their time ranging, where stretched moves snap back to a
moving average. Logic: when price is `entry_z` standard deviations from its mean,
fade it back toward the mean (the target), with an ATR stop beyond the extreme.

Causal: the z-score at bar i uses the mean/std of the window ending at bar i —
all known at that close, no look-ahead.

NOTE: mean reversion and momentum are natural opposites. Running both through the
same harness is deliberate — at most one tends to have edge in a given regime, and
the honest comparison is the whole point.
"""

from __future__ import annotations
import numpy as np

from fx_bot import indicators as ind
from fx_bot.strategy_base import Strategy, StratSignal


class ZScoreMeanReversion(Strategy):
    name = "meanrev"

    def __init__(self, period: int = 20, entry_z: float = 2.0,
                 atr_mult: float = 1.5, atr_period: int = 14):
        super().__init__(period=period, entry_z=entry_z,
                         atr_mult=atr_mult, atr_period=atr_period)

    def warmup(self) -> int:
        return max(self.params["period"], self.params["atr_period"]) + 2

    def prepare(self, df) -> None:
        self.df = df
        c = df["close"]
        p = self.params["period"]
        sma = c.rolling(p).mean()
        std = c.rolling(p).std()
        self.z = ((c - sma) / std.replace(0, np.nan)).to_numpy()
        self.sma = sma.to_numpy()
        self.atr = ind.atr(df["high"], df["low"], c, self.params["atr_period"]).to_numpy()
        self.close = c.to_numpy()

    def signal_at(self, i: int) -> StratSignal | None:
        z, a, c, m = self.z[i], self.atr[i], self.close[i], self.sma[i]
        if np.isnan(z) or np.isnan(a) or np.isnan(m) or a <= 0:
            return None
        ez, am = self.params["entry_z"], self.params["atr_mult"]
        if z <= -ez and m > c:                       # stretched low -> long back to mean
            return StratSignal(1, c - am * a, m)
        if z >= ez and m < c:                        # stretched high -> short back to mean
            return StratSignal(-1, c + am * a, m)
        return None
