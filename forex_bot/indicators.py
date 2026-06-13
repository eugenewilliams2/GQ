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
    """
    highs = pd.Series(np.nan, index=df.index)
    lows  = pd.Series(np.nan, index=df.index)
    for i in range(n, len(df) - n):
        window_h = df["high"].iloc[i - n : i + n + 1]
        window_l = df["low"].iloc[i - n : i + n + 1]
        if df["high"].iloc[i] == window_h.max():
            highs.iloc[i] = df["high"].iloc[i]
        if df["low"].iloc[i] == window_l.min():
            lows.iloc[i] = df["low"].iloc[i]
    return highs, lows


def market_structure_bias(df: pd.DataFrame, n: int = 5) -> int:
    """
    Higher-timeframe bias via Break of Structure (BOS).
    Bullish = most recent swing high AND swing low are both higher than previous.
    Bearish = most recent swing high AND swing low are both lower than previous.
    Returns  1 (bullish), -1 (bearish), 0 (unclear / choppy).

    Uses 2-point confirmation (last vs previous swing) rather than 3, which
    is still a valid BOS signal and fires frequently enough on real 4H data.
    """
    sh, sl = swing_points(df, n)
    swing_highs = sh.dropna().values
    swing_lows  = sl.dropna().values

    if len(swing_highs) < 2 or len(swing_lows) < 2:
        return 0

    hh = swing_highs[-1] > swing_highs[-2]
    hl = swing_lows[-1]  > swing_lows[-2]
    lh = swing_highs[-1] < swing_highs[-2]
    ll = swing_lows[-1]  < swing_lows[-2]

    if hh and hl: return 1
    if lh and ll: return -1
    return 0


def find_order_blocks(df: pd.DataFrame, direction: int,
                      lookback: int = 80) -> list[dict]:
    """
    ICT Order Blocks:
      Bullish OB = last bearish candle before a strong bullish impulse move
      Bearish OB = last bullish candle before a strong bearish impulse move

    Only returns unmitigated OBs (price hasn't returned to them since).
    """
    obs  = []
    data = df.tail(lookback).reset_index(drop=True)

    for i in range(1, len(data) - 1):
        c = data.iloc
        if direction == 1:
            is_ob_candle  = c[i]["close"] < c[i]["open"]           # bearish candle
            impulse_next  = c[i+1]["close"] > c[i+1]["open"]       # followed by bullish
            strong_move   = (c[i+1]["close"] - c[i+1]["open"]) > \
                            (c[i]["high"] - c[i]["low"])            # bigger than OB body
            if is_ob_candle and impulse_next and strong_move:
                zone = {"high": c[i]["high"], "low": c[i]["low"],
                        "idx": i, "type": "bullish_ob"}
                # unmitigated = price never dipped below OB high after the move
                if not _ob_mitigated(data, zone, i + 2, direction):
                    obs.append(zone)
        else:
            is_ob_candle  = c[i]["close"] > c[i]["open"]
            impulse_next  = c[i+1]["close"] < c[i+1]["open"]
            strong_move   = (c[i+1]["open"] - c[i+1]["close"]) > \
                            (c[i]["high"] - c[i]["low"])
            if is_ob_candle and impulse_next and strong_move:
                zone = {"high": c[i]["high"], "low": c[i]["low"],
                        "idx": i, "type": "bearish_ob"}
                if not _ob_mitigated(data, zone, i + 2, direction):
                    obs.append(zone)

    return obs[-5:]   # keep the 5 most recent unmitigated OBs


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


def price_in_zone(price: float, zones: list[dict]) -> tuple[bool, dict | None]:
    """Check if current price falls within any zone (OB or FVG)."""
    for z in zones:
        lo = z.get("low", z.get("bottom", 0))
        hi = z.get("high", z.get("top", 0))
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
    Find the next significant swing high (bullish TP) or swing low (bearish TP)
    beyond current price. Used for R:R calculation.
    """
    sh, sl = swing_points(df, n)
    price  = float(df["close"].iloc[-1])

    if direction == 1:
        highs = sh.dropna()
        candidates = highs[highs > price]
        if not candidates.empty:
            return float(candidates.iloc[0])
        # Fallback: 3× ATR above price
        return price + float(atr(df["high"], df["low"], df["close"]).iloc[-1]) * 3
    else:
        lows = sl.dropna()
        candidates = lows[lows < price]
        if not candidates.empty:
            return float(candidates.iloc[-1])
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
