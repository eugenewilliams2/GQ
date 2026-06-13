"""
GQ Forex Bot — premium Rich terminal dashboard.
"""

from datetime import datetime, timezone
from rich.console   import Console
from rich.table     import Table
from rich.panel     import Panel
from rich.columns   import Columns
from rich.text      import Text
from rich.layout    import Layout
from rich.live      import Live
from rich.progress  import BarColumn, Progress, TextColumn
from rich.rule      import Rule
from rich.align     import Align
from rich           import box

from forex_bot import config, indicators as ind
from forex_bot.portfolio import Portfolio

console = Console()

# ── colour helpers ─────────────────────────────────────────────────────────────

def _c(val: float, lo: float, hi: float, rev: bool = False) -> str:
    """Pick green/yellow/red based on thresholds."""
    good = val <= lo if rev else val >= hi
    bad  = val >= hi if rev else val <= lo
    if good: return "bright_green"
    if bad:  return "bright_red"
    return "yellow"

def _pnl(val: float, bold: bool = True) -> Text:
    style = ("bold " if bold else "") + ("bright_green" if val >= 0 else "bright_red")
    return Text(f"${val:+,.2f}", style=style)

def _bar(pct: float, width: int = 12, color: str = "cyan") -> str:
    """Tiny inline ASCII progress bar."""
    filled = int(min(pct / 100, 1.0) * width)
    return f"[{color}]{'█' * filled}[/][dim]{'░' * (width - filled)}[/]"

def _dir_badge(direction: int) -> str:
    return "[bold bright_green] BUY  ▲ [/]" if direction == 1 else "[bold bright_red] SELL ▼ [/]"


# ── sub-panels ─────────────────────────────────────────────────────────────────

def _header_panel(portfolio: Portfolio, prices: dict, signals_seen: int,
                  scan_count: int) -> Panel:
    equity   = portfolio.equity(prices)
    balance  = portfolio.balance
    peak     = portfolio.peak_balance or balance
    daily    = portfolio.daily_pnl
    heat_pct = portfolio.portfolio_heat * 100
    dd_pct   = (peak - balance) / peak * 100 if peak else 0
    pnl_net  = balance - config.STARTING_BALANCE

    kz_ok, kz_name = ind.in_killzone()
    kz_badge = (f"[bold bright_green]● {kz_name}[/]" if kz_ok
                else "[dim]○ Off-session[/]")

    ts  = datetime.now(timezone.utc).strftime("%Y-%m-%d  %H:%M:%S UTC")
    pnl_style = "bright_green" if pnl_net >= 0 else "bright_red"

    # top stat line
    top = (
        f"[bold bright_cyan]GQ Forex Bot[/]  [dim]│[/]  "
        f"[dim]Balance[/] [bold white]${balance:>10,.2f}[/]  "
        f"[dim]Equity[/]  [bold white]${equity:>10,.2f}[/]  "
        f"[dim]Net P&L[/] [{pnl_style}]{pnl_net:>+10,.2f}[/]  "
        f"[dim]│[/]  [dim]{ts}[/]"
    )

    # metric row
    heat_color = "bright_red" if heat_pct > 6 else ("yellow" if heat_pct > 3 else "bright_green")
    dd_color   = "bright_red" if dd_pct > 15  else ("yellow" if dd_pct > 5  else "bright_green")

    bot = (
        f"  [dim]Daily P&L[/]  {_pnl(daily, bold=False)}  [dim]│[/]  "
        f"  [dim]Heat[/]  [{heat_color}]{heat_pct:.1f}%[/]  {_bar(heat_pct, 10, heat_color)}  [dim]│[/]  "
        f"  [dim]Drawdown[/]  [{dd_color}]{dd_pct:.1f}%[/]  {_bar(dd_pct, 10, dd_color)}  [dim]│[/]  "
        f"  [dim]Killzone[/]  {kz_badge}  [dim]│[/]  "
        f"  [dim]Scans[/] [white]{scan_count}[/]  [dim]Signals[/] [white]{signals_seen}[/]"
    )

    body = top + "\n" + bot
    return Panel(body, box=box.DOUBLE_EDGE,
                 border_style="bright_cyan",
                 padding=(0, 1))


def _open_table(portfolio: Portfolio, prices: dict) -> Table:
    t = Table(
        title="[bold bright_white]◈  OPEN POSITIONS[/]",
        box=box.SIMPLE_HEAVY,
        border_style="cyan",
        header_style="bold cyan",
        expand=True,
        show_edge=True,
    )
    for col, just in [
        ("ID","left"), ("Pair","left"), ("Direction","center"),
        ("Entry","right"), ("Mark","right"), ("SL","right"), ("TP","right"),
        ("R:R","center"), ("Units","right"), ("Unrealised P&L","right"),
        ("Progress","center"),
    ]:
        t.add_column(col, justify=just)

    if not portfolio.open_trades:
        t.add_row(*["—"] * 11)
        return t

    for tr in portfolio.open_trades:
        price = prices.get(tr.pair, tr.entry_price)
        upnl  = tr.unrealised_pnl(price)

        # How far price has moved toward TP (as % of SL→TP range)
        sl_to_tp   = abs(tr.take_profit - tr.entry_price)
        moved      = (price - tr.entry_price) * tr.direction
        progress   = max(0.0, min(moved / sl_to_tp * 100, 100.0)) if sl_to_tp else 0
        prog_color = "bright_green" if progress >= 50 else ("yellow" if progress > 0 else "bright_red")

        rr_color   = "bright_green" if tr.rr_ratio >= 3 else "yellow"
        price_color= "bright_green" if upnl >= 0 else "bright_red"

        t.add_row(
            f"[dim]{tr.id}[/]",
            f"[bold]{tr.pair.replace('=X','')}[/]",
            _dir_badge(tr.direction),
            f"[white]{tr.entry_price:.5f}[/]",
            f"[{price_color}]{price:.5f}[/]",
            f"[dim]{tr.stop_loss:.5f}[/]",
            f"[dim]{tr.take_profit:.5f}[/]",
            f"[{rr_color}]{tr.rr_ratio:.1f}:1[/]",
            f"[dim]{tr.units:,}[/]",
            str(_pnl(upnl)),
            f"{_bar(progress, 10, prog_color)} [dim]{progress:.0f}%[/]",
        )
    return t


def _closed_table(portfolio: Portfolio) -> Table:
    t = Table(
        title="[bold bright_white]◇  RECENT CLOSED[/]",
        box=box.SIMPLE_HEAVY,
        border_style="bright_blue",
        header_style="bold bright_blue",
        expand=True,
        show_edge=True,
    )
    for col, just in [
        ("ID","left"), ("Pair","left"), ("Dir","center"),
        ("Entry","right"), ("Exit","right"), ("R:R","center"), ("P&L","right"),
    ]:
        t.add_column(col, justify=just)

    recent = list(reversed(portfolio.closed_trades))[:10]
    if not recent:
        t.add_row(*["—"] * 7)
        return t

    for tr in recent:
        pnl_color = "bright_green" if tr.pnl >= 0 else "bright_red"
        outcome   = "✓" if tr.pnl >= 0 else "✗"
        t.add_row(
            f"[dim]{tr.id}[/]",
            f"[bold]{tr.pair.replace('=X','')}[/]",
            _dir_badge(tr.direction),
            f"[white]{tr.entry_price:.5f}[/]",
            f"[white]{tr.exit_price:.5f}[/]" if tr.exit_price else "[dim]—[/]",
            f"{tr.rr_ratio:.1f}:1",
            f"[{pnl_color}]{outcome} ${tr.pnl:+,.2f}[/]",
        )
    return t


def _stats_panel(portfolio: Portfolio) -> Panel:
    s = portfolio.stats()
    if not s.get("trades"):
        return Panel("[dim]No closed trades yet[/]", title="[bold]Performance[/]",
                     box=box.SIMPLE, border_style="dim")

    trades = s.get("trades", 0)
    wr     = s.get("win_rate", 0)
    pf     = s.get("profit_factor", 0)
    avg_rr = s.get("avg_rr", 0)
    total  = s.get("total_pnl", 0)
    avg_w  = s.get("avg_win", 0)
    avg_l  = s.get("avg_loss", 0)

    wr_color = "bright_green" if wr >= 55 else ("yellow" if wr >= 45 else "bright_red")
    pf_color = "bright_green" if pf >= 1.5 else ("yellow" if pf >= 1.0 else "bright_red")
    rr_color = "bright_green" if avg_rr >= 2.5 else "yellow"

    body = (
        f"  [dim]Closed Trades[/]  [bold white]{trades}[/]"
        f"   [dim]│[/]   "
        f"  [dim]Win Rate[/]  [{wr_color}]{wr:.1f}%[/]  {_bar(wr, 12, wr_color)}"
        f"   [dim]│[/]   "
        f"  [dim]Avg R:R[/]  [{rr_color}]{avg_rr:.2f}[/]"
        f"   [dim]│[/]   "
        f"  [dim]Profit Factor[/]  [{pf_color}]{pf:.2f}[/]"
        f"   [dim]│[/]   "
        f"  [dim]Total P&L[/]  {_pnl(total)}"
        f"   [dim]│[/]   "
        f"  [dim]Avg Win[/]  [bright_green]${avg_w:+,.2f}[/]"
        f"   [dim]Avg Loss[/]  [bright_red]${avg_l:+,.2f}[/]"
    )
    return Panel(body, title="[bold bright_white]▸ PERFORMANCE[/]",
                 box=box.HEAVY, border_style="bright_white", padding=(0, 1))


# ── main render ────────────────────────────────────────────────────────────────

def render(portfolio: Portfolio, prices: dict[str, float],
           signals_seen: int, scan_count: int):
    console.clear()
    console.print(_header_panel(portfolio, prices, signals_seen, scan_count))
    console.print(Columns([_open_table(portfolio, prices),
                            _closed_table(portfolio)], equal=True, expand=True))
    console.print(_stats_panel(portfolio))
