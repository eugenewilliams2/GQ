"""
VWAP reversion — the most-cited intraday crypto setup.

Research (intraday crypto return predictability; VWAP practitioner consensus):
price tends to revert toward the volume-weighted average price. In an uptrend,
buy dips that stretch below VWAP; in a downtrend, fade rallies above it. The
trend filter keeps you reverting WITH the higher-timeframe bias, not against it.

Uses real volume, so it's meaningful for crypto (and inert/■ for volumeless FX —
with no volume, rolling VWAP collapses toward a simple average). Causal: rolling
VWAP and the trend EMA use only past/known-at-close bars.
"""

from __future__ import annotations
import numpy as np

from fx_bot import indicators as ind
from fx_bot.strategy_base import Strategy, StratSignal


class VWAPReversion(Strategy):
    name = "vwap"

    def __init__(self, window: int = 24, dev: float = 1.5, trend_ema: int = 100,
                 atr_mult: float = 1.5, atr_period: int = 14):
        super().__init__(window=window, dev=dev, trend_ema=trend_ema,
                         atr_mult=atr_mult, atr_period=atr_period)

    def warmup(self) -> int:
        return max(self.params["window"], self.params["trend_ema"]) + self.params["atr_period"] + 2

    def prepare(self, df) -> None:
        self.df = df
        c, h, l, v = df["close"], df["high"], df["low"], df["close"] * 0 + df["volume"]
        w = self.params["window"]
        tp = (h + l + c) / 3                                  # typical price
        vol = v.replace(0, np.nan)
        vwap = (tp * vol).rolling(w).sum() / vol.rolling(w).sum()
        vwap = vwap.fillna(tp.rolling(w).mean())             # fallback if no volume
        # standardize deviation by rolling std of (close - vwap)
        dev = (c - vwap)
        self.z = (dev / dev.rolling(w).std().replace(0, np.nan)).to_numpy()
        self.vwap = vwap.to_numpy()
        self.ema = ind.ema(c, self.params["trend_ema"]).to_numpy()
        self.atr = ind.atr(h, l, c, self.params["atr_period"]).to_numpy()
        self.close = c.to_numpy()

    def signal_at(self, i: int) -> StratSignal | None:
        z, vw, e, a, c = self.z[i], self.vwap[i], self.ema[i], self.atr[i], self.close[i]
        if any(np.isnan(x) for x in (z, vw, e, a)) or a <= 0:
            return None
        dev, am = self.params["dev"], self.params["atr_mult"]
        # uptrend: buy a stretched dip below VWAP, target reversion to VWAP
        if c > e and z <= -dev and vw > c:
            return StratSignal(1, c - am * a, vw, meta={"setup": "vwap_dip"})
        # downtrend: fade a stretched rally above VWAP
        if c < e and z >= dev and vw < c:
            return StratSignal(-1, c + am * a, vw, meta={"setup": "vwap_rally"})
        return None
