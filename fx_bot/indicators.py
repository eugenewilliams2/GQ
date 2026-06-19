"""
Technical indicator library — pure pandas/numpy.

Covers: standard indicators + ICT/SMC concepts (order blocks, FVGs,
market structure, liquidity sweeps, killzones) verified by deep research.
"""

from __future__ import annotations
from datetime import datetime, timezone

import numpy as np
import pandas as pd


# ══════════════════════════════════════════════════════════════════════════════
# Standard indicators
# ══════════════════════════════════════════════════════════════════════════════

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()

def dema(series: pd.Series, period: int) -> pd.Series:
    """Double EMA — reduced lag vs plain EMA."""
    e = ema(series, period)
    return 2 * e - ema(e, period)

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    return 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Returns (macd_line, signal_line, histogram)."""
    m   = ema(series, fast) - ema(series, slow)
    sig = ema(m, signal)
    return m, sig, m - sig

def stochastic(high, low, close, k=14, d=3):
    lo = low.rolling(k).min()
    hi = high.rolling(k).max()
    pct_k = 100 * (close - lo) / (hi - lo).replace(0, np.nan)
    return pct_k, pct_k.rolling(d).mean()

def atr(high, low, close, period: int = 14) -> pd.Series:
    pc = close.shift(1)
    tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()

def bollinger_bands(series, period: int = 20, std_dev: float = 2.0):
    m = sma(series, period)
    s = series.rolling(period).std()
    return m + std_dev * s, m, m - std_dev * s

def adx(high, low, close, period: int = 14):
    """Returns (ADX, +DI, -DI). ADX > 25 = trending (research-verified: use as confluence)."""
    ph, pl, pc = high.shift(1), low.shift(1), close.shift(1)
    dm_pos = (high - ph).clip(lower=0)
    dm_neg = (pl - low).clip(lower=0)
    cond   = dm_pos > dm_neg
    dm_pos = dm_pos.where(cond, 0)
    dm_neg = dm_neg.where(~cond, 0)
    atr_s  = atr(high, low, close, period)
    di_pos = 100 * ema(dm_pos, period) / atr_s.replace(0, np.nan)
    di_neg = 100 * ema(dm_neg, period) / atr_s.replace(0, np.nan)
    dx     = 100 * (di_pos - di_neg).abs() / (di_pos + di_neg).replace(0, np.nan)
    return ema(dx, period), di_pos, di_neg

def obv(close, volume) -> pd.Series:
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (direction * volume).cumsum()

def volume_oscillator(volume, fast: int = 5, slow: int = 20) -> pd.Series:
    return ema(volume, fast) - ema(volume, slow)

def keltner_channel(high, low, close, period: int = 20, mult: float = 2.0):
    mid = ema(close, period)
    a   = atr(high, low, close, period)
    return mid + mult * a, mid, mid - mult * a


# ══════════════════════════════════════════════════════════════════════════════
# ICT / Smart Money Concepts
# ══════════════════════════════════════════════════════════════════════════════

def swing_points(df: pd.DataFrame, n: int = 5) -> tuple[pd.Series, pd.Series]:
    """
    Identify swing highs and swing lows.
    A swing high is the highest high in a window of n candles on each side.
    Returns (swing_highs, swing_lows) — NaN everywhere except at swing points.

    Vectorized via a centered rolling window: bar i is a swing high when its
    high equals the max of [i-n, i+n], a swing low when its low equals the min
    of that window. Behaviour is identical to the old per-bar Python loop, but
    runs in one pandas pass — the loop version was recomputed over the full
    history every backtest bar, making the backtester effectively O(n²).
    """
    win = 2 * n + 1
    roll_max = df["high"].rolling(win, center=True).max()
    roll_min = df["low"].rolling(win, center=True).min()
    highs = df["high"].where(df["high"] == roll_max)
    lows  = df["low"].where(df["low"]  == roll_min)
    return highs, lows


def market_structure_bias(df: pd.DataFrame, n: int = 5) -> int:
    """
    Higher-timeframe bias via Break of Structure (BOS).
    Uses a majority-vote over the last 4 swing pairs so the bias stays
    valid during shallow pullbacks (the ICT retest entry scenario).

    Scoring (each pair contributes 1 bullish or 1 bearish vote):
      - swing_high[i] > swing_high[i-1]  → +1 bull
      - swing_low[i]  > swing_low[i-1]   → +1 bull
      - swing_high[i] < swing_high[i-1]  → +1 bear
      - swing_low[i]  < swing_low[i-1]   → +1 bear
    Need ≥3 of 4 votes in one direction to declare a trend.
    Falls back to 2-point check if fewer than 3 swings available.
    Returns 1 (bullish), -1 (bearish), 0 (unclear / choppy).
    """
    sh, sl = swing_points(df, n)
    swing_highs = sh.dropna().values
    swing_lows  = sl.dropna().values

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return 0

    # 2-point fallback when not enough history
    if len(swing_highs) < 3 or len(swing_lows) < 3:
        hh = swing_highs[-1] > swing_highs[-2]
        hl = swing_lows[-1]  > swing_lows[-2]
        lh = swing_highs[-1] < swing_highs[-2]
        ll = swing_lows[-1]  < swing_lows[-2]
        if hh and hl: return 1
        if lh and ll: return -1
        return 0

    # Majority vote over last min(4, available) pairs
    pairs = min(len(swing_highs) - 1, len(swing_lows) - 1, 4)
    bull_votes = bear_votes = 0
    for k in range(1, pairs + 1):
        if swing_highs[-k] > swing_highs[-(k+1)]: bull_votes += 1
        elif swing_highs[-k] < swing_highs[-(k+1)]: bear_votes += 1
        if swing_lows[-k]  > swing_lows[-(k+1)]:  bull_votes += 1
        elif swing_lows[-k]  < swing_lows[-(k+1)]:  bear_votes += 1

    threshold = max(pairs, 3)  # need ≥3 votes to declare direction
    if bull_votes >= threshold: return 1
    if bear_votes >= threshold: return -1
    return 0


def find_order_blocks(df: pd.DataFrame, direction: int,
                      lookback: int = 100) -> list[dict]:
    """
    ICT Order Blocks:
      Bullish OB = last bearish candle before a bullish impulse move
      Bearish OB = last bullish candle before a bearish impulse move

    The impulse just needs to close in the right direction — removing the
    'bigger than OB range' condition which almost never fires on real 4H data.
    Only returns unmitigated OBs (price hasn't broken clean through them).
    """
    obs  = []
    data = df.tail(lookback).reset_index(drop=True)

    for i in range(1, len(data) - 1):
        c = data.iloc
        if direction == 1:
            is_ob_candle = c[i]["close"] < c[i]["open"]      # bearish candle
            impulse_next = c[i+1]["close"] > c[i+1]["open"]  # followed by bullish
            if is_ob_candle and impulse_next:
                zone = {"high": c[i]["high"], "low": c[i]["low"],
                        "idx": i, "type": "bullish_ob"}
                if not _ob_mitigated(data, zone, i + 2, direction):
                    obs.append(zone)
        else:
            is_ob_candle = c[i]["close"] > c[i]["open"]      # bullish candle
            impulse_next = c[i+1]["close"] < c[i+1]["open"]  # followed by bearish
            if is_ob_candle and impulse_next:
                zone = {"high": c[i]["high"], "low": c[i]["low"],
                        "idx": i, "type": "bearish_ob"}
                if not _ob_mitigated(data, zone, i + 2, direction):
                    obs.append(zone)

    return obs[-8:]   # keep the 8 most recent unmitigated OBs


def _ob_mitigated(data: pd.DataFrame, zone: dict, from_idx: int, direction: int) -> bool:
    """
    Return True only when the zone is fully consumed — price traded clean through it.
    Bullish OB: mitigated when any future low goes below the OB's LOW (zone destroyed).
    Bearish OB: mitigated when any future high goes above the OB's HIGH (zone destroyed).
    Price re-entering the zone without breaking through = still valid (the trade setup).
    """
    if from_idx >= len(data):
        return False
    future = data.iloc[from_idx:]
    if direction == 1:
        return (future["low"] < zone["low"]).any()
    else:
        return (future["high"] > zone["high"]).any()


def find_fair_value_gaps(df: pd.DataFrame, direction: int,
                         lookback: int = 50) -> list[dict]:
    """
    ICT Fair Value Gap (FVG) — 3-candle imbalance:
      Bullish FVG: candle[i].low  > candle[i-2].high  (unfilled gap up)
      Bearish FVG: candle[i].high < candle[i-2].low   (unfilled gap down)

    Only returns unfilled (unmitigated) FVGs.
    """
    fvgs = []
    data = df.tail(lookback).reset_index(drop=True)

    for i in range(2, len(data)):
        if direction == 1:
            bottom = data["high"].iloc[i - 2]
            top    = data["low"].iloc[i]
            if top > bottom:
                zone = {"top": top, "bottom": bottom, "idx": i}
                if not _fvg_filled(data, zone, i + 1, direction):
                    fvgs.append(zone)
        else:
            top    = data["low"].iloc[i - 2]
            bottom = data["high"].iloc[i]
            if bottom < top:
                zone = {"top": top, "bottom": bottom, "idx": i}
                if not _fvg_filled(data, zone, i + 1, direction):
                    fvgs.append(zone)

    return fvgs[-5:]


def _fvg_filled(data, zone, from_idx, direction) -> bool:
    if from_idx >= len(data):
        return False
    future = data.iloc[from_idx:]
    if direction == 1:
        return (future["low"] < zone["bottom"]).any()
    else:
        return (future["high"] > zone["top"]).any()


def price_in_zone(price: float, zones: list[dict],
                  buffer: float = 0.0) -> tuple[bool, dict | None]:
    """
    Check if current price falls within any zone (OB or FVG).
    buffer: expand each zone by this much on BOTH sides (ATR-based approach margin).
    """
    for z in zones:
        lo = z.get("low", z.get("bottom", 0)) - buffer
        hi = z.get("high", z.get("top", 0)) + buffer
        if lo <= price <= hi:
            return True, z
    return False, None


def detect_liquidity_sweep(df: pd.DataFrame, direction: int,
                            n: int = 5) -> bool:
    """
    Liquidity sweep: price spikes through a recent swing point then closes back.
    Research note: Asian range sweep + NY reversal has high win rate only with
    killzone + confluence filters (not standalone).

    Bullish sweep: last candle's low is below a prior swing low, but closed above it.
    Bearish sweep: last candle's high is above a prior swing high, but closed below it.
    """
    sh, sl = swing_points(df.iloc[:-1], n)
    last = df.iloc[-1]

    if direction == 1:
        prior_lows = sl.dropna()
        if prior_lows.empty:
            return False
        nearest_low = float(prior_lows.iloc[-1])
        return last["low"] < nearest_low < last["close"]
    else:
        prior_highs = sh.dropna()
        if prior_highs.empty:
            return False
        nearest_high = float(prior_highs.iloc[-1])
        return last["close"] < nearest_high < last["high"]


def next_structure_target(df: pd.DataFrame, direction: int, n: int = 5) -> float | None:
    """
    Find the NEAREST structural target beyond current price — the first swing
    high above (bullish TP) or first swing low below (bearish TP). Used for R:R.

    Uses the closest qualifying level (min high above / max low below) rather
    than the oldest one in the series: the oldest qualifying swing can sit near
    the start of history, producing a distant target and nonsensical R:R (e.g.
    40:1). The nearest level is the realistic first objective price reaches, and
    it depends only on recent structure — so a bounded backtest window reproduces
    it. Falls back to 3× ATR when no structural level qualifies.
    """
    sh, sl = swing_points(df, n)
    price  = float(df["close"].iloc[-1])

    if direction == 1:
        above = sh.dropna()
        above = above[above > price]
        if not above.empty:
            return float(above.min())          # nearest resistance above price
        return price + float(atr(df["high"], df["low"], df["close"]).iloc[-1]) * 3
    else:
        below = sl.dropna()
        below = below[below < price]
        if not below.empty:
            return float(below.max())          # nearest support below price
        return price - float(atr(df["high"], df["low"], df["close"]).iloc[-1]) * 3


# ══════════════════════════════════════════════════════════════════════════════
# ICT Killzones  (research-verified: peak window 14:00-16:00 UTC)
# ══════════════════════════════════════════════════════════════════════════════

def in_killzone(ts: datetime | None = None) -> tuple[bool, str]:
    """
    Returns (True, zone_name) when current UTC time is inside an ICT killzone.

    Killzones (UTC):
      Asian   : 23:00 – 02:00  (mark Asian range for sweep setups)
      London  : 07:00 – 10:00  (institutional breakouts)
      NY      : 12:00 – 15:00  (sweeps + reversals)
      Peak    : 14:00 – 16:00  (London-NY overlap — highest verified volume)

    Note: DST can shift times ±1h. Bot uses UTC throughout to be DST-agnostic.
    """
    if ts is None:
        ts = datetime.now(timezone.utc)
    h = ts.hour

    if h >= 23 or h < 2:    return True, "Asian (23-02 UTC)"
    if 7 <= h < 10:          return True, "London (07-10 UTC)"
    if 12 <= h < 15:         return True, "NY (12-15 UTC)"
    if 15 <= h < 16:         return True, "London-NY Peak (15-16 UTC)"
    return False, ""


def asian_range(df: pd.DataFrame) -> tuple[float, float] | None:
    """
    Return (high, low) of the most recent Asian session (23:00-02:00 UTC).
    Used to identify liquidity pools that can be swept by London/NY.
    """
    asian = df[df.index.hour.isin([23, 0, 1])]
    if asian.empty:
        return None
    return float(asian["high"].max()), float(asian["low"].min())


# ══════════════════════════════════════════════════════════════════════════════
# Candlestick patterns
# ══════════════════════════════════════════════════════════════════════════════

def bullish_engulfing(open_: pd.Series, close: pd.Series) -> pd.Series:
    prev_bear = close.shift(1) < open_.shift(1)
    engulf    = (open_ < close.shift(1)) & (close > open_.shift(1)) & (close > open_)
    return prev_bear & engulf

def bearish_engulfing(open_: pd.Series, close: pd.Series) -> pd.Series:
    prev_bull = close.shift(1) > open_.shift(1)
    engulf    = (open_ > close.shift(1)) & (close < open_.shift(1)) & (close < open_)
    return prev_bull & engulf

def is_pin_bar(open_: pd.Series, high: pd.Series,
               low: pd.Series, close: pd.Series, direction: int) -> pd.Series:
    body       = (close - open_).abs()
    lower_wick = open_.combine(close, min) - low
    upper_wick = high - open_.combine(close, max)
    if direction == 1:
        return (lower_wick > 2 * body) & (upper_wick < body)
    return (upper_wick > 2 * body) & (lower_wick < body)


# ══════════════════════════════════════════════════════════════════════════════
# Data quality
# ══════════════════════════════════════════════════════════════════════════════

def pip_value(pair: str) -> float:
    return 0.01 if "JPY" in pair else 0.0001


def data_quality_score(df: pd.DataFrame) -> float:
    if df is None or df.empty:
        return 0.0
    cols   = ["open", "high", "low", "close", "volume"]
    checks = 0
    if not df[cols].isnull().any().any():            checks += 1
    if (df["high"] >= df["low"]).all():              checks += 1
    if ((df["high"] >= df["open"]) &
        (df["high"] >= df["close"])).all():          checks += 1
    if ((df["low"]  <= df["open"]) &
        (df["low"]  <= df["close"])).all():          checks += 1
    if df.index.is_monotonic_increasing:             checks += 1
    return checks / 5
