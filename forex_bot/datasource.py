"""
Pluggable market-data sources.

The harness was data-blind to anything but yfinance hourly (no volume, 730-day
cap). This abstracts the source so you can compare providers and timeframes —
and, crucially, bring your OWN data (real tick-volume from Dukascopy/broker
exports) via the CSV source. Every source returns the same clean frame:
a UTC-indexed OHLCV DataFrame, lowercase columns.

  YFinanceSource  works here; supports 1d (years of history, momentum's best
                  timeframe) as well as 1h. FX still has no real volume on Yahoo.
  CSVSource       load <dir>/<PAIR>.csv — the way to get REAL volume into the
                  harness (Dukascopy, broker, Kaggle all export CSV).
  StooqSource     free, no key, daily FX — environment-dependent (may be blocked
                  behind proxies); best-effort.
"""

from __future__ import annotations
import glob
import os
import warnings
from abc import ABC, abstractmethod

import pandas as pd

# Trading bars per year, by interval — used to annualize Sharpe etc. correctly.
BARS_PER_YEAR = {"1h": 24 * 252, "4h": 6 * 252, "1d": 252, "1wk": 52}


def bars_per_year(interval: str) -> float:
    return BARS_PER_YEAR.get(interval, 24 * 252)


def _normalize(df: pd.DataFrame, ticker: str | None = None) -> pd.DataFrame | None:
    if df is None or len(df) == 0:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        lvl1 = df.columns.get_level_values(1)
        df = df.xs(ticker, axis=1, level=1) if ticker in set(lvl1) else df.droplevel(1, axis=1)
    df = df.rename(columns={c: str(c).lower() for c in df.columns})
    need = {"open", "high", "low", "close"}
    if not need.issubset(df.columns):
        return None
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    df.index = pd.to_datetime(df.index, utc=True)
    return df[~df.index.duplicated(keep="last")].sort_index() if len(df) else None


class DataSource(ABC):
    name: str
    interval: str = "1h"

    @abstractmethod
    def fetch(self, pair: str, start: str, end: str) -> pd.DataFrame | None:
        ...


class YFinanceSource(DataSource):
    name = "yfinance"

    def __init__(self, interval: str = "1h"):
        self.interval = interval

    def fetch(self, pair: str, start: str, end: str) -> pd.DataFrame | None:
        import yfinance as yf
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = yf.download(pair, start=start, end=end, interval=self.interval,
                             auto_adjust=True, progress=False)
        return _normalize(df, pair)


class CSVSource(DataSource):
    """Load <directory>/<PAIR>.csv (PAIR with '=X' stripped, case-insensitive).
    Auto-detects a date/time column for the index and OHLCV columns."""
    name = "csv"

    def __init__(self, directory: str = "data", interval: str = "1h"):
        self.directory = directory
        self.interval = interval

    def fetch(self, pair: str, start: str, end: str) -> pd.DataFrame | None:
        stem = pair.replace("=X", "")
        matches = [p for p in glob.glob(os.path.join(self.directory, "*"))
                   if os.path.splitext(os.path.basename(p))[0].lower() in
                   (stem.lower(), pair.lower())]
        if not matches:
            return None
        df = pd.read_csv(matches[0])
        df.columns = [str(c).lower() for c in df.columns]
        # find a datetime column
        dtcol = next((c for c in ("datetime", "date", "time", "timestamp") if c in df.columns), None)
        if dtcol is not None:
            df = df.set_index(pd.to_datetime(df[dtcol], utc=True, errors="coerce"))
        out = _normalize(df, pair)
        if out is None:
            return None
        s, e = pd.to_datetime(start, utc=True), pd.to_datetime(end, utc=True)
        return out.loc[(out.index >= s) & (out.index <= e)]


class StooqSource(DataSource):
    """Free, no-key daily FX via stooq CSV endpoint. May be blocked by proxies."""
    name = "stooq"
    interval = "1d"

    def fetch(self, pair: str, start: str, end: str) -> pd.DataFrame | None:
        import requests
        sym = pair.replace("=X", "").lower()
        try:
            r = requests.get(f"https://stooq.com/q/d/l/?s={sym}&i=d", timeout=20)
            if r.status_code != 200 or "," not in r.text[:50]:
                return None
            from io import StringIO
            df = pd.read_csv(StringIO(r.text))
        except Exception:
            return None
        if "Date" not in df.columns:
            return None
        df = df.set_index(pd.to_datetime(df["Date"], utc=True))
        out = _normalize(df, pair)
        if out is None:
            return None
        s, e = pd.to_datetime(start, utc=True), pd.to_datetime(end, utc=True)
        return out.loc[(out.index >= s) & (out.index <= e)]


class CoinbaseSource(DataSource):
    """Coinbase Exchange public candles — real exchange OHLCV + volume, no key.
    Products use the BTC-USD form (matches our crypto universe). Granularity is
    fixed by the API (no native 4h); paginated at 300 candles per request."""
    name = "coinbase"
    GRAN = {"1h": 3600, "6h": 21600, "1d": 86400}

    def __init__(self, interval: str = "1d"):
        self.interval = interval

    def fetch(self, pair: str, start: str, end: str) -> pd.DataFrame | None:
        import time as _t
        import requests
        gran = self.GRAN.get(self.interval)
        if gran is None:                       # e.g. 4h not offered by Coinbase
            return None
        s = int(pd.to_datetime(start, utc=True).timestamp())
        e = int(pd.to_datetime(end, utc=True).timestamp())
        chunk = 300 * gran
        rows, cur = [], s
        while cur < e:
            cend = min(cur + chunk, e)
            try:
                r = requests.get(
                    f"https://api.exchange.coinbase.com/products/{pair}/candles",
                    params={"granularity": gran, "start": cur, "end": cend},
                    timeout=20, headers={"User-Agent": "gq-research"})
                if r.status_code == 200:
                    rows += r.json()
            except Exception:
                pass
            cur = cend
            _t.sleep(0.25)                      # be polite to the public endpoint
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=["time", "low", "high", "open", "close", "volume"])
        df = df.drop_duplicates("time")
        df.index = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df[["open", "high", "low", "close", "volume"]].astype(float).sort_index()
        return df[~df.index.duplicated(keep="last")] if len(df) else None


def get_source(name: str = "yfinance", interval: str = "1h") -> DataSource:
    name = name.lower()
    if name == "yfinance":
        return YFinanceSource(interval=interval)
    if name == "coinbase":
        return CoinbaseSource(interval=interval)
    if name == "csv":
        return CSVSource(interval=interval)
    if name == "stooq":
        return StooqSource()
    raise ValueError(f"unknown source '{name}' (yfinance | coinbase | csv | stooq)")
