"""
Wickless-candle method — implemented causally and tested honestly.

A bullish wickless candle (green, open == low, no lower wick) means buyers took
control instantly; its open/low becomes a support level. A bearish wickless candle
(red, open == high, no upper wick) leaves its open/high as resistance. The method:
when price later pulls back INTO that level (in the trend's direction), trade the
expected bounce/rejection, stop just beyond the level.

Real data rarely has a perfectly zero wick, so "wickless" = the wick on that side
is <= wick_tol of the candle's range, with a real body (marubozu-like). Levels are
tracked causally: a level is known at the close of the candle that formed it,
acted on only later, expires after max_age bars, and is invalidated once price
closes through it.

This is in the SMC/order-block family the harness has repeatedly shown has no edge
after costs — implemented anyway so `validate`/`compare` can judge it on its own.
"""

from __future__ import annotations
import numpy as np

from fx_bot import indicators as ind
from fx_bot.strategy_base import Strategy, StratSignal


class WicklessCandle(Strategy):
    name = "wickless"

    def __init__(self, trend_ema: int = 100, atr_mult: float = 1.0, rr: float = 2.0,
                 atr_period: int = 14, max_age: int = 20,
                 wick_tol: float = 0.05, body_min: float = 0.5):
        super().__init__(trend_ema=trend_ema, atr_mult=atr_mult, rr=rr,
                         atr_period=atr_period, max_age=max_age,
                         wick_tol=wick_tol, body_min=body_min)

    def warmup(self) -> int:
        return self.params["trend_ema"] + self.params["atr_period"] + 5

    def prepare(self, df) -> None:
        self.df = df
        o, h, l, c = (df["open"].to_numpy(), df["high"].to_numpy(),
                      df["low"].to_numpy(), df["close"].to_numpy())
        self.open, self.high, self.low, self.close = o, h, l, c
        self.ema = ind.ema(df["close"], self.params["trend_ema"]).to_numpy()
        self.atr = ind.atr(df["high"], df["low"], df["close"], self.params["atr_period"]).to_numpy()

        n = len(df)
        rng = np.maximum(h - l, 1e-12)
        body = np.abs(c - o)
        wt, bm = self.params["wick_tol"], self.params["body_min"]
        green, red = c > o, c < o
        lower_wick = np.minimum(o, c) - l
        upper_wick = h - np.maximum(o, c)
        bull_wickless = green & (lower_wick <= wt * rng) & (body >= bm * rng)
        bear_wickless = red & (upper_wick <= wt * rng) & (body >= bm * rng)

        # most-recent active support/resistance level (causal, carried forward)
        self.bull_lvl = np.full(n, np.nan); self.bull_age = np.full(n, 1e9)
        self.bear_lvl = np.full(n, np.nan); self.bear_age = np.full(n, 1e9)
        bull = bear = None                      # (level, formed_idx)
        for i in range(n):
            if bull is not None and c[i] < bull[0]:    # support broken -> invalidate
                bull = None
            if bear is not None and c[i] > bear[0]:
                bear = None
            if bull_wickless[i]:
                bull = (o[i], i)                # open == low = support
            if bear_wickless[i]:
                bear = (o[i], i)                # open == high = resistance
            if bull is not None:
                self.bull_lvl[i], self.bull_age[i] = bull[0], i - bull[1]
            if bear is not None:
                self.bear_lvl[i], self.bear_age[i] = bear[0], i - bear[1]

    def signal_at(self, i: int) -> StratSignal | None:
        c, e, a = self.close[i], self.ema[i], self.atr[i]
        if np.isnan(e) or np.isnan(a) or a <= 0:
            return None
        am, rr, maxage = self.params["atr_mult"], self.params["rr"], self.params["max_age"]

        # uptrend + price tagged the support level from above (still closing above it)
        if c > e and not np.isnan(self.bull_lvl[i]) and self.bull_age[i] <= maxage:
            lvl = self.bull_lvl[i]
            if self.low[i] <= lvl <= c:
                stop = lvl - am * a
                if stop < c:
                    return StratSignal(1, stop, c + (c - stop) * rr, meta={"setup": "bull_wickless"})

        # downtrend + price tagged the resistance level from below
        if c < e and not np.isnan(self.bear_lvl[i]) and self.bear_age[i] <= maxage:
            lvl = self.bear_lvl[i]
            if self.high[i] >= lvl >= c:
                stop = lvl + am * a
                if stop > c:
                    return StratSignal(-1, stop, c - (stop - c) * rr, meta={"setup": "bear_wickless"})
        return None
