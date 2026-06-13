"""
Event-driven backtester.
Replays historical OHLCV candle-by-candle and runs the full strategy stack.
"""

import logging
from datetime import timezone

import pandas as pd

from forex_bot import config, strategy, indicators
from forex_bot.portfolio import Portfolio, Trade

logger = logging.getLogger(__name__)


class BacktestResult:
    def __init__(self, portfolio: Portfolio, equity_curve: list[float]):
        self.portfolio    = portfolio
        self.equity_curve = equity_curve
        self.stats        = portfolio.stats()

    def __str__(self) -> str:
        s = self.stats
        lines = [
            "═" * 50,
            "  BACKTEST RESULTS",
            "═" * 50,
            f"  Total trades   : {s.get('trades', 0)}",
            f"  Win rate        : {s.get('win_rate', 0):.1f}%",
            f"  Profit factor   : {s.get('profit_factor', 0):.2f}",
            f"  Avg win         : ${s.get('avg_win', 0):.2f}",
            f"  Avg loss        : ${s.get('avg_loss', 0):.2f}",
            f"  Total P&L       : ${s.get('total_pnl', 0):.2f}",
            f"  Final balance   : ${s.get('balance', 0):.2f}",
            f"  Peak balance    : ${s.get('peak_balance', 0):.2f}",
            f"  Max drawdown    : {s.get('drawdown_pct', 0):.2f}%",
            "═" * 50,
        ]
        return "\n".join(lines)


def run_backtest(
    pairs:    list[str] = config.PAIRS,
    start:    str       = config.BACKTEST_START,
    end:      str       = config.BACKTEST_END,
    interval: str       = config.BACKTEST_INTERVAL,
) -> BacktestResult:
    """
    Download historical data then replay candle-by-candle.
    Uses a rolling window equal to the longest indicator period.
    """
    import yfinance as yf

    logger.info("Downloading backtest data: %s → %s  interval=%s", start, end, interval)
    warmup    = max(config.EMA_SLOW, config.BB_PERIOD, config.RSI_PERIOD) + 5
    portfolio = Portfolio()
    equity_curve: list[float] = []

    # --- fetch all pairs once ---
    raw: dict[str, pd.DataFrame] = {}
    for pair in pairs:
        df = yf.download(pair, start=start, end=end,
                         interval=interval, auto_adjust=True, progress=False)
        if df.empty:
            logger.warning("No data for %s", pair)
            continue
        df.columns = [c.lower() for c in df.columns]
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        df.index = pd.to_datetime(df.index, utc=True)
        raw[pair] = df
        logger.info("  %s: %d candles", pair, len(df))

    if not raw:
        logger.error("No data fetched — aborting backtest")
        return BacktestResult(portfolio, [])

    # --- build unified timeline ---
    all_timestamps = sorted(
        set().union(*[set(df.index) for df in raw.values()])
    )

    logger.info("Replaying %d timestamps…", len(all_timestamps))

    for i, ts in enumerate(all_timestamps):
        # Build slice dict: each pair's data up to this timestamp
        slices: dict[str, pd.DataFrame] = {}
        prices: dict[str, float]        = {}

        for pair, df in raw.items():
            sub = df[df.index <= ts]
            if len(sub) < warmup:
                continue
            slices[pair] = sub
            prices[pair] = float(sub["close"].iloc[-1])

        # Update open positions first
        portfolio.update(prices)

        # Generate and act on signals
        if slices:
            signals = strategy.scan_pairs(slices)
            for sig in signals:
                portfolio.open_trade(sig)

        equity_curve.append(portfolio.equity(prices))

    result = BacktestResult(portfolio, equity_curve)
    logger.info("Backtest complete.\n%s", result)
    return result
