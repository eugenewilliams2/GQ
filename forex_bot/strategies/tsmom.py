"""
Time-series momentum with a trend-regime filter.

The most robust documented anomaly in macro/FX (Moskowitz–Ooi–Pedersen; the
managed-futures industry): instruments that have risen tend to keep rising. We
add a regime filter — only take longs when price is above a long EMA, shorts when
below — so we trade WITH the prevailing trend, not against it. The filter is the
point: raw momentum whipsaws in ranges; gating it by regime is what historically
separates trend-following that survives from the kind that bleeds out.

Causal: trailing return (pct_change) and the EMA both use only past/current data.
"""

from __future__ import annotations
import numpy as np

from forex_bot import indicators as ind
from forex_bot.strategy_base import Strategy, StratSignal


class TSMomentum(Strategy):
    name = "tsmom"

    def __init__(self, mom_lookback: int = 120, trend_ema: int = 200,
                 atr_mult: float = 2.0, rr: float = 2.0, atr_period: int = 14):
        super().__init__(mom_lookback=mom_lookback, trend_ema=trend_ema,
                         atr_mult=atr_mult, rr=rr, atr_period=atr_period)

    def warmup(self) -> int:
        return max(self.params["trend_ema"], self.params["mom_lookback"]) + \
            self.params["atr_period"] + 2

    def prepare(self, df) -> None:
        self.df = df
        c = df["close"]
        self.mom = c.pct_change(self.params["mom_lookback"]).to_numpy()
        self.ema = ind.ema(c, self.params["trend_ema"]).to_numpy()
        self.atr = ind.atr(df["high"], df["low"], c, self.params["atr_period"]).to_numpy()
        self.close = c.to_numpy()

    def signal_at(self, i: int) -> StratSignal | None:
        m, e, c, a = self.mom[i], self.ema[i], self.close[i], self.atr[i]
        if any(np.isnan(x) for x in (m, e, a)) or a <= 0:
            return None
        am, rr = self.params["atr_mult"], self.params["rr"]
        if m > 0 and c > e:                           # up-trend regime, positive momentum
            return StratSignal(1, c - am * a, c + am * a * rr)
        if m < 0 and c < e:                           # down-trend regime, negative momentum
            return StratSignal(-1, c + am * a, c - am * a * rr)
        return None
