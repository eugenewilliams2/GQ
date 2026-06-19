"""
ICT / Smart-Money Concepts — ported to the causal harness.

A faithful, single-timeframe rendering of the original 4-gate idea, made honest:

  1. Structure : causal BOS — higher-high & higher-low (bull) / lower-low &
                 lower-high (bear), using swings only confirmed in the past.
  2. Liquidity : entry on a sweep of the last confirmed swing in the trend's
                 favour (price wicks beyond it, closes back).
  3. Momentum  : RSI not in the opposing extreme.

Stop sits beyond the swept level; target is the next confirmed swing in the
trade direction (nearest, not oldest — the take-profit bug from the old code).
Everything reads `causal_swing_*`, so no bar ever sees a swing the market hadn't
yet confirmed. This is the apples-to-apples version of the strategy that the
original backtester couldn't measure honestly.
"""

from __future__ import annotations
import numpy as np

from crypto_bot import indicators as ind
from crypto_bot.strategy_base import (
    Strategy, StratSignal, causal_swing_high, causal_swing_low)


class ICTStrategy(Strategy):
    name = "ict"

    def __init__(self, swing_n: int = 5, atr_period: int = 14,
                 atr_buffer: float = 0.5, rsi_period: int = 14):
        super().__init__(swing_n=swing_n, atr_period=atr_period,
                         atr_buffer=atr_buffer, rsi_period=rsi_period)

    def warmup(self) -> int:
        return self.params["swing_n"] * 6 + self.params["atr_period"] + 5

    def prepare(self, df) -> None:
        self.df = df
        h, l, c = df["high"], df["low"], df["close"]
        n = self.params["swing_n"]

        # Last confirmed swing levels (causal, forward-filled).
        sh = causal_swing_high(h, n)
        sl = causal_swing_low(l, n)
        self.sh = sh.to_numpy()
        self.sl = sl.to_numpy()
        # Previous DISTINCT confirmed swing, held forward (for HH/HL structure):
        # at each change point take the value just before it, then forward-fill so
        # between swings we keep comparing current vs prior swing — not vs itself.
        self.sh_prev = sh.shift().where(sh != sh.shift()).ffill().to_numpy()
        self.sl_prev = sl.shift().where(sl != sl.shift()).ffill().to_numpy()

        self.atr = ind.atr(h, l, c, self.params["atr_period"]).to_numpy()
        self.rsi = ind.rsi(c, self.params["rsi_period"]).to_numpy()
        self.high = h.to_numpy()
        self.low = l.to_numpy()
        self.close = c.to_numpy()

    def signal_at(self, i: int) -> StratSignal | None:
        sh, sl = self.sh[i], self.sl[i]
        shp, slp = self.sh_prev[i], self.sl_prev[i]
        a, rsi, c = self.atr[i], self.rsi[i], self.close[i]
        if any(np.isnan(x) for x in (sh, sl, shp, slp, a, rsi)) or a <= 0:
            return None
        buf = self.params["atr_buffer"] * a

        bull = sh > shp and sl > slp                 # break of structure up
        bear = sh < shp and sl < slp                 # break of structure down

        # Bullish: swept the last swing low (low pierced it, closed back above) + RSI ok
        if bull and self.low[i] < sl < c and rsi < 70:
            stop = sl - buf
            target = sh                              # nearest confirmed high above
            if target > c and stop < c:
                return StratSignal(1, stop, target, meta={"setup": "bull_sweep"})

        # Bearish: swept the last swing high
        if bear and self.high[i] > sh > c and rsi > 30:
            stop = sh + buf
            target = sl
            if target < c and stop > c:
                return StratSignal(-1, stop, target, meta={"setup": "bear_sweep"})

        return None
