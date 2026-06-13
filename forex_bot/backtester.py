"""
Event-driven backtester — replays history with the ICT 4-gate strategy.
Uses 4H data (resampled from 1H) for structure/bias and 1H data for entry timing.

Note: Yahoo Finance has no native 4h interval and only serves 1h data for the
trailing ~730 days, so we fetch 1h and resample to 4h, clamping the start date.
"""

import logging
import warnings
from datetime import datetime, timedelta, timezone

import pandas as pd

from forex_bot import config, strategy
from forex_bot.portfolio import Portfolio

logger = logging.getLogger(__name__)

_YF_INTRADAY_MAX_DAYS = 730


def _clean(df: pd.DataFrame, pair: str) -> pd.DataFrame | None:
    """Flatten MultiIndex columns (new yfinance) and select OHLCV."""
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        lvl1 = df.columns.get_level_values(1)
        df = df.xs(pair, axis=1, level=1) if pair in set(lvl1) \
             else df.droplevel(1, axis=1)
    df.columns = [str(c).lower() for c in df.columns]
    needed = {"open", "high", "low", "close", "volume"}
    if not needed.issubset(df.columns):
        return None
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    df.index = pd.to_datetime(df.index, utc=True)
    return df if not df.empty else None


def _resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    return df.resample("4h").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()


def _clamp_start(start: str) -> str:
    """Yahoo only serves 1h data for the trailing ~730 days — clamp the start."""
    earliest = datetime.now(timezone.utc) - timedelta(days=_YF_INTRADAY_MAX_DAYS - 2)
    try:
        requested = pd.to_datetime(start, utc=True)
    except Exception:
        return earliest.strftime("%Y-%m-%d")
    if requested < earliest:
        logger.warning(
            "Start %s is beyond Yahoo's 1h limit — clamping to %s",
            start, earliest.strftime("%Y-%m-%d"))
        return earliest.strftime("%Y-%m-%d")
    return start


class BacktestResult:
    def __init__(self, portfolio: Portfolio, equity_curve: list[float]):
        self.portfolio    = portfolio
        self.equity_curve = equity_curve
        self.stats        = portfolio.stats()

    def __str__(self) -> str:
        s = self.stats
        profile = config.ACTIVE_PROFILE
        lines = [
            "═" * 56,
            f"  BACKTEST RESULTS  [{profile['label']}]",
            "═" * 56,
            f"  Total trades     : {s.get('trades', 0)}",
            f"  Win rate         : {s.get('win_rate', 0):.1f}%",
            f"  Avg R:R achieved : {s.get('avg_rr', 0):.2f}",
            f"  Profit factor    : {s.get('profit_factor', 0):.2f}",
            f"  Avg win          : ${s.get('avg_win', 0):.2f}",
            f"  Avg loss         : ${s.get('avg_loss', 0):.2f}",
            f"  Total P&L        : ${s.get('total_pnl', 0):.2f}",
            f"  Final balance    : ${s.get('balance', 0):.2f}",
            f"  Peak balance     : ${s.get('peak_balance', 0):.2f}",
            f"  Max drawdown     : {s.get('drawdown_pct', 0):.2f}%",
            "═" * 56,
        ]
        return "\n".join(lines)


def run_backtest(
    pairs:    list[str] = config.PAIRS,
    start:    str       = config.BACKTEST_START,
    end:      str       = config.BACKTEST_END,
    interval: str       = config.BACKTEST_INTERVAL,
) -> BacktestResult:
    import yfinance as yf

    warmup    = strategy.MIN_LTF
    portfolio = Portfolio()
    equity_curve: list[float] = []

    start = _clamp_start(start)
    logger.info("Downloading 1H backtest data: %s → %s", start, end)
    raw_1h: dict[str, pd.DataFrame] = {}
    raw_4h: dict[str, pd.DataFrame] = {}

    for pair in pairs:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df1 = yf.download(pair, start=start, end=end,
                              interval="1h", auto_adjust=True, progress=False)

        df1 = _clean(df1, pair)
        if df1 is not None:
            raw_1h[pair] = df1
            raw_4h[pair] = _resample_4h(df1)   # derive 4h locally

        logger.info("  %s  1H=%s  4H=%s",
                    pair,
                    len(raw_1h[pair]) if pair in raw_1h else "NO DATA",
                    len(raw_4h[pair]) if pair in raw_4h else "NO DATA")

    if not raw_1h:
        logger.error(
            "No data fetched for any pair.\n"
            "  • Update yfinance:  pip install -U yfinance\n"
            "  • Check your internet connection\n"
            "  • Yahoo Finance rate-limits — wait 30-60s and retry"
        )
        return BacktestResult(portfolio, [])

    all_ts = sorted(set().union(*[set(df.index) for df in raw_1h.values()]))
    logger.info("Replaying %d timestamps across %d pairs…", len(all_ts), len(raw_1h))

    for ts in all_ts:
        slices_1h, slices_4h, prices = {}, {}, {}

        for pair in raw_1h:
            sub1 = raw_1h[pair][raw_1h[pair].index <= ts]
            sub4 = raw_4h.get(pair, pd.DataFrame())
            sub4 = sub4[sub4.index <= ts] if not sub4.empty else sub4

            if len(sub1) < warmup:
                continue
            slices_1h[pair] = sub1
            slices_4h[pair] = sub4
            prices[pair]    = float(sub1["close"].iloc[-1])

        portfolio.update(prices)

        if slices_1h:
            for sig in strategy.scan_pairs(slices_1h, slices_4h):
                portfolio.open_trade(sig)

        equity_curve.append(portfolio.equity(prices))

    result = BacktestResult(portfolio, equity_curve)
    logger.info("Backtest complete.\n%s", result)
    return result
