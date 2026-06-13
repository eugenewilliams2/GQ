"""
Event-driven backtester — replays history with the ICT 4-gate strategy.
Uses 4H data for structure/bias and 1H data for entry timing.
"""

import logging

import pandas as pd

from forex_bot import config, strategy
from forex_bot.portfolio import Portfolio

logger = logging.getLogger(__name__)


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

    logger.info("Downloading 1H backtest data: %s → %s", start, end)
    raw_1h: dict[str, pd.DataFrame] = {}
    raw_4h: dict[str, pd.DataFrame] = {}

    for pair in pairs:
        df1 = yf.download(pair, start=start, end=end,
                          interval="1h", auto_adjust=True, progress=False)
        df4 = yf.download(pair, start=start, end=end,
                          interval="4h", auto_adjust=True, progress=False)
        for df, store in [(df1, raw_1h), (df4, raw_4h)]:
            if df.empty:
                continue
            df.columns = [c.lower() for c in df.columns]
            df = df[["open","high","low","close","volume"]].dropna()
            df.index = pd.to_datetime(df.index, utc=True)
            store[pair] = df

        logger.info("  %s  1H=%d  4H=%d",
                    pair,
                    len(raw_1h.get(pair, [])),
                    len(raw_4h.get(pair, [])))

    if not raw_1h:
        logger.error("No data fetched — aborting.")
        return BacktestResult(portfolio, [])

    all_ts = sorted(set().union(*[set(df.index) for df in raw_1h.values()]))
    logger.info("Replaying %d timestamps…", len(all_ts))

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
