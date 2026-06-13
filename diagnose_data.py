"""
Run this on your Mac to diagnose why market data isn't loading.
  python diagnose_data.py
"""

import sys

print("=" * 55)
print("GQ Forex Bot — Data Feed Diagnostic")
print("=" * 55)

# 1. Python version
print(f"\nPython: {sys.version}")

# 2. yfinance version
try:
    import yfinance as yf
    print(f"yfinance: {yf.__version__}")
except ImportError:
    print("\n[FAIL] yfinance is NOT installed.")
    print("  Fix:  pip install yfinance")
    sys.exit(1)

# 3. pandas version
try:
    import pandas as pd
    print(f"pandas : {pd.__version__}")
except ImportError:
    print("[FAIL] pandas is NOT installed.")
    print("  Fix:  pip install pandas")
    sys.exit(1)

# 4. Test a single pair with a short window
print("\n--- Fetching EURUSD=X (30d, 1h) ---")
import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    df = yf.download("EURUSD=X", period="30d", interval="1h",
                     auto_adjust=True, progress=False)

print(f"  Returned type     : {type(df)}")
print(f"  Shape             : {df.shape}")
print(f"  Columns           : {list(df.columns)}")
print(f"  Empty?            : {df.empty}")

if df.empty:
    print("\n[FAIL] No data returned for EURUSD=X")
    print("  Possible causes:")
    print("  1. yfinance is outdated  →  pip install -U yfinance")
    print("  2. Yahoo Finance is temporarily down — try again in 60s")
    print("  3. No internet connection")
else:
    # Check column format
    if hasattr(df.columns, "levels"):
        print(f"\n  MultiIndex detected: {df.columns.tolist()[:4]}…")
        print("  (This is handled automatically by the bot)")
    else:
        print(f"\n  Flat columns: {df.columns.tolist()}")

    print(f"\n[OK] Data received  ({len(df)} rows, "
          f"{df.index[0].date()} → {df.index[-1].date()})")
    print(f"  Sample close prices:\n{df[['Close']].tail(3).to_string()}")

# 5. Quick test across all pairs
print("\n--- Testing all 7 pairs ---")
PAIRS = ["EURUSD=X","GBPUSD=X","USDJPY=X","USDCHF=X",
         "AUDUSD=X","USDCAD=X","NZDUSD=X"]
ok, fail = [], []
for p in PAIRS:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d = yf.download(p, period="5d", interval="1h",
                        auto_adjust=True, progress=False)
    if not d.empty:
        ok.append(p)
    else:
        fail.append(p)

print(f"  OK   : {ok}")
print(f"  FAIL : {fail if fail else 'none — all good!'}")

if fail:
    print("\n[NEXT STEP] Run:  pip install -U yfinance")
else:
    print("\n[ALL OK] Data feed is working. Run your backtest:")
    print("  python run.py backtest --mode safe")
