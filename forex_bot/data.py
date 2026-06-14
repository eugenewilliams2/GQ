"""
Data loading with on-disk caching.

yfinance throttles aggressively and only serves ~730 days of hourly FX, so we
fetch once and cache to disk. Every backtest/comparison then runs offline and
fast. This is research data (free, hourly, no real volume) — adequate for
relative strategy comparison, NOT for anything you'd trade real money on.
"""

from __future__ import annotations
import os
import pickle
import time
import warnings

import pandas as pd

from forex_bot import config

CACHE_PATH = os.path.join(os.path.dirname(__file__), os.pardir, ".gq_data_cache.pkl")


def _resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    return df.resample("4h").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"}).dropna()


def _download(pair: str, start: str, end: str, retries: int = 3) -> pd.DataFrame | None:
    import yfinance as yf
    for _ in range(retries):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = yf.download(pair, start=start, end=end, interval="1h",
                             auto_adjust=True, progress=False)
        if df is not None and not df.empty:
            if isinstance(df.columns, pd.MultiIndex):
                df = df.droplevel(1, axis=1)
            df.columns = [str(c).lower() for c in df.columns]
            df = df[["open", "high", "low", "close", "volume"]].dropna()
            df.index = pd.to_datetime(df.index, utc=True)
            return df
        time.sleep(5)
    return None


def load(pairs: list[str] | None = None,
         start: str = "2025-01-01",
         end: str = "2026-06-01",
         refresh: bool = False) -> dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
    """
    Returns {pair: (df_1h, df_4h)}. Uses the on-disk cache unless refresh=True or
    the cached pair set doesn't cover what's requested.
    """
    pairs = pairs or config.PAIRS
    cache: dict = {}
    if not refresh and os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "rb") as f:
                cache = pickle.load(f)
        except Exception:
            cache = {}

    missing = [p for p in pairs if p not in cache]
    if missing:
        for p in missing:
            df = _download(p, start, end)
            if df is not None:
                cache[p] = (df, _resample_4h(df))
        with open(CACHE_PATH, "wb") as f:
            pickle.dump(cache, f)

    return {p: cache[p] for p in pairs if p in cache}
