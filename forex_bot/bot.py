"""
GQ Forex Trading Bot — main entry point.

Usage:
  python -m forex_bot.bot live       # paper-trade in real time
  python -m forex_bot.bot backtest   # run historical backtest
  python -m forex_bot.bot scan       # one-shot signal scan (no trading)
"""

import argparse
import logging
import time
import sys
from datetime import datetime, timezone

from rich.console import Console
from rich.logging import RichHandler

from forex_bot import config
from forex_bot.data_feed  import fetch_all_pairs, get_current_price
from forex_bot.strategy   import scan_pairs
from forex_bot.portfolio  import Portfolio
from forex_bot.dashboard  import render, console as dash_console

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level    = logging.INFO,
    format   = "%(message)s",
    datefmt  = "[%X]",
    handlers = [
        RichHandler(rich_tracebacks=True),
        logging.FileHandler(config.LOG_FILE),
    ],
)
logger  = logging.getLogger(__name__)
console = Console()


# ── Modes ────────────────────────────────────────────────────────────────────

def run_live():
    """Paper-trade in real time with a Rich dashboard."""
    console.print("[bold cyan]GQ Forex Bot — LIVE PAPER TRADING[/]")
    console.print(f"Pairs: {config.PAIRS}")
    console.print(f"Scanning every {config.SCAN_INTERVAL_S}s  |  interval={config.CANDLE_INTERVAL}\n")

    portfolio    = Portfolio()
    scan_count   = 0
    signals_seen = 0

    try:
        while True:
            data   = fetch_all_pairs()
            prices = {pair: float(df["close"].iloc[-1])
                      for pair, df in data.items()}

            # Close positions that hit SL/TP
            portfolio.update(prices)

            # Generate new signals
            signals = scan_pairs(data)
            signals_seen += len(signals)

            for sig in signals:
                logger.info(
                    "Signal: %s %s @ %.5f  strength=%.2f  [%s]",
                    "BUY" if sig.direction == 1 else "SELL",
                    sig.pair, sig.price, sig.strength, sig.reason,
                )
                portfolio.open_trade(sig)

            scan_count += 1
            render(portfolio, prices, signals_seen, scan_count)

            # Drawdown guard
            if not _drawdown_ok(portfolio):
                console.print("[bold red]Max drawdown reached — shutting down.[/]")
                break

            time.sleep(config.SCAN_INTERVAL_S)

    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped by user.[/]")
        _print_summary(portfolio, prices)


def run_scan():
    """One-shot: fetch data, print signals, exit."""
    console.print("[bold cyan]GQ Forex Bot — SIGNAL SCAN[/]\n")
    data    = fetch_all_pairs()
    signals = scan_pairs(data)

    if not signals:
        console.print("[dim]No signals at this time.[/]")
        return

    from rich.table import Table
    from rich       import box

    table = Table(title="Current Signals", box=box.SIMPLE_HEAVY)
    for col in ("Pair", "Dir", "Price", "SL", "TP", "Strength", "Reason"):
        table.add_column(col)

    for s in signals:
        table.add_row(
            s.pair,
            "[green]BUY[/]" if s.direction == 1 else "[red]SELL[/]",
            f"{s.price:.5f}",
            f"{s.stop_loss:.5f}",
            f"{s.take_profit:.5f}",
            f"{s.strength:.0%}",
            s.reason,
        )
    console.print(table)


def run_backtest():
    """Run historical backtest and print results."""
    console.print("[bold cyan]GQ Forex Bot — BACKTEST[/]")
    console.print(
        f"Period: {config.BACKTEST_START} → {config.BACKTEST_END}"
        f"  interval={config.BACKTEST_INTERVAL}\n"
    )
    from forex_bot.backtester import run_backtest as _bt
    result = _bt()
    console.print(str(result))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _drawdown_ok(portfolio: Portfolio) -> bool:
    from forex_bot.risk_manager import is_drawdown_ok
    return is_drawdown_ok(portfolio.balance, portfolio.peak_balance)


def _print_summary(portfolio: Portfolio, prices: dict[str, float]):
    stats = portfolio.stats()
    console.print("\n[bold]Session summary:[/]")
    for k, v in stats.items():
        console.print(f"  {k:<16}: {v}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="GQ Forex Trading Bot")
    parser.add_argument(
        "mode",
        nargs   = "?",
        default = "scan",
        choices = ["live", "backtest", "scan"],
        help    = "live | backtest | scan  (default: scan)",
    )
    args = parser.parse_args()

    if   args.mode == "live":      run_live()
    elif args.mode == "backtest":  run_backtest()
    else:                          run_scan()


if __name__ == "__main__":
    main()
