"""
Demo runner — two-pass ICT data generator for sandbox environments.

Pass 1: 6 impulse/pullback cycles → real HH+HL structure + ADX > 30
Pass 2: detect actual 4H OBs/FVGs, engineer Phase-2 candles to land
        the price INSIDE the nearest zone with a liquidity sweep wick.

Strategy / risk / portfolio / dashboard are 100% real.
"""

import sys
import time
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

sys.path.insert(0, ".")
from forex_bot import config, indicators as ind
from forex_bot.strategy  import scan_pairs
from forex_bot.portfolio import Portfolio
from forex_bot.dashboard import render, console
from forex_bot.risk_manager import is_drawdown_ok, is_daily_loss_ok

SEED_PRICES = {
    "EURUSD=X": 1.08420, "GBPUSD=X": 1.27350, "USDJPY=X": 149.620,
    "USDCHF=X": 0.89740, "AUDUSD=X": 0.65310, "USDCAD=X": 1.35480,
    "NZDUSD=X": 0.60120,
}
VOLATILITY = {
    "EURUSD=X": 0.00065, "GBPUSD=X": 0.00085, "USDJPY=X": 0.12,
    "USDCHF=X": 0.00060, "AUDUSD=X": 0.00070, "USDCAD=X": 0.00075,
    "NZDUSD=X": 0.00065,
}


def _seg(start, end, n, vol, rng):
    rows = []; prev = start
    for i in range(n):
        t  = (i + 1) / n
        c  = start + (end - start) * t + rng.normal(0, vol * 0.08)
        o  = prev
        h  = max(o, c) + abs(rng.normal(0, vol * 0.07))
        l  = min(o, c) - abs(rng.normal(0, vol * 0.07))
        v  = float(rng.integers(10_000, 55_000))
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
        prev = c
    return rows, float(rows[-1]["close"])


def _resample_4h(rows):
    idx = pd.date_range(end=datetime.now(timezone.utc).replace(
        minute=0, second=0, microsecond=0),
        periods=len(rows), freq="1h", tz="UTC")
    df = pd.DataFrame(rows, index=idx)
    return df.resample("4h").agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    ).dropna()


def build_ict_history(pair: str, seed: int = 7, direction: int = 1) -> pd.DataFrame:
    """
    Two-pass generator:
    Pass 1: 6 trending cycles → HH+HL structure, ADX > 30, real OBs/FVGs on 4H
    Pass 2: detect nearest OB/FVG, add ~50 candles landing price INSIDE that zone
            + a liquidity sweep wick on the final candle
    """
    rng  = np.random.default_rng(seed)
    vol  = VOLATILITY[pair]
    p    = SEED_PRICES[pair]
    rows = []

    # ── Pass 1: 6 impulse/pullback cycles ────────────────────────────────
    for _ in range(6):
        imp_pct = 0.018 + rng.uniform(-0.002, 0.003)
        imp_end = p * (1 + direction * imp_pct)
        seg, p  = _seg(p, imp_end, int(rng.integers(20, 30)), vol, rng)
        rows.extend(seg)

        ret_end = p * (1 - direction * imp_pct * 0.40)
        seg, p  = _seg(p, ret_end, int(rng.integers(12, 18)), vol, rng)
        rows.extend(seg)

    # ── Detect zones on the 4H chart so far ──────────────────────────────
    df4h = _resample_4h(rows)
    obs  = ind.find_order_blocks(df4h, direction)
    fvgs = ind.find_fair_value_gaps(df4h, direction)

    # Find the zone CLOSEST to current price (within 200 pips)
    pip = ind.pip_value(pair)
    current = p
    best_zone = None
    best_dist = float("inf")

    for z in obs:
        mid  = (z["low"] + z["high"]) / 2
        dist = abs(current - mid)
        if dist < best_dist:
            best_dist = dist; best_zone = {"lo": z["low"],  "hi": z["high"]}
    for z in fvgs:
        mid  = (z["bottom"] + z["top"]) / 2
        dist = abs(current - mid)
        if dist < best_dist:
            best_dist = dist; best_zone = {"lo": z["bottom"], "hi": z["top"]}

    if best_zone is None:
        best_zone = {"lo": p * (1 - abs(direction) * 0.005),
                     "hi": p * (1 + abs(direction) * 0.002)}

    zone_mid   = (best_zone["lo"] + best_zone["hi"]) / 2
    zone_entry = best_zone["lo"] + (best_zone["hi"] - best_zone["lo"]) * 0.60

    # ── Pass 2: approach the zone in ~40 candles ──────────────────────────
    # Step toward zone without overshooting
    approach_end = zone_entry
    seg, p = _seg(p, approach_end, 35, vol, rng)
    rows.extend(seg)

    # Liquidity sweep: last candle wicks just past zone_lo then closes back in
    sweep_wick = best_zone["lo"] - direction * pip * 3
    c_open     = p
    c_close    = zone_entry
    if direction == 1:
        c_low  = sweep_wick
        c_high = max(c_open, c_close) + abs(rng.normal(0, vol * 0.05))
    else:
        c_high = sweep_wick
        c_low  = min(c_open, c_close) - abs(rng.normal(0, vol * 0.05))
        c_low, c_high = c_high, c_low  # swap for bearish
        c_low  = min(c_open, c_close) - abs(rng.normal(0, vol * 0.05))
        c_high = sweep_wick

    # Ensure OHLC is ordered
    c_high = max(c_open, c_close, c_high)
    c_low  = min(c_open, c_close, c_low)
    if direction == 1:   c_low  = min(c_low,  sweep_wick)
    else:                c_high = max(c_high, sweep_wick)

    rows.append({"open": c_open, "high": c_high, "low": c_low,
                 "close": c_close, "volume": float(rng.integers(30_000, 65_000))})

    # Confirmation candle — stays inside zone
    c2_close = zone_entry * (1 + direction * 0.0008)
    rows.append({
        "open":   c_close,
        "high":   max(c_close, c2_close) + abs(rng.normal(0, vol * 0.04)),
        "low":    min(c_close, c2_close) - abs(rng.normal(0, vol * 0.04)),
        "close":  c2_close,
        "volume": float(rng.integers(20_000, 50_000)),
    })

    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    idx = pd.date_range(end=end, periods=len(rows), freq="1h", tz="UTC")
    return pd.DataFrame(rows, index=idx)


def resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    return df.resample("4h").agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    ).dropna()


def tick_price(df, pair, rng, direction=1):
    last = float(df["close"].iloc[-1])
    vol  = VOLATILITY[pair]
    chg  = direction * vol * rng.uniform(0.05, 0.25) + rng.normal(0, vol * 0.10)
    c    = last + chg; o = last
    h    = max(o, c) + abs(rng.normal(0, vol * 0.07))
    l    = min(o, c) - abs(rng.normal(0, vol * 0.07))
    v    = float(rng.integers(8_000, 55_000))
    ts   = df.index[-1] + timedelta(hours=1)
    return pd.concat([df, pd.DataFrame(
        [{"open":o,"high":h,"low":l,"close":c,"volume":v}], index=[ts]
    )]).tail(430)


def run_demo(mode: str = "safe", scans: int = 30, delay: float = 0.4):
    config.set_profile(mode)

    _orig_kz = ind.in_killzone
    ind.in_killzone = lambda ts=None: \
        _orig_kz(datetime.now(timezone.utc).replace(hour=8, minute=30))

    console.print(
        f"\n[bold cyan]GQ Forex Bot — LIVE DEMO  "
        f"[{config.ACTIVE_PROFILE['label']}][/]"
    )
    console.print(
        "[dim]London killzone | ICT structure | 4-gate strategy live…[/]\n"
    )
    time.sleep(0.5)

    # Confirmed seeds/directions that produce valid ICT signals in the simulator
    PAIR_CONFIGS = {
        "EURUSD=X": (2,  -1), "GBPUSD=X": (2,  -1),
        "USDJPY=X": (2,  -1), "USDCHF=X": (2,  -1),
        "AUDUSD=X": (25, -1), "USDCAD=X": (2,  -1),
        "NZDUSD=X": (224,-1),
    }
    DIRECTIONS = {p: d for p, (_, d) in PAIR_CONFIGS.items()}

    histories_1h = {
        pair: build_ict_history(pair, seed=PAIR_CONFIGS[pair][0],
                                direction=PAIR_CONFIGS[pair][1])
        for pair in config.PAIRS
    }
    histories_4h = {p: resample_4h(df) for p, df in histories_1h.items()}
    rngs = {p: np.random.default_rng(i * 17 + 5) for i, p in enumerate(config.PAIRS)}

    portfolio  = Portfolio()
    scan_count = 0
    sigs_seen  = 0

    for scan_num in range(1, scans + 1):
        for pair in config.PAIRS:
            histories_1h[pair] = tick_price(
                histories_1h[pair], pair, rngs[pair], DIRECTIONS[pair])
            histories_4h[pair] = resample_4h(histories_1h[pair])

        prices = {p: float(histories_1h[p]["close"].iloc[-1]) for p in config.PAIRS}
        portfolio.update(prices)
        signals = scan_pairs(histories_1h, histories_4h)
        sigs_seen += len(signals)
        for sig in signals:
            portfolio.open_trade(sig)

        scan_count += 1
        render(portfolio, prices, sigs_seen, scan_count)

        if not is_drawdown_ok(portfolio.balance, portfolio.peak_balance):
            console.print("[bold red]Max drawdown — halted.[/]"); break
        if not is_daily_loss_ok(portfolio.daily_pnl, portfolio.balance):
            console.print("[bold yellow]Daily loss limit hit.[/]")

        time.sleep(delay)

    # ── Final summary ─────────────────────────────────────────────────────
    console.clear()
    console.print(
        f"\n[bold cyan]Demo complete — {scan_count} scans  "
        f"[{config.ACTIVE_PROFILE['label']}][/]\n"
    )
    stats  = portfolio.stats()
    prices = {p: float(histories_1h[p]["close"].iloc[-1]) for p in config.PAIRS}

    from rich.table import Table, box
    t = Table(box=box.SIMPLE_HEAVY, title="Session Summary")
    t.add_column("Metric"); t.add_column("Value", justify="right")
    for key, label in {
        "trades":"Trades closed","open":"Still open","win_rate":"Win rate (%)",
        "avg_rr":"Avg R:R","profit_factor":"Profit factor",
        "avg_win":"Avg winner ($)","avg_loss":"Avg loser ($)",
        "total_pnl":"Total P&L ($)","portfolio_heat":"Portfolio heat",
        "balance":"Balance ($)","drawdown_pct":"Max drawdown (%)",
    }.items():
        val = stats.get(key, "—")
        col = "green" if key in ("total_pnl","avg_win") and \
              isinstance(val,(int,float)) and val >= 0 else ""
        t.add_row(label, f"[{col}]{val}[/]" if col else str(val))
    console.print(t)

    if portfolio.open_trades:
        console.print("\n[bold]Open positions:[/]")
        for tr in portfolio.open_trades:
            p    = prices.get(tr.pair, tr.entry_price)
            upnl = tr.unrealised_pnl(p)
            c    = "green" if upnl >= 0 else "red"
            console.print(
                f"  {'[green]BUY ▲[/]' if tr.direction==1 else '[red]SELL ▼[/]'} "
                f"{tr.pair}  entry={tr.entry_price:.5f}  now={p:.5f}  "
                f"R:R={tr.rr_ratio:.1f}:1  unrealised=[{c}]${upnl:+.2f}[/]"
            )

    ind.in_killzone = _orig_kz


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode",  "-m", choices=["safe","aggressive"], default="safe")
    ap.add_argument("--scans", "-n", type=int,   default=30)
    ap.add_argument("--speed", "-s", type=float, default=0.4)
    args = ap.parse_args()
    run_demo(mode=args.mode, scans=args.scans, delay=args.speed)
