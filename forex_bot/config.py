"""
Central configuration for the GQ Forex Trading Bot.
Risk profiles are selected at runtime via --mode safe | aggressive.
"""

# ── Pairs to trade ─────────────────────────────────────────────────────────
PAIRS = [
    "EURUSD=X",
    "GBPUSD=X",
    "USDJPY=X",
    "USDCHF=X",
    "AUDUSD=X",
    "USDCAD=X",
    "NZDUSD=X",
]

# ── Paper-trading account ──────────────────────────────────────────────────
STARTING_BALANCE = 10_000.0
LOT_SIZE         = 1_000       # 1 micro-lot = 1,000 base units

# ── Indicator parameters (shared across modes) ────────────────────────────
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

# ── Data / scheduling ─────────────────────────────────────────────────────
CANDLE_INTERVAL  = "1h"
CANDLE_LOOKBACK  = "60d"
SCAN_INTERVAL_S  = 60

# ── Backtesting ────────────────────────────────────────────────────────────
BACKTEST_START    = "2024-01-01"
BACKTEST_END      = "2025-12-31"
BACKTEST_INTERVAL = "1h"

# ── Logging ────────────────────────────────────────────────────────────────
LOG_FILE = "forex_bot.log"

# ══════════════════════════════════════════════════════════════════════════
# RISK PROFILES  — selected by passing --mode safe | aggressive
# ══════════════════════════════════════════════════════════════════════════

PROFILES = {
    "safe": {
        "label":             "SAFE  (low risk / steady returns)",
        "risk_per_trade":    0.005,   # 0.5 % of balance per trade
        "leverage":          10,
        "max_open_trades":   3,
        "stop_loss_pips":    15,
        "take_profit_pips":  45,      # 1:3 R:R
        "max_drawdown_pct":  0.10,    # halt at 10 % drawdown
        "min_strength":      0.67,    # need ≥ 67 % indicator agreement
        "momentum_needed":   3,       # gates 2 needs 3/4
        "entry_needed":      2,       # gate 3 needs 2/4
        "adx_min":           28,      # stronger trend required
    },
    "aggressive": {
        "label":             "AGGRESSIVE  (high risk / high reward)",
        "risk_per_trade":    0.025,   # 2.5 % of balance per trade
        "leverage":          50,
        "max_open_trades":   7,
        "stop_loss_pips":    25,
        "take_profit_pips":  75,      # 1:3 R:R but wider
        "max_drawdown_pct":  0.25,    # tolerates bigger swings
        "min_strength":      0.40,    # fires on lighter confirmation
        "momentum_needed":   2,       # gate 2 needs only 2/4
        "entry_needed":      1,       # gate 3 needs only 1/4
        "adx_min":           22,      # accepts weaker trends
    },
}

# Default — overwritten at startup by bot.py
ACTIVE_PROFILE = PROFILES["safe"]


def set_profile(mode: str):
    global ACTIVE_PROFILE
    mode = mode.lower()
    if mode not in PROFILES:
        raise ValueError(f"Unknown mode '{mode}'. Choose: safe | aggressive")
    ACTIVE_PROFILE = PROFILES[mode]
