"""
Central configuration for the GQ Forex Trading Bot.
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

# ── Crypto universe (real volume on Yahoo, trades 24/7) ─────────────────────
CRYPTO_PAIRS = [
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
    "BNB-USD",
    "XRP-USD",
    "ADA-USD",
    "DOGE-USD",
]

# Trading days per year by asset class — crypto trades 24/7 (365), FX 24/5 (252).
ASSET_DAYS = {"forex": 252, "crypto": 365}


def pairs_for(asset: str) -> list[str]:
    return CRYPTO_PAIRS if asset == "crypto" else PAIRS


# Correlation groups — positions in same group share risk budget
CORRELATION_GROUPS = {
    "eur_cluster":   ["EURUSD=X", "GBPUSD=X"],
    "asia_pacific":  ["USDJPY=X", "AUDUSD=X", "NZDUSD=X"],
    "americas":      ["USDCAD=X", "USDCHF=X"],
}

# USD-positive pairs (USD is quote) — rise when dollar weakens
USD_POSITIVE = {"EURUSD=X", "GBPUSD=X", "AUDUSD=X", "NZDUSD=X"}
# USD-negative pairs (USD is base) — rise when dollar strengthens
USD_NEGATIVE = {"USDJPY=X", "USDCHF=X", "USDCAD=X"}

# ── Paper-trading account ──────────────────────────────────────────────────
STARTING_BALANCE = 10_000.0
LOT_SIZE         = 1_000       # 1 micro-lot

# ── Indicator parameters ───────────────────────────────────────────────────
EMA_FAST       = 9
EMA_SLOW       = 21
RSI_PERIOD     = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD   = 30
MACD_FAST      = 12
MACD_SLOW      = 26
MACD_SIGNAL    = 9
BB_PERIOD      = 20
BB_STD         = 2.0
ATR_PERIOD     = 14
SWING_LOOKBACK = 5   # candles either side for swing point detection

# ── ICT Killzones (UTC hours) ──────────────────────────────────────────────
# Research-verified peak windows (adversarially checked):
#   Asian killzone : 23:00-02:00 UTC  (mark range, sweep incoming)
#   London killzone: 07:00-10:00 UTC  (institutional breakouts)
#   NY killzone    : 12:00-15:00 UTC  (sweeps + reversals)
#   Peak overlap   : 14:00-16:00 UTC  (highest volume, tightest spreads)
KILLZONES = {
    "Asian":   (23, 2),    # wraps midnight
    "London":  (7,  10),
    "NY":      (12, 15),
}

# ── Data / scheduling ─────────────────────────────────────────────────────
# NOTE: Yahoo Finance has no native 4h interval and only serves 1h data for
# the trailing ~730 days. We fetch 1h and resample to 4h locally.
CANDLE_INTERVAL_LTF = "1h"    # lower timeframe — entry timing (fetched from Yahoo)
CANDLE_INTERVAL_HTF = "4h"    # higher timeframe — bias / structure (resampled from 1h)
CANDLE_LOOKBACK_LTF = "60d"
CANDLE_LOOKBACK_HTF = "180d"  # 6 months of 1h → plenty of 4H structure
SCAN_INTERVAL_S     = 60

# ── Backtesting ────────────────────────────────────────────────────────────
# Start is auto-clamped to Yahoo's 730-day 1h limit if set earlier.
BACKTEST_START    = "2025-01-01"
BACKTEST_END      = "2026-06-01"
BACKTEST_INTERVAL = "1h"

# ── Logging ────────────────────────────────────────────────────────────────
LOG_FILE = "forex_bot.log"

# ══════════════════════════════════════════════════════════════════════════
# RISK PROFILES
# Research sources:
#   - Paul Tudor Jones: 5:1 R:R minimum, 1% risk per trade
#   - Half-Kelly: confirmed by professional consensus (75% of optimal return)
#   - Daily loss limit: 3-5% (institutional prop firm standard)
#   - Portfolio heat: 5-6% max aggregate (per professional risk frameworks)
# ══════════════════════════════════════════════════════════════════════════

PROFILES = {
    "safe": {
        "label":             "SAFE  (low risk / steady returns)",
        # Position sizing
        "risk_per_trade":    0.005,   # 0.5% — conservative fixed fractional
        "leverage":          10,
        # Trade limits
        "max_open_trades":   3,
        "portfolio_heat":    0.05,    # 5% max aggregate potential loss
        "corr_heat":         0.02,    # 2% max per correlation group
        "daily_loss_pct":    0.03,    # halt if down 3% in one day
        # SL/TP
        "stop_loss_pips":    15,
        "take_profit_pips":  75,      # PTJ-inspired: 5:1 R:R
        "min_rr":            3.0,     # minimum acceptable R:R ratio
        # Signal filters
        "max_drawdown_pct":  0.10,
        "min_strength":      0.65,
        "adx_min":           25,      # ADX as confirmation (verified: lagging, needs confluence)
        "momentum_needed":   3,       # gates need 3/4 momentum checks
        "entry_needed":      2,       # gate needs 2/4 entry checks
        "require_killzone":  True,    # only trade during institutional windows
        "require_sweep":     True,    # require liquidity sweep confirmation
    },
    "aggressive": {
        "label":             "AGGRESSIVE  (high risk / high reward)",
        "risk_per_trade":    0.025,   # 2.5%
        "leverage":          50,
        "max_open_trades":   7,
        "portfolio_heat":    0.08,    # 8% max aggregate heat
        "corr_heat":         0.04,    # 4% per correlation group
        "daily_loss_pct":    0.05,    # halt at 5% daily loss
        "stop_loss_pips":    25,
        "take_profit_pips":  75,      # 3:1 R:R
        "min_rr":            2.0,     # more permissive
        "max_drawdown_pct":  0.25,
        "min_strength":      0.40,
        "adx_min":           22,
        "momentum_needed":   2,
        "entry_needed":      1,
        "require_killzone":  True,    # still require killzone even in aggressive mode
        "require_sweep":     False,   # sweep is preferred but not mandatory
    },
}

ACTIVE_PROFILE = PROFILES["safe"]


def set_profile(mode: str):
    global ACTIVE_PROFILE
    mode = mode.lower()
    if mode not in PROFILES:
        raise ValueError(f"Unknown mode '{mode}'. Choose: safe | aggressive")
    ACTIVE_PROFILE = PROFILES[mode]
    return ACTIVE_PROFILE
