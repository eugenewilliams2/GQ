"""
GQ Forex Trading Bot — main entry point.

Usage:
  python run.py                       # interactive menu
  python run.py --mode safe           # safe mode scan
  python run.py --mode aggressive     # high risk / high reward
  python run.py live --mode safe
  python run.py backtest --mode aggressive
"""

import argparse
import logging
import time

from rich.console import Console
from rich.logging import RichHandler
from rich.panel   import Panel
from rich.prompt  import Prompt
from rich         import box

from forex_bot import config

console = Console()


def _setup_logging(verbose: bool = False):
    logging.basicConfig(
        level    = logging.DEBUG if verbose else logging.INFO,
        format   = "%(message)s",
        datefmt  = "[%X]",
        handlers = [
            RichHandler(rich_tracebacks=True, show_path=False),
            logging.FileHandler(config.LOG_FILE),
        ],
    )


def _print_banner(mode: str):
    profile = config.ACTIVE_PROFILE
    color, icon = ("green", "🛡") if mode == "safe" else ("red", "🔥")
    lines = [
        f"[bold {color}]{icon}  {profile['label']}[/]",
        "",
        f"  Risk per trade   : [yellow]{profile['risk_per_trade']*100:.1f}%[/] of balance",
        f"  Leverage         : [yellow]{profile['leverage']}x[/]",
        f"  Min R:R          : [yellow]{profile['min_rr']:.0f}:1[/]  (Paul Tudor Jones method)",
        f"  Stop loss        : [yellow]{profile['stop_loss_pips']} pips[/]",
        f"  Max open trades  : [yellow]{profile['max_open_trades']}[/]",
        f"  Portfolio heat   : [yellow]{profile['portfolio_heat']*100:.0f}%[/] max",
        f"  Daily loss halt  : [yellow]{profile['daily_loss_pct']*100:.0f}%[/]",
        f"  Max drawdown     : [yellow]{profile['max_drawdown_pct']*100:.0f}%[/]",
        f"  Signal strength  : [yellow]{profile['min_strength']*100:.0f}%[/] min",
        f"  Killzone filter  : [yellow]{'ON' if profile['require_killzone'] else 'OFF'}[/]",
        f"  Sweep required   : [yellow]{'YES' if profile['require_sweep'] else 'NO'}[/]",
    ]
    console.print(Panel(
        "\n".join(lines),
        title   = "[bold]GQ Forex Bot — ICT / SMC Strategy[/]",
        box     = box.DOUBLE_EDGE,
        border_style = color,
    ))


def _interactive_menu() -> tuple[str, str]:
    console.print()
    console.print("[bold cyan]GQ Forex Trading Bot[/]\n")

    console.print("Select [bold]risk mode[/]:")
    console.print("  [green]1[/]  Safe       — 0.5% risk, 3:1 R:R min, strict filters")
    console.print("  [red]2[/]  Aggressive — 2.5% risk, 2:1 R:R min, wider positions\n")
    m = Prompt.ask("Mode", choices=["1", "2", "safe", "aggressive"], default="1")
    mode = "safe" if m in ("1", "safe") else "aggressive"

    console.print()
    console.print("Select [bold]action[/]:")
    console.print("  [cyan]1[/]  Scan      — show current signals (ICT 4-gate analysis)")
    console.print("  [cyan]2[/]  Live      — paper-trade in real time (Ctrl+C to stop)")
    console.print("  [cyan]3[/]  Backtest  — replay 2024–2025 historical data\n")
    a = Prompt.ask("Action", choices=["1","2","3","scan","live","backtest"], default="1")
    return mode, {"1": "scan", "2": "live", "3": "backtest"}.get(a, a)


# ── Actions ───────────────────────────────────────────────────────────────────

def run_scan():
    from forex_bot.data_feed  import fetch_all_pairs_mtf
    from forex_bot.strategy   import scan_pairs
    from rich.table import Table

    console.print("\n[dim]Fetching market data (1H + 4H)…[/]")
    ltf, htf = fetch_all_pairs_mtf()
    signals  = scan_pairs(ltf, htf)

    if not signals:
        console.print(
            "[yellow]No signals right now.[/]\n"
            "[dim]All 4 ICT gates must pass: 4H structure + order block/FVG + "
            "killzone + sweep + momentum.[/]"
        )
        return

    table = Table(
        title   = f"ICT Signals  ({len(signals)} found)",
        box     = box.SIMPLE_HEAVY,
    )
    for col in ("Pair", "Dir", "Price", "Stop Loss", "Take Profit", "R:R", "Strength", "Killzone", "Why"):
        table.add_column(col, justify="right" if col not in ("Pair","Dir","Killzone","Why") else "left")

    for s in signals:
        d_str = "[green]BUY ▲[/]" if s.direction == 1 else "[red]SELL ▼[/]"
        table.add_row(
            s.pair, d_str,
            f"{s.price:.5f}", f"{s.stop_loss:.5f}", f"{s.take_profit:.5f}",
            f"[{'green' if s.rr_ratio >= 3 else 'yellow'}]{s.rr_ratio:.1f}:1[/]",
            f"{s.strength:.0%}",
            s.killzone or "—",
            s.reason.split("|")[1].strip() if "|" in s.reason else s.reason[:40],
        )
    console.print(table)


def run_live():
    from forex_bot.data_feed    import fetch_all_pairs_mtf
    from forex_bot.strategy     import scan_pairs
    from forex_bot.portfolio    import Portfolio
    from forex_bot.dashboard    import render
    from forex_bot.risk_manager import is_drawdown_ok, is_daily_loss_ok

    portfolio    = Portfolio()
    scan_count   = 0
    signals_seen = 0

    console.print(f"\n[dim]Live scan every {config.SCAN_INTERVAL_S}s — Ctrl+C to stop[/]\n")
    try:
        while True:
            ltf, htf = fetch_all_pairs_mtf()
            prices   = {p: float(df["close"].iloc[-1]) for p, df in ltf.items()}

            portfolio.update(prices)

            signals = scan_pairs(ltf, htf)
            signals_seen += len(signals)
            for sig in signals:
                portfolio.open_trade(sig)

            scan_count += 1
            render(portfolio, prices, signals_seen, scan_count)

            if not is_drawdown_ok(portfolio.balance, portfolio.peak_balance):
                console.print("[bold red]Max drawdown — shutting down.[/]")
                break
            if not is_daily_loss_ok(portfolio.daily_pnl, portfolio.balance):
                console.print("[bold yellow]Daily loss limit — no more trades today.[/]")

            time.sleep(config.SCAN_INTERVAL_S)

    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped.[/]")
        s = portfolio.stats()
        if s.get("trades", 0):
            console.print(
                f"\nSession: {s['trades']} trades  "
                f"Win rate: {s['win_rate']:.1f}%  "
                f"Avg R:R: {s['avg_rr']:.1f}  "
                f"P&L: ${s['total_pnl']:+.2f}  "
                f"Balance: ${s['balance']:,.2f}"
            )


def run_backtest():
    from forex_bot.backtester import run_backtest as _bt
    console.print(
        f"\n[dim]Backtesting {config.BACKTEST_START} → {config.BACKTEST_END}"
        f"  interval={config.BACKTEST_INTERVAL}[/]\n"
    )
    _bt()


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog        = "python run.py",
        description = "GQ Forex Trading Bot — ICT / Smart Money strategy",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = (
            "examples:\n"
            "  python run.py                       # interactive menu\n"
            "  python run.py --mode safe            # safe scan\n"
            "  python run.py live --mode aggressive # aggressive live trading\n"
            "  python run.py backtest --mode safe\n"
        ),
    )
    parser.add_argument(
        "action", nargs="?",
        choices=["scan", "live", "backtest"],
        help="scan | live | backtest  (omit for interactive menu)",
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["safe", "aggressive"], default=None,
        help="safe = low risk  |  aggressive = high risk / high reward",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    _setup_logging(args.verbose)

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
