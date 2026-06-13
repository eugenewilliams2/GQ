"""
Central configuration for the GQ Forex Trading Bot.
Edit these values to tune behaviour without touching strategy code.
"""

# ── Pairs to trade (yfinance tickers) ──────────────────────────────────────
PAIRS = [
    "EURUSD=X",
    "GBPUSD=X",
    "USDJPY=X",
    "USDCHF=X",
    "AUDUSD=X",
    "USDCAD=X",
    "NZDUSD=X",
]

# ── Paper-trading account ───────────────────────────────────────────────────
STARTING_BALANCE = 10_000.0   # USD
LEVERAGE         = 50          # max units per dollar of margin
LOT_SIZE         = 1_000       # 1 micro-lot = 1,000 base units

# ── Risk management ────────────────────────────────────────────────────────
RISK_PER_TRADE   = 0.01        # fraction of balance to risk per trade (1 %)
MAX_OPEN_TRADES  = 5
STOP_LOSS_PIPS   = 20
TAKE_PROFIT_PIPS = 40
MAX_DRAWDOWN_PCT = 0.20        # halt trading if drawdown exceeds 20 %

# ── Strategy parameters ────────────────────────────────────────────────────
EMA_FAST         = 9
EMA_SLOW         = 21
RSI_PERIOD       = 14
RSI_OVERBOUGHT   = 70
RSI_OVERSOLD     = 30
MACD_FAST        = 12
MACD_SLOW        = 26
MACD_SIGNAL      = 9
BB_PERIOD        = 20
BB_STD           = 2.0
ATR_PERIOD       = 14

# ── Data / scheduling ──────────────────────────────────────────────────────
CANDLE_INTERVAL  = "1h"        # yfinance interval: 1m 5m 15m 30m 1h 4h 1d
CANDLE_LOOKBACK  = "60d"       # history window fetched on each refresh
SCAN_INTERVAL_S  = 60          # seconds between live scans

# ── Backtesting ────────────────────────────────────────────────────────────
BACKTEST_START   = "2024-01-01"
BACKTEST_END     = "2025-12-31"
BACKTEST_INTERVAL= "1h"

# ── Logging ────────────────────────────────────────────────────────────────
LOG_FILE         = "forex_bot.log"
