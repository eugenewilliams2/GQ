"""
Pure-pandas/numpy technical indicator library.
All functions accept a pandas Series and return a Series aligned to the same index.
"""

import numpy as np
import pandas as pd


# ── Trend ────────────────────────────────────────────────────────────────────

def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def wma(series: pd.Series, period: int) -> pd.Series:
    weights = np.arange(1, period + 1, dtype=float)
    return series.rolling(period).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)


def dema(series: pd.Series, period: int) -> pd.Series:
    """Double EMA — reduces lag vs plain EMA."""
    e1 = ema(series, period)
    return 2 * e1 - ema(e1, period)


# ── Momentum ─────────────────────────────────────────────────────────────────

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Returns (macd_line, signal_line, histogram)."""
    fast_ema    = ema(series, fast)
    slow_ema    = ema(series, slow)
    macd_line   = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    histogram   = macd_line - signal_line
    return macd_line, signal_line, histogram


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
               k_period: int = 14, d_period: int = 3):
    """Returns (%K, %D)."""
    lowest  = low.rolling(k_period).min()
    highest = high.rolling(k_period).max()
    k = 100 * (close - lowest) / (highest - lowest).replace(0, np.nan)
    d = k.rolling(d_period).mean()
    return k, d


def cci(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 20) -> pd.Series:
    """Commodity Channel Index."""
    typical   = (high + low + close) / 3
    mean_dev  = typical.rolling(period).apply(
        lambda x: np.mean(np.abs(x - x.mean())), raw=True
    )
    return (typical - sma(typical, period)) / (0.015 * mean_dev.replace(0, np.nan))


def williams_r(high: pd.Series, low: pd.Series, close: pd.Series,
               period: int = 14) -> pd.Series:
    highest = high.rolling(period).max()
    lowest  = low.rolling(period).min()
    return -100 * (highest - close) / (highest - lowest).replace(0, np.nan)


# ── Volatility ────────────────────────────────────────────────────────────────

def atr(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def bollinger_bands(series: pd.Series, period: int = 20, std_dev: float = 2.0):
    """Returns (upper, middle, lower)."""
    middle = sma(series, period)
    std    = series.rolling(period).std()
    upper  = middle + std_dev * std
    lower  = middle - std_dev * std
    return upper, middle, lower


def keltner_channel(high: pd.Series, low: pd.Series, close: pd.Series,
                    period: int = 20, mult: float = 2.0):
    """Returns (upper, middle, lower)."""
    middle = ema(close, period)
    a      = atr(high, low, close, period)
    return middle + mult * a, middle, middle - mult * a


# ── Trend strength ────────────────────────────────────────────────────────────

def adx(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> pd.Series:
    """
    Average Directional Index.
    ADX > 25 = trending market; < 20 = ranging.
    """
    prev_high  = high.shift(1)
    prev_low   = low.shift(1)
    prev_close = close.shift(1)

    dm_pos = (high - prev_high).clip(lower=0)
    dm_neg = (prev_low - low).clip(lower=0)
    # Resolve ties — whichever is larger wins; equal → 0
    cond   = dm_pos > dm_neg
    dm_pos = dm_pos.where(cond, 0)
    dm_neg = dm_neg.where(~cond, 0)

    tr_series = atr(high, low, close, period)
    di_pos    = 100 * ema(dm_pos, period) / tr_series.replace(0, np.nan)
    di_neg    = 100 * ema(dm_neg, period) / tr_series.replace(0, np.nan)
    dx        = 100 * (di_pos - di_neg).abs() / (di_pos + di_neg).replace(0, np.nan)
    return ema(dx, period), di_pos, di_neg   # adx, +DI, -DI


# ── Volume ────────────────────────────────────────────────────────────────────

def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (direction * volume).cumsum()


def volume_oscillator(volume: pd.Series,
                      fast: int = 5, slow: int = 20) -> pd.Series:
    """Fast vs slow volume MA — positive = volume expanding."""
    return ema(volume, fast) - ema(volume, slow)


# ── Candlestick patterns ──────────────────────────────────────────────────────

def bullish_engulfing(open_: pd.Series, close: pd.Series) -> pd.Series:
    """Returns True where a bullish engulfing pattern is detected."""
    prev_bearish = close.shift(1) < open_.shift(1)
    engulf = (open_ < close.shift(1)) & (close > open_.shift(1)) & (close > open_)
    return prev_bearish & engulf


def bearish_engulfing(open_: pd.Series, close: pd.Series) -> pd.Series:
    prev_bullish = close.shift(1) > open_.shift(1)
    engulf = (open_ > close.shift(1)) & (close < open_.shift(1)) & (close < open_)
    return prev_bullish & engulf


def is_pin_bar(open_: pd.Series, high: pd.Series,
               low: pd.Series, close: pd.Series,
               direction: int) -> pd.Series:
    """
    Bullish pin bar (direction=1)  : long lower wick, small body near top.
    Bearish pin bar (direction=-1) : long upper wick, small body near bottom.
    """
    body      = (close - open_).abs()
    candle    = high - low
    lower_wick = open_.combine(close, min) - low
    upper_wick = high - open_.combine(close, max)
    if direction == 1:
        return (lower_wick > 2 * body) & (upper_wick < body) & (candle > 0)
    else:
        return (upper_wick > 2 * body) & (lower_wick < body) & (candle > 0)


# ── Utilities ─────────────────────────────────────────────────────────────────

def pip_value(pair: str) -> float:
    return 0.01 if "JPY" in pair else 0.0001


def data_quality_score(df: pd.DataFrame) -> float:
    """
    Return a 0–1 score for DataFrame quality.
    Checks: no NaN in OHLCV, OHLC ordering, monotonic timestamps.
    """
    if df is None or df.empty:
        return 0.0
    checks = 0
    total  = 5

    # 1. No NaN in OHLCV
    if not df[["open","high","low","close","volume"]].isnull().any().any():
        checks += 1
    # 2. High >= Low
    if (df["high"] >= df["low"]).all():
        checks += 1
    # 3. High >= Open and Close
    if ((df["high"] >= df["open"]) & (df["high"] >= df["close"])).all():
        checks += 1
    # 4. Low <= Open and Close
    if ((df["low"] <= df["open"]) & (df["low"] <= df["close"])).all():
        checks += 1
    # 5. Monotonically increasing timestamps
    if df.index.is_monotonic_increasing:
        checks += 1

    return checks / total
