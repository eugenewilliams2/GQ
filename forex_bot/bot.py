"""
GQ Forex Trading Bot
────────────────────
Usage (quick):
  python run.py                         # interactive menu
  python run.py --mode safe             # low risk, conservative
  python run.py --mode aggressive       # high risk / high reward

  python run.py scan        --mode safe
  python run.py live        --mode aggressive
  python run.py backtest    --mode safe
"""

import argparse
import logging
import sys
import time

from rich.console import Console
from rich.logging import RichHandler
from rich.panel   import Panel
from rich.prompt  import Prompt
from rich         import box

from forex_bot import config

console = Console()


# ── Logging ──────────────────────────────────────────────────────────────────

def _setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level    = level,
        format   = "%(message)s",
        datefmt  = "[%X]",
        handlers = [
            RichHandler(rich_tracebacks=True, show_path=False),
            logging.FileHandler(config.LOG_FILE),
        ],
    )


# ── Mode banner ───────────────────────────────────────────────────────────────

def _print_banner(mode: str):
    profile = config.ACTIVE_PROFILE
    if mode == "safe":
        color, icon = "green", "🛡"
    else:
        color, icon = "red", "🔥"

    lines = [
        f"[bold {color}]{icon}  {profile['label']}[/]",
        "",
        f"  Risk per trade   : [yellow]{profile['risk_per_trade']*100:.1f}%[/] of balance",
        f"  Max open trades  : [yellow]{profile['max_open_trades']}[/]",
        f"  Stop loss        : [yellow]{profile['stop_loss_pips']} pips[/]",
        f"  Take profit      : [yellow]{profile['take_profit_pips']} pips[/]  "
        f"(1:{profile['take_profit_pips']//profile['stop_loss_pips']}  R:R)",
        f"  Max drawdown     : [yellow]{profile['max_drawdown_pct']*100:.0f}%[/]",
        f"  Leverage         : [yellow]{profile['leverage']}x[/]",
        f"  Min signal str.  : [yellow]{profile['min_strength']*100:.0f}%[/]",
    ]
    console.print(Panel("\n".join(lines), title="[bold]GQ Forex Bot[/]",
                        box=box.DOUBLE_EDGE, border_style=color))


# ── Interactive menu ──────────────────────────────────────────────────────────

def _interactive_menu() -> tuple[str, str]:
    console.print()
    console.print("[bold cyan]GQ Forex Trading Bot[/]\n")

    console.print("Select [bold]risk mode[/]:")
    console.print("  [green]1[/]  Safe       — low risk, steady gains, tight drawdown protection")
    console.print("  [red]2[/]  Aggressive — high risk, high reward, wider positions\n")
    mode_choice = Prompt.ask("Mode", choices=["1", "2", "safe", "aggressive"], default="1")
    mode = "safe" if mode_choice in ("1", "safe") else "aggressive"

    console.print()
    console.print("Select [bold]action[/]:")
    console.print("  [cyan]1[/]  Scan      — check all pairs for signals right now")
    console.print("  [cyan]2[/]  Live      — paper-trade in real time (press Ctrl+C to stop)")
    console.print("  [cyan]3[/]  Backtest  — replay 2024–2025 historical data\n")
    action_choice = Prompt.ask("Action", choices=["1", "2", "3", "scan", "live", "backtest"], default="1")
    action_map = {"1": "scan", "2": "live", "3": "backtest"}
    action = action_map.get(action_choice, action_choice)

    return mode, action


# ── Actions ───────────────────────────────────────────────────────────────────

def run_scan():
    from forex_bot.data_feed import fetch_all_pairs
    from forex_bot.strategy  import scan_pairs
    from rich.table import Table

    console.print("\n[dim]Fetching market data…[/]")
    data    = fetch_all_pairs()
    signals = scan_pairs(data)

    if not signals:
        console.print("[yellow]No signals right now — all three confirmation gates must pass.[/]")
        return

    table = Table(title=f"Signals  ({len(signals)} found)", box=box.SIMPLE_HEAVY)
    for col in ("Pair", "Direction", "Price", "Stop Loss", "Take Profit", "Strength", "Why"):
        table.add_column(col)

    for s in signals:
        direction_str = "[green]  BUY ▲[/]" if s.direction == 1 else "[red]  SELL ▼[/]"
        table.add_row(
            s.pair, direction_str,
            f"{s.price:.5f}", f"{s.stop_loss:.5f}", f"{s.take_profit:.5f}",
            f"{s.strength:.0%}",
            s.reason.split("|")[0].strip(),
        )
    console.print(table)


def run_live():
    from forex_bot.data_feed  import fetch_all_pairs
    from forex_bot.strategy   import scan_pairs
    from forex_bot.portfolio  import Portfolio
    from forex_bot.dashboard  import render
    from forex_bot.risk_manager import is_drawdown_ok

    portfolio    = Portfolio()
    scan_count   = 0
    signals_seen = 0

    console.print(f"\n[dim]Starting live scan every {config.SCAN_INTERVAL_S}s — press Ctrl+C to stop[/]\n")

    try:
        while True:
            data   = fetch_all_pairs()
            prices = {pair: float(df["close"].iloc[-1]) for pair, df in data.items()}

            portfolio.update(prices)

            signals = scan_pairs(data)
            signals_seen += len(signals)
            for sig in signals:
                portfolio.open_trade(sig)

            scan_count += 1
            render(portfolio, prices, signals_seen, scan_count)

            if not is_drawdown_ok(portfolio.balance, portfolio.peak_balance):
                console.print("[bold red]Max drawdown reached — shutting down.[/]")
                break

            time.sleep(config.SCAN_INTERVAL_S)

    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped.[/]")
        stats = portfolio.stats()
        if stats.get("trades", 0):
            console.print(f"\nSession: {stats['trades']} trades  "
                          f"Win rate: {stats['win_rate']:.1f}%  "
                          f"P&L: ${stats['total_pnl']:+.2f}  "
                          f"Balance: ${stats['balance']:,.2f}")


def run_backtest():
    from forex_bot.backtester import run_backtest as _bt
    console.print(
        f"\n[dim]Backtesting {config.BACKTEST_START} → {config.BACKTEST_END}"
        f"  interval={config.BACKTEST_INTERVAL}[/]\n"
    )
    result = _bt()
    console.print(str(result))


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog        = "python run.py",
        description = "GQ Forex Trading Bot",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "examples:\n"
            "  python run.py                       # interactive menu\n"
            "  python run.py --mode safe            # safe mode scan\n"
            "  python run.py live --mode aggressive # aggressive live trading\n"
            "  python run.py backtest --mode safe   # safe backtest\n"
        ),
    )
    parser.add_argument(
        "action",
        nargs   = "?",
        choices = ["scan", "live", "backtest"],
        help    = "scan | live | backtest  (omit for interactive menu)",
    )
    parser.add_argument(
        "--mode", "-m",
        choices = ["safe", "aggressive"],
        default = None,
        help    = "safe = low risk  |  aggressive = high risk / high reward",
    )
    parser.add_argument(
        "--verbose", "-v",
        action = "store_true",
        help   = "show debug-level logs",
    )
    args = parser.parse_args()

    _setup_logging(args.verbose)

    # Interactive menu if nothing was specified
    if args.action is None and args.mode is None:
        mode, action = _interactive_menu()
    else:
        mode   = args.mode   or "safe"
        action = args.action or "scan"

    config.set_profile(mode)
    _print_banner(mode)

    if   action == "scan":      run_scan()
    elif action == "live":      run_live()
    elif action == "backtest":  run_backtest()


if __name__ == "__main__":
    main()
