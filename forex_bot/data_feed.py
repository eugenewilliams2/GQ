"""
Market data — OHLCV fetcher with multi-timeframe (HTF + LTF) support.

Note: Yahoo Finance does NOT offer a native 4h interval, and only serves
intraday (1h) data for roughly the trailing 730 days. We therefore fetch
1h data and resample it to 4h locally for the higher-timeframe structure.
"""

import logging
import warnings
from datetime import datetime, timedelta, timezone

import pandas as pd
import yfinance as yf

from forex_bot import config

logger = logging.getLogger(__name__)

# Yahoo Finance valid intervals (4h is NOT one of them)
_YF_INTRADAY_MAX_DAYS = 730


def _flatten_columns(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Newer yfinance (>=0.2.40) returns MultiIndex columns — flatten them."""
    if isinstance(df.columns, pd.MultiIndex):
        lvl1 = df.columns.get_level_values(1)
        if ticker in set(lvl1):
            df = df.xs(ticker, axis=1, level=1)
        else:
            df = df.droplevel(1, axis=1)
    return df


def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample 1h OHLCV up to a higher timeframe (e.g. '4h')."""
    return df.resample(rule).agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()


def _download_1h(ticker: str, lookback_days: int) -> pd.DataFrame | None:
    """Download 1h OHLCV, clamping the window to Yahoo's 730-day intraday limit."""
    lookback_days = min(lookback_days, _YF_INTRADAY_MAX_DAYS - 2)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = yf.download(ticker, period=f"{lookback_days}d",
                             interval="1h", auto_adjust=True, progress=False)

        if df is None or df.empty:
            logger.warning("No 1h data for %s (rate-limited or unavailable)", ticker)
            return None

        df = _flatten_columns(df, ticker)
        df.columns = [str(c).lower() for c in df.columns]

        needed = {"open", "high", "low", "close", "volume"}
        if not needed.issubset(df.columns):
            logger.warning("%s: missing columns %s", ticker, needed - set(df.columns))
            return None

        df = df[["open", "high", "low", "close", "volume"]].dropna()
        df.index = pd.to_datetime(df.index, utc=True)
        return df if not df.empty else None

    except Exception as exc:
        logger.error("fetch(%s): %s", ticker, exc)
        return None


def _days_from_lookback(lookback: str, default: int) -> int:
    """Parse '60d' / '180d' style lookback strings into integer days."""
    try:
        return int(str(lookback).lower().rstrip("d"))
    except (ValueError, AttributeError):
        return default


def fetch_ohlcv(pair: str,
                period: str   = config.CANDLE_LOOKBACK_LTF,
                interval: str = config.CANDLE_INTERVAL_LTF) -> pd.DataFrame | None:
    days = _days_from_lookback(period, 60)
    return _download_1h(pair, days)


def fetch_all_pairs(pairs: list[str] = config.PAIRS) -> dict[str, pd.DataFrame]:
    """Fetch LTF (1H) data for all pairs."""
    out = {}
    for p in pairs:
        df = fetch_ohlcv(p)
        if df is not None:
            out[p] = df
    return out


def fetch_all_pairs_mtf(
    pairs: list[str] = config.PAIRS,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """
    Fetch 1h data once per pair and derive both timeframes:
      ltf = 1H candles (entry timing)
      htf = 4H candles, resampled locally (market structure / bias)
    """
    htf_days = _days_from_lookback(config.CANDLE_LOOKBACK_HTF, 180)
    ltf, htf = {}, {}

    for p in pairs:
        df_1h = _download_1h(p, htf_days)
        if df_1h is None:
            continue
        ltf[p] = df_1h
        htf[p] = _resample(df_1h, "4h")
        logger.debug("%s  LTF(1h)=%d  HTF(4h)=%d", p, len(ltf[p]), len(htf[p]))

    if not ltf:
        logger.error(
            "No market data fetched for any pair.\n"
            "  • Update yfinance:  pip install -U yfinance\n"
            "  • Check internet connection\n"
            "  • Yahoo Finance rate-limits — wait 30-60s and retry"
        )
    return ltf, htf


def fetch_dxy(period: str = "60d") -> pd.DataFrame | None:
    """
    US Dollar Index — used as intermarket confluence filter only.
    Research note: DXY has structural bias (EUR = 57.6% weight) so treated
    as confluence, NOT a leading indicator (claim was adversarially refuted).
    """
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = yf.download("DX-Y.NYB", period=period, interval="1d",
                             auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        df = _flatten_columns(df, "DX-Y.NYB")
        df.columns = [str(c).lower() for c in df.columns]
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        df.index = pd.to_datetime(df.index, utc=True)
        return df if not df.empty else None
    except Exception as exc:
        logger.error("fetch(DXY): %s", exc)
        return None
