"""
Gate-by-gate diagnostic for the 4-gate strategy on real downloaded data.
Run: python3 debug_strategy.py

Reports exactly how many bars pass/fail each gate per pair,
so we can pinpoint which gate blocks all trades.
"""

import sys, warnings
sys.path.insert(0, ".")

import pandas as pd
import yfinance as yf
from collections import defaultdict

from forex_bot import config, indicators as ind
from forex_bot.strategy import (
    MIN_LTF, MIN_HTF,
    _gate_structure, _gate_poi, _gate_timing, _gate_momentum,
)

config.set_profile("aggressive")

PAIRS = config.PAIRS
START = "2025-06-01"
END   = "2025-12-31"

print("=" * 60)
print("GQ Forex Bot — Strategy Gate Diagnostic")
print(f"Period: {START} → {END}  mode: aggressive")
print("=" * 60)

# ── Download data ─────────────────────────────────────────────────────────────
raw = {}
for pair in PAIRS:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = yf.download(pair, start=START, end=END,
                         interval="1h", auto_adjust=True, progress=False)
    if df is None or df.empty:
        print(f"  {pair}: NO DATA")
        continue
    if isinstance(df.columns, pd.MultiIndex):
        df = df.xs(pair, axis=1, level=1) if pair in df.columns.get_level_values(1) \
             else df.droplevel(1, axis=1)
    df.columns = [c.lower() for c in df.columns]
    df = df[["open","high","low","close","volume"]].dropna()
    df.index = pd.to_datetime(df.index, utc=True)
    raw[pair] = df
    print(f"  {pair}: {len(df)} 1H bars")

def resample_4h(df):
    return df.resample("4h").agg(
        {"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    ).dropna()

# ── Sample every 24 bars (once per day) to keep it fast ──────────────────────
print("\nRunning gate checks (sampling every 24h)...\n")

totals = defaultdict(lambda: defaultdict(int))

for pair, df_full in raw.items():
    df4_full = resample_4h(df_full)
    timestamps = df_full.index[MIN_LTF::24]   # every 24 bars after warmup

    for ts in timestamps:
        df1 = df_full[df_full.index <= ts]
        df4 = df4_full[df4_full.index <= ts]

        if len(df1) < MIN_LTF or len(df4) < MIN_HTF:
            totals[pair]["warmup"] += 1
            continue

        # Gate 1
        direction = _gate_structure(df4)
        if direction == 0:
            totals[pair]["g1_fail"] += 1
            continue
        totals[pair]["g1_pass"] += 1

        # Gate 2
        from forex_bot.strategy import _gate_poi
        poi_ok, _, _ = _gate_poi(df4, df1, direction)
        if not poi_ok:
            totals[pair]["g2_fail"] += 1
            continue
        totals[pair]["g2_pass"] += 1

        # Gate 3
        timing_ok, _ = _gate_timing(df1, direction)
        if not timing_ok:
            totals[pair]["g3_fail"] += 1
            continue
        totals[pair]["g3_pass"] += 1

        # Gate 4
        mom_ok, _ = _gate_momentum(df1, direction)
        if not mom_ok:
            totals[pair]["g4_fail"] += 1
            continue
        totals[pair]["g4_pass"] += 1

        totals[pair]["all_pass"] += 1

# ── Report ────────────────────────────────────────────────────────────────────
print(f"{'Pair':<12} {'G1✓':>5} {'G1✗':>5} {'G2✓':>5} {'G2✗':>5} "
      f"{'G3✓':>5} {'G3✗':>5} {'G4✓':>5} {'G4✗':>5} {'SIGNAL':>7}")
print("-" * 70)

for pair in PAIRS:
    t = totals[pair]
    print(
        f"{pair.replace('=X',''):<12}"
        f" {t['g1_pass']:>5} {t['g1_fail']:>5}"
        f" {t['g2_pass']:>5} {t['g2_fail']:>5}"
        f" {t['g3_pass']:>5} {t['g3_fail']:>5}"
        f" {t['g4_pass']:>5} {t['g4_fail']:>5}"
        f" {t['all_pass']:>7}"
    )

print()
print("Key: G1=Structure  G2=OB/FVG  G3=Killzone  G4=Momentum")
print("     ✓=passed  ✗=failed at that gate")
