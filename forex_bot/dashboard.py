"""
Rich terminal dashboard — live paper-trading view.
Shows R:R, portfolio heat, daily P&L, killzone status.
"""

from datetime import datetime, timezone

from rich.console import Console
from rich.table   import Table
from rich.panel   import Panel
from rich.columns import Columns
from rich.text    import Text
from rich         import box

from forex_bot import indicators as ind
from forex_bot.portfolio import Portfolio

console = Console()


def _pnl_text(val: float) -> Text:
    return Text(f"${val:+.2f}", style=f"bold {'green' if val >= 0 else 'red'}")


def render(portfolio: Portfolio, prices: dict[str, float],
           signals_seen: int, scan_count: int):
    console.clear()

    equity  = portfolio.equity(prices)
    balance = portfolio.balance
    heat    = portfolio.portfolio_heat * 100
    dd_pct  = (portfolio.peak_balance - balance) / portfolio.peak_balance * 100 \
              if portfolio.peak_balance else 0
    daily   = portfolio.daily_pnl
    kz_ok, kz_name = ind.in_killzone()
    kz_str  = f"[green]{kz_name}[/]" if kz_ok else "[dim]No killzone[/]"

    header = (
        f"[bold cyan]GQ Forex Bot — ICT/SMC[/]  "
        f"Balance: [yellow]${balance:,.2f}[/]  "
        f"Equity: [yellow]${equity:,.2f}[/]  "
        f"Daily P&L: {'[green]' if daily >= 0 else '[red]'}${daily:+.2f}[/]  "
        f"Heat: [{'red' if heat > 5 else 'yellow'}]{heat:.1f}%[/]  "
        f"DD: [{'red' if dd_pct > 10 else 'green'}]{dd_pct:.1f}%[/]  "
        f"Killzone: {kz_str}  "
        f"Scans: {scan_count}  Sigs: {signals_seen}  "
        f"[dim]{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}[/]"
    )
    console.print(Panel(header, box=box.DOUBLE_EDGE))

    # ── Open positions ────────────────────────────────────────────────────
    open_t = Table(title="Open Positions", box=box.SIMPLE_HEAVY, expand=True)
    for col in ("ID", "Pair", "Dir", "Entry", "Now", "SL", "TP", "R:R", "Units", "P&L"):
        open_t.add_column(col, justify="right")

    for t in portfolio.open_trades:
        price = prices.get(t.pair, t.entry_price)
        upnl  = t.unrealised_pnl(price)
        rr_color = "green" if t.rr_ratio >= 3 else "yellow"
        open_t.add_row(
            t.id,
            t.pair,
            "[green]BUY ▲[/]" if t.direction == 1 else "[red]SELL ▼[/]",
            f"{t.entry_price:.5f}",
            f"{price:.5f}",
            f"{t.stop_loss:.5f}",
            f"{t.take_profit:.5f}",
            f"[{rr_color}]{t.rr_ratio:.1f}:1[/]",
            str(t.units),
            str(_pnl_text(upnl)),
        )

    # ── Recent closed trades ──────────────────────────────────────────────
    closed_t = Table(title="Closed (last 10)", box=box.SIMPLE_HEAVY, expand=True)
    for col in ("ID", "Pair", "Dir", "Entry", "Exit", "R:R", "P&L"):
        closed_t.add_column(col, justify="right")

    for t in list(reversed(portfolio.closed_trades))[:10]:
        closed_t.add_row(
            t.id, t.pair,
            "[green]BUY[/]" if t.direction == 1 else "[red]SELL[/]",
            f"{t.entry_price:.5f}",
            f"{t.exit_price:.5f}" if t.exit_price else "—",
            f"{t.rr_ratio:.1f}:1",
            str(_pnl_text(t.pnl)),
        )

    console.print(Columns([open_t, closed_t]))

    stats = portfolio.stats()
    console.print(Panel(
        f"Trades: {stats.get('trades',0)}  "
        f"Win rate: {stats.get('win_rate',0):.1f}%  "
        f"Avg R:R: {stats.get('avg_rr',0):.1f}  "
        f"Profit factor: {stats.get('profit_factor',0):.2f}  "
        f"Total P&L: ${stats.get('total_pnl',0):+.2f}  "
        f"Portfolio heat: {stats.get('portfolio_heat','0%')}",
        title="Performance",
        box=box.SIMPLE,
    ))
