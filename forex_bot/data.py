"""
Data loading with on-disk caching, over a pluggable source (see datasource.py).

Fetch once per (source, interval), cache to disk, then every backtest runs
offline and fast. The cache key includes the source and interval so switching
providers/timeframes doesn't collide. This is research data — adequate for
relative strategy comparison, not a basis for risking real money.
"""

from __future__ import annotations
import os
import pickle
import time

import pandas as pd

from forex_bot import config
from forex_bot.datasource import DataSource, get_source, bars_per_year  # noqa: F401

_CACHE_DIR = os.path.join(os.path.dirname(__file__), os.pardir)


def _cache_path(source: str, interval: str) -> str:
    return os.path.join(_CACHE_DIR, f".gq_cache_{source}_{interval}.pkl")


def _resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    return df.resample("4h").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum"}).dropna()


def load(pairs: list[str] | None = None,
         start: str = "2020-01-01",
         end: str = "2026-06-01",
         source: str | DataSource = "yfinance",
         interval: str = "1h",
         refresh: bool = False,
         retries: int = 3) -> dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
    """
    Returns {pair: (df_primary, df_4h)}. df_4h is a 4H resample for intraday data,
    else a copy of the primary frame (unused by current strategies). Uses the
    on-disk cache for the (source, interval) pair unless refresh=True.
    """
    pairs = pairs or config.PAIRS
    src = source if isinstance(source, DataSource) else get_source(source, interval)
    src_name, ivl = src.name, src.interval
    path = _cache_path(src_name, ivl)

    cache: dict = {}
    if not refresh and os.path.exists(path):
        try:
            with open(path, "rb") as f:
                cache = pickle.load(f)
        except Exception:
            cache = {}

    missing = [p for p in pairs if p not in cache]
    if missing:
        for p in missing:
            df = None
            for _ in range(retries):
                df = src.fetch(p, start, end)
                if df is not None and len(df):
                    break
                time.sleep(3)
            if df is not None and len(df):
                df4 = _resample_4h(df) if ivl in ("1h", "4h") else df.copy()
                cache[p] = (df, df4)
        with open(path, "wb") as f:
            pickle.dump(cache, f)

    return {p: cache[p] for p in pairs if p in cache}
