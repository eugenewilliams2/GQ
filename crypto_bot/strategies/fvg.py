"""
Fair Value Gap (FVG) strategy — from the SMC playbook, implemented causally.

A bullish FVG is a 3-candle imbalance where bar i's low prints above bar i-2's
high (a gap the market left behind). The setup: in an up-trend, wait for price to
pull back INTO the most recent unfilled bullish FVG, enter long, stop below the
gap, target a multiple of risk. Bearish is the mirror.

Trend filter (their rule #1 — trade with the macro trend) is a causal EMA.
Everything is known at the close of bar i; the FVG that forms at bar i is only
acted on from bar i onward, so no look-ahead.

NOTE: FVG is part of the SMC family that already scored worst in this harness.
Implemented anyway so `validate` can judge it on its own merits, not by family.
"""

from __future__ import annotations
import numpy as np

from crypto_bot import indicators as ind
from crypto_bot.strategy_base import Strategy, StratSignal


class FVGStrategy(Strategy):
    name = "fvg"

    def __init__(self, trend_ema: int = 100, atr_mult: float = 1.0,
                 rr: float = 2.0, atr_period: int = 14, max_age: int = 30):
        super().__init__(trend_ema=trend_ema, atr_mult=atr_mult, rr=rr,
                         atr_period=atr_period, max_age=max_age)

    def warmup(self) -> int:
        return self.params["trend_ema"] + self.params["atr_period"] + 5

    def prepare(self, df) -> None:
        self.df = df
        h, l, c = df["high"], df["low"], df["close"]
        self.high, self.low, self.close = h.to_numpy(), l.to_numpy(), c.to_numpy()
        self.ema = ind.ema(c, self.params["trend_ema"]).to_numpy()
        self.atr = ind.atr(h, l, c, self.params["atr_period"]).to_numpy()

        n = len(df)
        hi, lo = self.high, self.low
        # Most recent unfilled FVG zone as of each bar (causal, forward-filled).
        self.bull_top = np.full(n, np.nan); self.bull_bot = np.full(n, np.nan); self.bull_age = np.full(n, 1e9)
        self.bear_top = np.full(n, np.nan); self.bear_bot = np.full(n, np.nan); self.bear_age = np.full(n, 1e9)
        bull = bear = None          # (top, bot, formed_idx)
        for i in range(2, n):
            # carry forward, invalidate if filled
            if bull is not None and lo[i] < bull[1]:      # price traded through bottom -> filled
                bull = None
            if bear is not None and hi[i] > bear[0]:
                bear = None
            # new FVG formed at bar i (3-candle pattern i-2,i-1,i)
            if lo[i] > hi[i - 2]:
                bull = (lo[i], hi[i - 2], i)              # top, bottom, idx
            if hi[i] < lo[i - 2]:
                bear = (lo[i - 2], hi[i], i)
            if bull is not None:
                self.bull_top[i], self.bull_bot[i], self.bull_age[i] = bull[0], bull[1], i - bull[2]
            if bear is not None:
                self.bear_top[i], self.bear_bot[i], self.bear_age[i] = bear[0], bear[1], i - bear[2]

    def signal_at(self, i: int) -> StratSignal | None:
        c, e, a = self.close[i], self.ema[i], self.atr[i]
        if np.isnan(e) or np.isnan(a) or a <= 0:
            return None
        am, rr, maxage = self.params["atr_mult"], self.params["rr"], self.params["max_age"]

        # Bullish: up-trend + price pulled back into a fresh unfilled bullish FVG
        if c > e and not np.isnan(self.bull_top[i]) and self.bull_age[i] <= maxage:
            top, bot = self.bull_top[i], self.bull_bot[i]
            if self.low[i] <= top and c >= bot:           # tagged the gap, still above it
                stop = bot - am * a
                if stop < c:
                    return StratSignal(1, stop, c + (c - stop) * rr, meta={"setup": "bull_fvg"})

        # Bearish mirror
        if c < e and not np.isnan(self.bear_bot[i]) and self.bear_age[i] <= maxage:
            top, bot = self.bear_top[i], self.bear_bot[i]
            if self.high[i] >= bot and c <= top:
                stop = top + am * a
                if stop > c:
                    return StratSignal(-1, stop, c - (stop - c) * rr, meta={"setup": "bear_fvg"})
        return None
