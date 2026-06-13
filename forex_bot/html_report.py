"""
HTML report generator — renders a full backtest or live-session
summary as a self-contained dark-theme HTML file.
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

from forex_bot import config
from forex_bot.portfolio import Portfolio


# ── equity curve SVG ──────────────────────────────────────────────────────────

def _equity_svg(curve: list[float], width: int = 900, height: int = 220) -> str:
    if not curve or len(curve) < 2:
        return "<p style='color:#555;text-align:center;padding:40px'>No equity data</p>"

    lo, hi   = min(curve), max(curve)
    span     = hi - lo or 1
    pad_x, pad_y = 40, 20

    def px(i):
        return pad_x + (i / (len(curve) - 1)) * (width - 2 * pad_x)

    def py(v):
        return pad_y + (1 - (v - lo) / span) * (height - 2 * pad_y)

    pts   = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(curve))
    start = config.STARTING_BALANCE
    color = "#00ff88" if curve[-1] >= start else "#ff4466"

    # area fill path
    first_x = f"{px(0):.1f}"
    last_x  = f"{px(len(curve)-1):.1f}"
    area    = f"M {first_x},{height-pad_y} L {pts} L {last_x},{height-pad_y} Z"

    # y-axis labels
    ticks = [lo, lo + span * 0.25, lo + span * 0.5, lo + span * 0.75, hi]
    ylabels = "".join(
        f'<text x="{pad_x-6}" y="{py(v)+4:.1f}" text-anchor="end" '
        f'font-size="10" fill="#556">${v:,.0f}</text>'
        for v in ticks
    )

    return f"""
<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg"
     style="width:100%;height:{height}px;overflow:visible">
  <defs>
    <linearGradient id="eq" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"   stop-color="{color}" stop-opacity="0.25"/>
      <stop offset="100%" stop-color="{color}" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <!-- grid lines -->
  {''.join(f'<line x1="{pad_x}" y1="{py(v):.1f}" x2="{width-pad_x}" y2="{py(v):.1f}" stroke="#1a1a2e" stroke-width="1"/>' for v in ticks)}
  <!-- area fill -->
  <path d="{area}" fill="url(#eq)" />
  <!-- line -->
  <polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>
  <!-- start line -->
  <line x1="{pad_x}" y1="{py(start):.1f}" x2="{width-pad_x}" y2="{py(start):.1f}"
        stroke="#334" stroke-width="1" stroke-dasharray="4,4"/>
  <!-- y labels -->
  {ylabels}
  <!-- end dot -->
  <circle cx="{px(len(curve)-1):.1f}" cy="{py(curve[-1]):.1f}" r="4" fill="{color}"/>
</svg>"""


# ── HTML page ──────────────────────────────────────────────────────────────────

_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{background:#080810;color:#c8d0e0;font-family:'SF Mono',Monaco,
     'Cascadia Code','Fira Code',monospace;font-size:13px;line-height:1.5}
.wrap{max-width:1300px;margin:0 auto;padding:24px 20px}

/* header */
.hdr{background:linear-gradient(135deg,#0d1117 0%,#0a0f1e 100%);
     border:1px solid #1e2d40;border-radius:12px;padding:24px 28px;
     margin-bottom:20px;display:flex;align-items:center;gap:20px}
.logo{font-size:22px;font-weight:700;letter-spacing:1px;
      background:linear-gradient(90deg,#00d4ff,#00ff88);
      -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.sub{color:#445;font-size:11px}
.ts{margin-left:auto;color:#334;font-size:11px;text-align:right}

/* stat grid */
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
      gap:12px;margin-bottom:20px}
.card{background:#0d1117;border:1px solid #1a2535;border-radius:10px;
      padding:16px 18px;transition:border-color .2s}
.card:hover{border-color:#2a3f5a}
.card .label{color:#445;font-size:10px;text-transform:uppercase;
             letter-spacing:.08em;margin-bottom:6px}
.card .val{font-size:22px;font-weight:700;letter-spacing:.5px}
.card .sub2{font-size:10px;color:#334;margin-top:3px}
.g{color:#00ff88}.r{color:#ff4466}.y{color:#ffd700}.c{color:#00d4ff}
.w{color:#e8edf5}

/* mini bar */
.bar-wrap{height:4px;background:#1a2535;border-radius:2px;
          margin-top:8px;overflow:hidden}
.bar-fill{height:100%;border-radius:2px;transition:width .4s}

/* chart panel */
.panel{background:#0d1117;border:1px solid #1a2535;border-radius:10px;
       margin-bottom:20px}
.panel-hdr{padding:14px 18px;border-bottom:1px solid #1a2535;
           font-size:11px;text-transform:uppercase;letter-spacing:.1em;
           color:#556;display:flex;align-items:center;gap:8px}
.panel-hdr span{font-size:14px;color:#00d4ff}
.panel-body{padding:16px 18px}

/* tables */
table{width:100%;border-collapse:collapse;font-size:12px}
th{color:#334;font-size:10px;text-transform:uppercase;letter-spacing:.08em;
   padding:8px 12px;text-align:right;border-bottom:1px solid #131a26;
   white-space:nowrap}
th:first-child,th:nth-child(2),th:nth-child(3){text-align:left}
td{padding:9px 12px;border-bottom:1px solid #0f1520;text-align:right;
   white-space:nowrap}
td:first-child,td:nth-child(2),td:nth-child(3){text-align:left}
tr:last-child td{border-bottom:none}
tr:hover td{background:#0f1825}
.badge{display:inline-block;padding:2px 8px;border-radius:4px;
       font-size:10px;font-weight:700;letter-spacing:.05em}
.buy{background:#00ff8820;color:#00ff88;border:1px solid #00ff8840}
.sell{background:#ff446620;color:#ff4466;border:1px solid #ff446640}
.win{color:#00ff88}.loss{color:#ff4466}
.prog-wrap{display:flex;align-items:center;gap:6px}
.prog-bg{height:6px;width:60px;background:#1a2535;border-radius:3px;overflow:hidden}
.prog-fg{height:100%;border-radius:3px}

/* footer */
.foot{text-align:center;color:#223;font-size:10px;margin-top:24px}
"""

def _stat_card(label: str, value: str, color: str = "w",
               sub: str = "", bar_pct: float = None,
               bar_color: str = "#00d4ff") -> str:
    bar = ""
    if bar_pct is not None:
        pct = min(max(bar_pct, 0), 100)
        bar = f'<div class="bar-wrap"><div class="bar-fill" style="width:{pct:.1f}%;background:{bar_color}"></div></div>'
    return (f'<div class="card">'
            f'<div class="label">{label}</div>'
            f'<div class="val {color}">{value}</div>'
            f'{"<div class=sub2>"+sub+"</div>" if sub else ""}'
            f'{bar}'
            f'</div>')


def _color_val(v: float, lo: float = 0, hi: float = 0) -> str:
    if v > hi:   return "g"
    if v < lo:   return "r"
    return "y"


def generate_html(portfolio: Portfolio, equity_curve: list[float],
                  mode: str = "safe", title: str = "Backtest Report") -> str:
    s    = portfolio.stats()
    prof = config.PROFILES.get(mode, config.ACTIVE_PROFILE)
    ts   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    balance   = s.get("balance", config.STARTING_BALANCE)
    peak      = s.get("peak_balance", balance)
    pnl       = s.get("total_pnl", 0)
    wr        = s.get("win_rate", 0)
    avg_rr    = s.get("avg_rr", 0)
    pf        = s.get("profit_factor", 0)
    trades    = s.get("trades", 0)
    dd        = s.get("drawdown_pct", 0)
    avg_w     = s.get("avg_win", 0)
    avg_l     = s.get("avg_loss", 0)
    start_bal = config.STARTING_BALANCE
    pnl_pct   = pnl / start_bal * 100 if start_bal else 0

    pnl_color    = "#00ff88" if pnl >= 0 else "#ff4466"
    pnl_cls      = "g" if pnl >= 0 else "r"
    wr_color     = "#00ff88" if wr >= 55 else ("#ffd700" if wr >= 45 else "#ff4466")
    pf_cls       = "g" if pf >= 1.5 else ("y" if pf >= 1.0 else "r")
    rr_cls       = "g" if avg_rr >= 2.5 else "y"
    dd_cls       = "r" if dd > 15 else ("y" if dd > 5 else "g")
    mode_color   = "#ff4466" if mode == "aggressive" else "#00d4ff"
    mode_label   = prof.get("label", mode.title())

    # ── stat cards ────────────────────────────────────────────────────────────
    cards = "".join([
        _stat_card("Net P&L", f'{"+" if pnl>=0 else ""}{pnl_pct:.1f}%',
                   pnl_cls, f'${pnl:+,.2f}',
                   abs(pnl_pct), pnl_color),
        _stat_card("Final Balance", f"${balance:,.2f}", "w",
                   f"Started ${start_bal:,.0f}"),
        _stat_card("Win Rate", f"{wr:.1f}%",
                   "g" if wr>=55 else ("y" if wr>=45 else "r"),
                   f"{trades} trades", wr, wr_color),
        _stat_card("Avg R:R", f"{avg_rr:.2f}:1", rr_cls,
                   f"Min required {prof.get('min_rr',2):.0f}:1"),
        _stat_card("Profit Factor", f"{pf:.2f}", pf_cls,
                   "≥1.5 is institutional grade"),
        _stat_card("Max Drawdown", f"{dd:.1f}%", dd_cls,
                   f"Limit {prof.get('max_drawdown_pct',0.25)*100:.0f}%",
                   dd, "#ff4466"),
        _stat_card("Avg Winner", f"${avg_w:+,.2f}", "g"),
        _stat_card("Avg Loser",  f"${avg_l:+,.2f}", "r"),
    ])

    # ── open trades table ─────────────────────────────────────────────────────
    open_rows = ""
    prices_snap = {t.pair: t.entry_price for t in portfolio.open_trades}
    for t in portfolio.open_trades:
        upnl = t.unrealised_pnl(t.entry_price)
        upnl_cls = "win" if upnl >= 0 else "loss"
        badge = ('<span class="badge buy">BUY ▲</span>' if t.direction == 1
                 else '<span class="badge sell">SELL ▼</span>')
        open_rows += f"""<tr>
            <td><code style="color:#445">{t.id}</code></td>
            <td><b style="color:#c8d0e0">{t.pair.replace('=X','')}</b></td>
            <td>{badge}</td>
            <td>{t.entry_price:.5f}</td>
            <td style="color:#556">{t.stop_loss:.5f}</td>
            <td style="color:#556">{t.take_profit:.5f}</td>
            <td style="color:#ffd700">{t.rr_ratio:.1f}:1</td>
            <td>{t.units:,}</td>
            <td class="{upnl_cls}">${upnl:+,.2f}</td>
        </tr>"""
    if not open_rows:
        open_rows = '<tr><td colspan="9" style="text-align:center;color:#334;padding:20px">No open positions</td></tr>'

    # ── closed trades table ───────────────────────────────────────────────────
    closed_rows = ""
    for t in list(reversed(portfolio.closed_trades))[:20]:
        pnl_cls2 = "win" if t.pnl >= 0 else "loss"
        outcome  = "✓" if t.pnl >= 0 else "✗"
        badge = ('<span class="badge buy">BUY ▲</span>' if t.direction == 1
                 else '<span class="badge sell">SELL ▼</span>')
        opened = t.opened_at.strftime("%m/%d %H:%M") if t.opened_at else "—"
        closed = t.closed_at.strftime("%m/%d %H:%M") if t.closed_at else "—"
        closed_rows += f"""<tr>
            <td><code style="color:#445">{t.id}</code></td>
            <td><b style="color:#c8d0e0">{t.pair.replace('=X','')}</b></td>
            <td>{badge}</td>
            <td>{t.entry_price:.5f}</td>
            <td>{""+str(f'{t.exit_price:.5f}') if t.exit_price else '—'}</td>
            <td style="color:#ffd700">{t.rr_ratio:.1f}:1</td>
            <td style="color:#556">{opened}</td>
            <td style="color:#556">{closed}</td>
            <td class="{pnl_cls2}">{outcome} ${t.pnl:+,.2f}</td>
        </tr>"""
    if not closed_rows:
        closed_rows = '<tr><td colspan="9" style="text-align:center;color:#334;padding:20px">No closed trades</td></tr>'

    chart = _equity_svg(equity_curve)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GQ Forex Bot — {title}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">

  <!-- header -->
  <div class="hdr">
    <div>
      <div class="logo">GQ FOREX BOT</div>
      <div class="sub">ICT / Smart Money Concepts  ·  Multi-Timeframe  ·  4-Gate Strategy</div>
    </div>
    <div style="margin-left:20px">
      <div style="display:inline-block;padding:4px 14px;border-radius:20px;font-size:11px;
                  font-weight:700;letter-spacing:.08em;
                  background:{mode_color}18;color:{mode_color};
                  border:1px solid {mode_color}40">{mode_label}</div>
    </div>
    <div class="ts">
      <div style="color:#556;font-size:18px;font-weight:700">{title}</div>
      <div style="color:#334;margin-top:4px">{ts}</div>
    </div>
  </div>

  <!-- stat cards -->
  <div class="grid">{cards}</div>

  <!-- equity curve -->
  <div class="panel">
    <div class="panel-hdr"><span>▸</span> EQUITY CURVE
      <span style="margin-left:auto;font-size:11px;color:#334">
        Start ${start_bal:,.0f} → Peak ${peak:,.0f} → Final ${balance:,.2f}
      </span>
    </div>
    <div class="panel-body">{chart}</div>
  </div>

  <!-- open positions -->
  <div class="panel">
    <div class="panel-hdr"><span>◈</span> OPEN POSITIONS
      <span style="margin-left:auto">{len(portfolio.open_trades)} position(s)</span>
    </div>
    <div class="panel-body">
      <table>
        <thead><tr>
          <th>ID</th><th>Pair</th><th>Dir</th>
          <th>Entry</th><th>Stop Loss</th><th>Take Profit</th>
          <th>R:R</th><th>Units</th><th>Unrealised P&L</th>
        </tr></thead>
        <tbody>{open_rows}</tbody>
      </table>
    </div>
  </div>

  <!-- closed trades -->
  <div class="panel">
    <div class="panel-hdr"><span>◇</span> CLOSED TRADES (last 20)
      <span style="margin-left:auto">{trades} total</span>
    </div>
    <div class="panel-body">
      <table>
        <thead><tr>
          <th>ID</th><th>Pair</th><th>Dir</th>
          <th>Entry</th><th>Exit</th><th>R:R</th>
          <th>Opened</th><th>Closed</th><th>P&L</th>
        </tr></thead>
        <tbody>{closed_rows}</tbody>
      </table>
    </div>
  </div>

  <!-- strategy settings -->
  <div class="panel">
    <div class="panel-hdr"><span>⚙</span> STRATEGY SETTINGS</div>
    <div class="panel-body">
      <table>
        <thead><tr>
          <th style="text-align:left">Parameter</th>
          <th style="text-align:left">Value</th>
          <th style="text-align:left">Parameter</th>
          <th style="text-align:left">Value</th>
        </tr></thead>
        <tbody>
          <tr>
            <td style="color:#445">Risk per trade</td>
            <td class="c">{prof.get('risk_per_trade',0)*100:.1f}%</td>
            <td style="color:#445">Min R:R</td>
            <td class="c">{prof.get('min_rr',2):.0f}:1</td>
          </tr>
          <tr>
            <td style="color:#445">Leverage</td>
            <td class="c">{prof.get('leverage',10)}x</td>
            <td style="color:#445">Max drawdown</td>
            <td class="c">{prof.get('max_drawdown_pct',0.1)*100:.0f}%</td>
          </tr>
          <tr>
            <td style="color:#445">Portfolio heat limit</td>
            <td class="c">{prof.get('portfolio_heat',0.05)*100:.0f}%</td>
            <td style="color:#445">Daily loss halt</td>
            <td class="c">{prof.get('daily_loss_pct',0.03)*100:.0f}%</td>
          </tr>
          <tr>
            <td style="color:#445">Killzone required</td>
            <td class="{"g" if prof.get("require_killzone") else "r"}">\
{"✓ Yes" if prof.get("require_killzone") else "✗ No"}</td>
            <td style="color:#445">Sweep required</td>
            <td class="{"g" if prof.get("require_sweep") else "y"}">\
{"✓ Yes" if prof.get("require_sweep") else "○ No"}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="foot">
    GQ Forex Bot · ICT / SMC Strategy · Generated {ts}<br>
    <span style="color:#1a2535">Paper trading only — not financial advice</span>
  </div>

</div>
</body>
</html>"""
    return html


def save_report(portfolio: Portfolio, equity_curve: list[float],
                mode: str = "safe", path: str = "report.html") -> str:
    html = generate_html(portfolio, equity_curve, mode)
    Path(path).write_text(html, encoding="utf-8")
    return path
