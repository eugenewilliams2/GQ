"""
Market data — OHLCV fetcher with multi-timeframe (HTF + LTF) support.
"""

import logging

import pandas as pd
import yfinance as yf

from forex_bot import config

logger = logging.getLogger(__name__)


def _download(ticker: str, period: str, interval: str) -> pd.DataFrame | None:
    try:
        t  = yf.Ticker(ticker)
        df = t.history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            logger.warning("No data for %s", ticker)
            return None
        df.columns = [c.lower() for c in df.columns]
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        df.index = pd.to_datetime(df.index, utc=True)
        return df
    except Exception as exc:
        logger.error("fetch(%s): %s", ticker, exc)
        return None


def fetch_ohlcv(pair: str,
                period: str   = config.CANDLE_LOOKBACK_LTF,
                interval: str = config.CANDLE_INTERVAL_LTF) -> pd.DataFrame | None:
    return _download(pair, period, interval)


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
    Fetch both timeframes for all pairs.
    Returns (ltf_data, htf_data) where:
      ltf = 1H candles (entry timing)
      htf = 4H candles (market structure / bias)
    """
    ltf, htf = {}, {}
    for p in pairs:
        df_l = _download(p, config.CANDLE_LOOKBACK_LTF, config.CANDLE_INTERVAL_LTF)
        df_h = _download(p, config.CANDLE_LOOKBACK_HTF, config.CANDLE_INTERVAL_HTF)
        if df_l is not None: ltf[p] = df_l
        if df_h is not None: htf[p] = df_h
        if df_l is not None or df_h is not None:
            logger.debug("%s  LTF=%s  HTF=%s",
                         p,
                         len(df_l) if df_l is not None else "—",
                         len(df_h) if df_h is not None else "—")
    return ltf, htf


def fetch_dxy(period: str = "60d") -> pd.DataFrame | None:
    """
    US Dollar Index — used as intermarket confluence filter only.
    Research note: DXY has structural bias (EUR = 57.6% weight) so treated
    as confluence, NOT a leading indicator (claim was adversarially refuted).
    """
    return _download("DX-Y.NYB", period, "1d")
