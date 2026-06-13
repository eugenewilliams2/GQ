"""
Market data — OHLCV fetcher with multi-timeframe (HTF + LTF) support.
"""

import logging
import warnings

import pandas as pd
import yfinance as yf

from forex_bot import config

logger = logging.getLogger(__name__)


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Newer yfinance (>=0.2.40) returns MultiIndex columns — flatten them."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _download(ticker: str, period: str = None, interval: str = "1h",
              start: str = None, end: str = None) -> pd.DataFrame | None:
    try:
        kwargs = dict(interval=interval, auto_adjust=True, progress=False)
        if start:
            kwargs["start"] = start
            if end:
                kwargs["end"] = end
        else:
            kwargs["period"] = period

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = yf.download(ticker, **kwargs)

        if df is None or df.empty:
            logger.warning("No data returned for %s (possibly delisted or rate-limited)", ticker)
            return None

        df = _flatten_columns(df)
        df.columns = [c.lower() for c in df.columns]

        needed = {"open", "high", "low", "close", "volume"}
        missing = needed - set(df.columns)
        if missing:
            logger.warning("%s: missing columns %s", ticker, missing)
            return None

        df = df[["open", "high", "low", "close", "volume"]].dropna()
        df.index = pd.to_datetime(df.index, utc=True)

        if df.empty:
            logger.warning("All rows dropped after dropna for %s", ticker)
            return None

        return df

    except Exception as exc:
        logger.error("fetch(%s): %s", ticker, exc)
        return None


def fetch_ohlcv(pair: str,
                period: str   = config.CANDLE_LOOKBACK_LTF,
                interval: str = config.CANDLE_INTERVAL_LTF) -> pd.DataFrame | None:
    return _download(pair, period=period, interval=interval)


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
        df_l = _download(p, period=config.CANDLE_LOOKBACK_LTF,
                         interval=config.CANDLE_INTERVAL_LTF)
        df_h = _download(p, period=config.CANDLE_LOOKBACK_HTF,
                         interval=config.CANDLE_INTERVAL_HTF)
        if df_l is not None:
            ltf[p] = df_l
        if df_h is not None:
            htf[p] = df_h
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
    return _download("DX-Y.NYB", period=period, interval="1d")
