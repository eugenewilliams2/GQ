"""
Market data fetching via yfinance.
Returns OHLCV DataFrames ready for indicator calculation.
"""

import logging
from datetime import datetime

import pandas as pd
import yfinance as yf

from forex_bot import config

logger = logging.getLogger(__name__)


def fetch_ohlcv(pair: str,
                period: str  = config.CANDLE_LOOKBACK,
                interval: str = config.CANDLE_INTERVAL) -> pd.DataFrame:
    """
    Download OHLCV data for one forex pair.
    Returns a clean DataFrame with columns: open high low close volume.
    Returns None if download fails.
    """
    try:
        ticker = yf.Ticker(pair)
        df = ticker.history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            logger.warning("No data returned for %s", pair)
            return None
        df.columns = [c.lower() for c in df.columns]
        df = df[["open", "high", "low", "close", "volume"]].copy()
        df.index = pd.to_datetime(df.index, utc=True)
        df.dropna(inplace=True)
        return df
    except Exception as exc:
        logger.error("fetch_ohlcv(%s): %s", pair, exc)
        return None


def fetch_all_pairs(pairs: list[str] = config.PAIRS,
                    period: str = config.CANDLE_LOOKBACK,
                    interval: str = config.CANDLE_INTERVAL) -> dict[str, pd.DataFrame]:
    """Fetch OHLCV for every pair in the list. Returns {pair: DataFrame}."""
    results = {}
    for pair in pairs:
        df = fetch_ohlcv(pair, period=period, interval=interval)
        if df is not None:
            results[pair] = df
            logger.debug("Fetched %d candles for %s", len(df), pair)
    return results


def get_current_price(pair: str) -> float | None:
    """Return the most recent close price for a pair."""
    df = fetch_ohlcv(pair, period="5d", interval="1h")
    if df is not None and not df.empty:
        return float(df["close"].iloc[-1])
    return None
