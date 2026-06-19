"""
Time-series momentum via Donchian breakout.

Trend-following / breakout is one of the few styles with decades of out-of-sample
evidence across asset classes (Moskowitz–Ooi–Pedersen, "Time Series Momentum";
the original Turtle system). Logic: go with a break of the recent range, ride it
with an ATR-based stop, take profit at a multiple of risk.

Causal: the Donchian channel uses bars STRICTLY before the current one (shift 1),
so a breakout is judged only against confirmed history.
"""

from __future__ import annotations
import numpy as np

from crypto_bot import indicators as ind
from crypto_bot.strategy_base import Strategy, StratSignal


class MomentumBreakout(Strategy):
    name = "momentum"

    def __init__(self, lookback: int = 48, atr_mult: float = 2.0,
                 rr: float = 2.0, atr_period: int = 14):
        super().__init__(lookback=lookback, atr_mult=atr_mult,
                         rr=rr, atr_period=atr_period)

    def warmup(self) -> int:
        return self.params["lookback"] + self.params["atr_period"] + 2

    def prepare(self, df) -> None:
        self.df = df
        h, l, c = df["high"], df["low"], df["close"]
        lb = self.params["lookback"]
        self.upper = h.rolling(lb).max().shift(1).to_numpy()   # prior-range high
        self.lower = l.rolling(lb).min().shift(1).to_numpy()
        self.atr = ind.atr(h, l, c, self.params["atr_period"]).to_numpy()
        self.close = c.to_numpy()

    def signal_at(self, i: int) -> StratSignal | None:
        c, up, lo, a = self.close[i], self.upper[i], self.lower[i], self.atr[i]
        if np.isnan(up) or np.isnan(lo) or np.isnan(a) or a <= 0:
            return None
        am, rr = self.params["atr_mult"], self.params["rr"]
        if c > up:                                   # upside breakout -> long
            return StratSignal(1, c - am * a, c + am * a * rr)
        if c < lo:                                   # downside breakout -> short
            return StratSignal(-1, c + am * a, c - am * a * rr)
        return None
