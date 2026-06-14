"""
HTML report for the strategy comparison — a self-contained dark dashboard with
out-of-sample equity curves and the honest verdict. No external dependencies;
inline SVG, opens straight in a browser.
"""

from __future__ import annotations
import datetime as _dt

import numpy as np

from forex_bot import metrics
from forex_bot.compare import run_comparison


def _equity_svg(equity: np.ndarray, w: int = 720, h: int = 150) -> str:
    if equity is None or len(equity) < 2:
        return '<svg viewBox="0 0 720 150"></svg>'
    y = np.asarray(equity, float)
    if len(y) > 800:                                  # downsample for a lean SVG
        y = y[np.linspace(0, len(y) - 1, 800).astype(int)]
    lo, hi = float(y.min()), float(y.max())
    rng = hi - lo or 1.0
    n = len(y)
    pts = [(x / (n - 1) * w, h - (v - lo) / rng * (h - 10) - 5) for x, v in enumerate(y)]
    path = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
    base_y = h - (10_000 - lo) / rng * (h - 10) - 5 if lo <= 10_000 <= hi else None
    up = y[-1] >= y[0]
    color = "#4ade80" if up else "#f87171"
    baseline = (f'<line x1="0" y1="{base_y:.1f}" x2="{w}" y2="{base_y:.1f}" '
                f'stroke="#475569" stroke-dasharray="4 4" stroke-width="1"/>'
                if base_y is not None else "")
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="none">'
            f'{baseline}<polyline fill="none" stroke="{color}" stroke-width="1.6" '
            f'points="{path}"/></svg>')


def _metric_chip(label: str, value: str, good: bool | None = None) -> str:
    color = "" if good is None else ("color:#4ade80" if good else "color:#f87171")
    return (f'<div class="chip"><span class="lbl">{label}</span>'
            f'<span class="val" style="{color}">{value}</span></div>')


def _card(name: str, p: metrics.Performance, equity: np.ndarray) -> str:
    edge = p.deflated_sharpe >= 0.95 and p.sharpe > 0
    badge = ('<span class="badge ok">EDGE?</span>' if edge
             else '<span class="badge no">NO EDGE</span>')
    chips = "".join([
        _metric_chip("Sharpe", f"{p.sharpe:.2f}", p.sharpe > 0),
        _metric_chip("Sortino", f"{p.sortino:.2f}", p.sortino > 0),
        _metric_chip("Profit factor", f"{p.profit_factor:.2f}", p.profit_factor > 1),
        _metric_chip("Max DD", f"{p.max_drawdown*100:.1f}%", p.max_drawdown < 0.2),
        _metric_chip("Win rate", f"{p.win_rate*100:.1f}%"),
        _metric_chip("Trades", f"{p.n_trades}"),
        _metric_chip("PSR", f"{p.psr:.2f}", p.psr > 0.95),
        _metric_chip("Deflated Sharpe", f"{p.deflated_sharpe:.2f}", edge),
        _metric_chip("Trials searched", f"{p.n_trials}"),
        _metric_chip("Total return", f"{p.total_return*100:+.1f}%", p.total_return > 0),
    ])
    return (f'<div class="card"><div class="card-head"><h3>{name}</h3>{badge}</div>'
            f'<div class="chart">{_equity_svg(equity)}</div>'
            f'<div class="chips">{chips}</div></div>')


def save_report(rows, path: str = "comparison_report.html") -> str:
    best = rows[0][1] if rows else None
    has_edge = best is not None and best.deflated_sharpe >= 0.95 and best.sharpe > 0
    verdict = (f"{rows[0][0]} clears the bar (DSR={best.deflated_sharpe:.2f}) — "
               "validate further before trusting it."
               if has_edge else
               "No strategy shows a credible edge out-of-sample after costs. "
               "All deflated Sharpe ratios are indistinguishable from luck.")
    vclass = "ok" if has_edge else "no"
    cards = "".join(_card(n, p, e) for n, p, e in rows)
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Forex Strategy Research — Out-of-Sample Comparison</title>
<style>
 :root{{--bg:#0b1120;--panel:#111a2e;--line:#1e293b;--txt:#e2e8f0;--mut:#64748b}}
 *{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--txt);
   font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;padding:28px}}
 h1{{font-size:20px;margin:0 0 4px}} .sub{{color:var(--mut);margin-bottom:20px}}
 .verdict{{padding:14px 18px;border-radius:10px;margin-bottom:24px;font-weight:600;
   border:1px solid}} .verdict.no{{background:#1f1416;border-color:#7f1d1d;color:#fca5a5}}
 .verdict.ok{{background:#0f1f17;border-color:#14532d;color:#86efac}}
 .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:16px}}
 .card{{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px}}
 .card-head{{display:flex;justify-content:space-between;align-items:center}}
 h3{{margin:0;font-size:15px;text-transform:uppercase;letter-spacing:.05em}}
 .badge{{font-size:11px;padding:3px 8px;border-radius:6px;font-weight:700}}
 .badge.no{{background:#7f1d1d;color:#fecaca}} .badge.ok{{background:#14532d;color:#bbf7d0}}
 .chart{{margin:12px 0;height:150px;background:#0a1324;border-radius:8px}}
 .chips{{display:grid;grid-template-columns:1fr 1fr;gap:6px}}
 .chip{{display:flex;justify-content:space-between;padding:5px 9px;background:#0d1730;
   border-radius:6px}} .chip .lbl{{color:var(--mut)}} .chip .val{{font-weight:600}}
 footer{{color:var(--mut);margin-top:24px;font-size:12px;border-top:1px solid var(--line);
   padding-top:12px}}
</style></head><body>
 <h1>Forex Strategy Research — Out-of-Sample Comparison</h1>
 <div class="sub">Walk-forward · after realistic costs · ranked by Deflated Sharpe · {now}</div>
 <div class="verdict {vclass}">VERDICT: {verdict}</div>
 <div class="grid">{cards}</div>
 <footer>Equity curves are pooled out-of-sample only. Dashed line = $10k start.
 Deflated Sharpe penalizes for the number of parameter combinations searched
 (Bailey &amp; López de Prado). Research tool — not investment advice, no live trading.</footer>
</body></html>"""
    with open(path, "w") as f:
        f.write(html)
    return path


def generate(data, path: str = "comparison_report.html", n_splits: int = 4) -> str:
    rows = run_comparison(data, n_splits=n_splits)
    return save_report(rows, path)
