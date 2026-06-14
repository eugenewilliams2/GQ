"""
Synthetic gate test — no Yahoo Finance needed.
Creates minimal engineered OHLCV data and runs each gate.
Prints exactly what passes/fails and why.
"""
import sys
sys.path.insert(0, ".")

import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

from forex_bot import config, indicators as ind
from forex_bot.strategy import (
    _validate, _gate_structure, _gate_poi, _gate_timing, _gate_momentum,
    generate_signal, MIN_LTF, MIN_HTF,
)

config.set_profile("aggressive")
PAIR = "EURUSD=X"

# ── Build synthetic uptrend 4H data (clear HH+HL pattern) ────────────────────
# We need at least MIN_HTF=60 4H bars with SWING_LOOKBACK=5 on each side.
# Pattern: uptrend with 8 clear HH+HL cycles.

def make_4h_uptrend(n_bars=120):
    """Steady uptrend: each 20-bar cycle makes a new higher high and higher low."""
    price = 1.0800
    rows  = []
    ts    = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
    cycle_len = 15

    for i in range(n_bars):
        cycle_pos = i % cycle_len
        # Up-leg: bars 0-9, down-leg: bars 10-14
        if cycle_pos < 10:
            drift = 0.0008   # strong impulse up
        else:
            drift = -0.0003  # shallow pullback

        open_ = price
        high  = open_ + 0.0010 + drift + abs(np.random.randn() * 0.0002)
        low   = open_ - 0.0002 + abs(np.random.randn() * 0.0001)
        close = open_ + drift + np.random.randn() * 0.0001

        high  = max(high, open_, close)
        low   = min(low,  open_, close)
        rows.append({"open": open_, "high": high, "low": low,
                     "close": close, "volume": 1000.0})
        price = close
        ts   += timedelta(hours=4)

    df = pd.DataFrame(rows)
    df.index = pd.date_range(start="2025-01-01 00:00", periods=n_bars, freq="4h", tz="UTC")
    return df


def make_1h_data(n_bars=250, last_price=1.0900, killzone_hour=14):
    """
    1H bars. Last bar is at killzone_hour UTC.
    Engineered so:
     - RSI ~50 (neutral, not overbought)
     - MACD histogram positive
     - Pin bar (long lower wick) on last bar → sweep signal
    """
    price = last_price - 0.0050  # start a bit lower
    rows  = []

    # We need the last bar at killzone_hour on 2025-06-15
    end_ts = datetime(2025, 6, 15, killzone_hour, 0, tzinfo=timezone.utc)
    start_ts = end_ts - timedelta(hours=n_bars - 1)

    for i in range(n_bars):
        drift = 0.00005 if i < n_bars * 0.6 else 0.00001
        open_ = price
        close = price + drift + np.random.randn() * 0.00005
        high  = max(open_, close) + abs(np.random.randn() * 0.00008)
        low   = min(open_, close) - abs(np.random.randn() * 0.00008)
        rows.append({"open": open_, "high": high, "low": low,
                     "close": close, "volume": max(500 + np.random.randn() * 50, 10.0)})
        price = close

    # Make the last bar a pin bar (bullish): long lower wick, closed back up
    # This also simulates a liquidity sweep
    last = rows[-1]
    last["open"]  = price - 0.0005
    last["close"] = price + 0.0003    # closed back above the sweep low
    last["high"]  = price + 0.0006
    last["low"]   = price - 0.0020   # spike below a prior swing low

    df = pd.DataFrame(rows)
    df.index = pd.date_range(start=start_ts, periods=n_bars, freq="1h", tz="UTC")
    return df


np.random.seed(42)
df_4h = make_4h_uptrend(n_bars=120)
df_1h = make_1h_data(n_bars=250, last_price=df_4h["close"].iloc[-1])

print("=" * 60)
print("Synthetic Gate Test  —  ICT 4-gate  (aggressive)")
print("=" * 60)
print(f"4H bars: {len(df_4h)}  (need ≥{MIN_HTF})")
print(f"1H bars: {len(df_1h)}  (need ≥{MIN_LTF})")
print(f"Last 1H bar UTC hour: {df_1h.index[-1].hour}  (NY killzone=12-15)")
print(f"Last 4H close: {df_4h['close'].iloc[-1]:.5f}")
print(f"Last 1H close: {df_1h['close'].iloc[-1]:.5f}")
print()

# ── Gate 0: Validate ─────────────────────────────────────────────────────────
ok = _validate(PAIR, df_1h, df_4h)
print(f"[Validate]  pass={ok}")
if not ok:
    # debug why
    print(f"  len(1H)={len(df_1h)} MIN_LTF={MIN_LTF}")
    print(f"  len(4H)={len(df_4h)} MIN_HTF={MIN_HTF}")
    print(f"  dqs_1h={ind.data_quality_score(df_1h):.2f}  dqs_4h={ind.data_quality_score(df_4h):.2f}")
    zv = (df_1h["volume"] == 0).sum()
    print(f"  zero_vol_1h={zv} ({zv/len(df_1h)*100:.1f}%)")

# ── Gate 1: Structure ─────────────────────────────────────────────────────────
direction = _gate_structure(df_4h)
print(f"\n[Gate 1 — Structure]  direction={direction}  (1=bull,-1=bear,0=unclear)")
sh, sl = ind.swing_points(df_4h, config.SWING_LOOKBACK)
swing_highs = sh.dropna().values
swing_lows  = sl.dropna().values
print(f"  swing highs found: {len(swing_highs)}  last 3: {swing_highs[-3:] if len(swing_highs)>=3 else swing_highs}")
print(f"  swing lows  found: {len(swing_lows)}   last 3: {swing_lows[-3:] if len(swing_lows)>=3 else swing_lows}")
adx_val, di_pos, di_neg = ind.adx(df_4h["high"], df_4h["low"], df_4h["close"], config.ATR_PERIOD)
print(f"  ADX={adx_val.iloc[-1]:.1f}  +DI={di_pos.iloc[-1]:.1f}  -DI={di_neg.iloc[-1]:.1f}  (need ADX>={config.ACTIVE_PROFILE['adx_min']})")

# ── Gate 2: POI ───────────────────────────────────────────────────────────────
if direction != 0:
    poi_ok, poi_zone, poi_label = _gate_poi(df_4h, df_1h, direction)
    price = float(df_1h["close"].iloc[-1])
    obs  = ind.find_order_blocks(df_4h, direction)
    fvgs = ind.find_fair_value_gaps(df_4h, direction)
    atr_4h = float(ind.atr(df_4h["high"], df_4h["low"], df_4h["close"], config.ATR_PERIOD).iloc[-1])
    print(f"\n[Gate 2 — POI]  pass={poi_ok}  label='{poi_label}'")
    print(f"  current price: {price:.5f}")
    print(f"  4H ATR: {atr_4h:.5f}")
    print(f"  order blocks found: {len(obs)}")
    for ob in obs[-3:]:
        print(f"    OB  low={ob['low']:.5f} high={ob['high']:.5f}  price_in={ob['low']<=price<=ob['high']}")
    print(f"  FVGs found: {len(fvgs)}")
    for fvg in fvgs[-3:]:
        lo = fvg.get('bottom', fvg.get('low', 0))
        hi = fvg.get('top', fvg.get('high', 0))
        print(f"    FVG bottom={lo:.5f} top={hi:.5f}  price_in={lo<=price<=hi}")
    if poi_zone:
        print(f"  zone: {poi_zone}")
else:
    print(f"\n[Gate 2 — POI]  SKIPPED (direction=0)")

# ── Gate 3: Timing ────────────────────────────────────────────────────────────
if direction != 0:
    timing_ok, timing_reasons = _gate_timing(df_1h, direction)
    bar_ts = df_1h.index[-1].to_pydatetime()
    kz_ok, kz_name = ind.in_killzone(bar_ts)
    sweep  = ind.detect_liquidity_sweep(df_1h, direction)
    print(f"\n[Gate 3 — Timing]  pass={timing_ok}  reasons={timing_reasons}")
    print(f"  bar_ts={bar_ts}  UTC hour={bar_ts.hour}")
    print(f"  in_killzone={kz_ok}  name='{kz_name}'")
    print(f"  liquidity_sweep={sweep}")
    print(f"  require_killzone={config.ACTIVE_PROFILE['require_killzone']}")
    print(f"  require_sweep={config.ACTIVE_PROFILE['require_sweep']}")
else:
    print(f"\n[Gate 3 — Timing]  SKIPPED (direction=0)")

# ── Gate 4: Momentum ─────────────────────────────────────────────────────────
if direction != 0:
    mom_ok, mom_reasons = _gate_momentum(df_1h, direction)
    rsi_v = ind.rsi(df_1h["close"], config.RSI_PERIOD).iloc[-1]
    _, _, hist = ind.macd(df_1h["close"], config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL)
    k, d = ind.stochastic(df_1h["high"], df_1h["low"], df_1h["close"])
    print(f"\n[Gate 4 — Momentum]  pass={mom_ok}  needed={config.ACTIVE_PROFILE['momentum_needed']}  reasons={mom_reasons}")
    print(f"  RSI={rsi_v:.1f}  (bull range: 35-{config.RSI_OVERBOUGHT})")
    print(f"  MACD hist={hist.iloc[-1]:.6f}  (need >0 for bull)")
    print(f"  Stoch K={k.iloc[-1]:.1f} D={d.iloc[-1]:.1f}")
    bull_eng = ind.bullish_engulfing(df_1h["open"], df_1h["close"]).iloc[-1]
    pin_bar  = ind.is_pin_bar(df_1h["open"], df_1h["high"], df_1h["low"], df_1h["close"], 1).iloc[-1]
    print(f"  bullish_engulfing={bull_eng}  pin_bar={pin_bar}")
else:
    print(f"\n[Gate 4 — Momentum]  SKIPPED (direction=0)")

# ── Full signal ───────────────────────────────────────────────────────────────
print()
print("=" * 60)
sig = generate_signal(PAIR, df_1h, df_4h)
if sig:
    print(f"SIGNAL GENERATED: {sig.direction} @ {sig.price:.5f}  R:R={sig.rr_ratio:.2f}  strength={sig.strength:.0%}")
    print(f"  reason: {sig.reason}")
else:
    print("NO SIGNAL GENERATED (at least one gate failed)")
