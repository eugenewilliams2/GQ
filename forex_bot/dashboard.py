"""
Rich terminal dashboard for live paper-trading mode.
"""

from datetime import datetime, timezone

from rich.console import Console
from rich.table   import Table
from rich.panel   import Panel
from rich.columns import Columns
from rich.text    import Text
from rich import box

from forex_bot.portfolio import Portfolio

console = Console()


def _color_pnl(val: float) -> Text:
    color = "green" if val >= 0 else "red"
    return Text(f"${val:+.2f}", style=f"bold {color}")


def render(portfolio: Portfolio, prices: dict[str, float],
           signals_seen: int, scan_count: int):
    console.clear()

    # ── Header ──────────────────────────────────────────────────────────────
    equity  = portfolio.equity(prices)
    balance = portfolio.balance
    dd_pct  = (portfolio.peak_balance - balance) / portfolio.peak_balance * 100 if portfolio.peak_balance else 0

    header = (
        f"[bold cyan]GQ Forex Trading Bot[/]  "
        f"  Balance: [yellow]${balance:,.2f}[/]"
        f"  Equity:  [yellow]${equity:,.2f}[/]"
        f"  Drawdown: [{'red' if dd_pct > 10 else 'green'}]{dd_pct:.1f}%[/]"
        f"  Scans: {scan_count}  Signals: {signals_seen}"
        f"  [dim]{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}[/]"
    )
    console.print(Panel(header, box=box.DOUBLE_EDGE))

    # ── Open positions ───────────────────────────────────────────────────────
    open_table = Table(title="Open Positions", box=box.SIMPLE_HEAVY, expand=True)
    for col in ("ID", "Pair", "Dir", "Entry", "Current", "SL", "TP", "Units", "Unreal P&L"):
        open_table.add_column(col, justify="right")

    for t in portfolio.open_trades:
        price = prices.get(t.pair, t.entry_price)
        upnl  = t.unrealised_pnl(price)
        open_table.add_row(
            t.id,
            t.pair,
            "[green]BUY[/]" if t.direction == 1 else "[red]SELL[/]",
            f"{t.entry_price:.5f}",
            f"{price:.5f}",
            f"{t.stop_loss:.5f}",
            f"{t.take_profit:.5f}",
            str(t.units),
            str(_color_pnl(upnl)),
        )

    # ── Recent closed trades ─────────────────────────────────────────────────
    closed_table = Table(title="Recent Closed Trades (last 10)", box=box.SIMPLE_HEAVY, expand=True)
    for col in ("ID", "Pair", "Dir", "Entry", "Exit", "P&L", "Reason"):
        closed_table.add_column(col, justify="right")

    for t in list(reversed(portfolio.closed_trades))[:10]:
        closed_table.add_row(
            t.id,
            t.pair,
            "[green]BUY[/]" if t.direction == 1 else "[red]SELL[/]",
            f"{t.entry_price:.5f}",
            f"{t.exit_price:.5f}" if t.exit_price else "—",
            str(_color_pnl(t.pnl)),
            t.reason.split("|")[0].strip(),
        )

    console.print(Columns([open_table, closed_table]))

    # ── Stats panel ──────────────────────────────────────────────────────────
    stats = portfolio.stats()
    stats_text = (
        f"Trades: {stats.get('trades',0)}  "
        f"Win rate: {stats.get('win_rate',0):.1f}%  "
        f"Profit factor: {stats.get('profit_factor',0):.2f}  "
        f"Total P&L: ${stats.get('total_pnl',0):+.2f}"
    )
    console.print(Panel(stats_text, title="Performance", box=box.SIMPLE))
