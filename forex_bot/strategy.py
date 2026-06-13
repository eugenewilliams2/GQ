"""
Trading strategy engine — triple-confirmation system.

A trade is only opened when ALL THREE gates pass:

  Gate 1 — TREND   : ADX > 25, EMA structure aligned, DEMA direction matches
  Gate 2 — MOMENTUM: RSI in range, MACD aligned, Stochastic %K/%D aligned, CCI in zone
  Gate 3 — ENTRY   : Bollinger squeeze break, Keltner channel, candlestick pattern,
                     OBV rising (long) / falling (short), volume expanding

Signal values:
    1  = BUY
   -1  = SELL
    0  = NO SIGNAL
"""

import logging
from dataclasses import dataclass

import pandas as pd

from forex_bot import config, indicators

logger = logging.getLogger(__name__)

MIN_CANDLES = max(
    config.EMA_SLOW, config.BB_PERIOD, config.RSI_PERIOD, 50
) + 10   # warm-up buffer


@dataclass
class Signal:
    pair:        str
    direction:   int          # 1 buy / -1 sell / 0 none
    price:       float
    stop_loss:   float
    take_profit: float
    reason:      str
    strength:    float = 0.0  # 0–1 composite confidence


# ══════════════════════════════════════════════════════════════════════════════
# Gate 1 — TREND CONFIRMATION
# ══════════════════════════════════════════════════════════════════════════════

def _gate_trend(df: pd.DataFrame) -> int:
    """
    Returns 1 (bullish trend), -1 (bearish trend), or 0 (no trend / inconclusive).
    Requires:
      - ADX > 25 (trending, not ranging)
      - +DI > -DI for long; -DI > +DI for short
      - DEMA fast > DEMA slow for long; reversed for short
      - EMA fast > EMA slow for long; reversed for short
    """
    adx_val, di_pos, di_neg = indicators.adx(
        df["high"], df["low"], df["close"], config.ATR_PERIOD
    )
    if adx_val.iloc[-1] < 25:
        logger.debug("ADX too low (%.1f) — no trend", adx_val.iloc[-1])
        return 0

    fast_dema = indicators.dema(df["close"], config.EMA_FAST)
    slow_dema = indicators.dema(df["close"], config.EMA_SLOW)
    fast_ema  = indicators.ema(df["close"],  config.EMA_FAST)
    slow_ema  = indicators.ema(df["close"],  config.EMA_SLOW)

    bullish = (
        di_pos.iloc[-1]  > di_neg.iloc[-1]
        and fast_dema.iloc[-1] > slow_dema.iloc[-1]
        and fast_ema.iloc[-1]  > slow_ema.iloc[-1]
    )
    bearish = (
        di_neg.iloc[-1]  > di_pos.iloc[-1]
        and fast_dema.iloc[-1] < slow_dema.iloc[-1]
        and fast_ema.iloc[-1]  < slow_ema.iloc[-1]
    )

    if bullish:
        return 1
    if bearish:
        return -1
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# Gate 2 — MOMENTUM CONFIRMATION
# ══════════════════════════════════════════════════════════════════════════════

def _gate_momentum(df: pd.DataFrame, direction: int) -> tuple[bool, list[str]]:
    """
    Returns (passed, list_of_confirmations).
    Requires at least 3 of 4 momentum sub-checks.
    """
    passed = []

    # 2a. RSI — not overbought on buy, not oversold on sell
    rsi_val = indicators.rsi(df["close"], config.RSI_PERIOD).iloc[-1]
    if direction == 1 and 40 < rsi_val < config.RSI_OVERBOUGHT:
        passed.append(f"RSI {rsi_val:.0f} bullish")
    elif direction == -1 and config.RSI_OVERSOLD < rsi_val < 60:
        passed.append(f"RSI {rsi_val:.0f} bearish")

    # 2b. MACD histogram aligned and crossing
    _, _, hist = indicators.macd(
        df["close"], config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL
    )
    macd_aligned  = (direction == 1 and hist.iloc[-1] > 0) or \
                    (direction == -1 and hist.iloc[-1] < 0)
    macd_crossing = (direction == 1  and hist.iloc[-2] < 0 and hist.iloc[-1] > 0) or \
                    (direction == -1 and hist.iloc[-2] > 0 and hist.iloc[-1] < 0)
    if macd_aligned:
        passed.append("MACD aligned" + (" (crossing)" if macd_crossing else ""))

    # 2c. Stochastic %K/%D crossover in correct zone
    k, d = indicators.stochastic(df["high"], df["low"], df["close"])
    stoch_k, stoch_d = k.iloc[-1], d.iloc[-1]
    if direction == 1 and stoch_k < 80 and stoch_k > stoch_d and k.iloc[-2] <= d.iloc[-2]:
        passed.append(f"Stoch %K/{stoch_k:.0f} bullish cross")
    elif direction == -1 and stoch_k > 20 and stoch_k < stoch_d and k.iloc[-2] >= d.iloc[-2]:
        passed.append(f"Stoch %K/{stoch_k:.0f} bearish cross")

    # 2d. CCI alignment
    cci_val = indicators.cci(df["high"], df["low"], df["close"]).iloc[-1]
    if direction == 1  and 0 < cci_val < 200:
        passed.append(f"CCI {cci_val:.0f} bullish")
    elif direction == -1 and -200 < cci_val < 0:
        passed.append(f"CCI {cci_val:.0f} bearish")

    return len(passed) >= 3, passed


# ══════════════════════════════════════════════════════════════════════════════
# Gate 3 — ENTRY / PRICE-ACTION CONFIRMATION
# ══════════════════════════════════════════════════════════════════════════════

def _gate_entry(df: pd.DataFrame, direction: int) -> tuple[bool, list[str]]:
    """
    Returns (passed, list_of_confirmations).
    Requires at least 2 of 4 entry sub-checks.
    """
    passed = []

    # 3a. Bollinger Band — price near the band being tested
    upper, mid, lower = indicators.bollinger_bands(
        df["close"], config.BB_PERIOD, config.BB_STD
    )
    price = df["close"].iloc[-1]
    bb_width = (upper.iloc[-1] - lower.iloc[-1]) / mid.iloc[-1]
    if direction == 1  and price <= lower.iloc[-1] * 1.001:
        passed.append("BB lower touch")
    elif direction == -1 and price >= upper.iloc[-1] * 0.999:
        passed.append("BB upper touch")
    elif bb_width > 0.003:                          # breakout mode: wide band
        if direction == 1  and price > mid.iloc[-1]:
            passed.append("BB breakout long")
        elif direction == -1 and price < mid.iloc[-1]:
            passed.append("BB breakout short")

    # 3b. Keltner channel alignment
    kc_upper, kc_mid, kc_lower = indicators.keltner_channel(
        df["high"], df["low"], df["close"]
    )
    if direction == 1  and price > kc_mid.iloc[-1]:
        passed.append("Keltner bullish")
    elif direction == -1 and price < kc_mid.iloc[-1]:
        passed.append("Keltner bearish")

    # 3c. Candlestick pattern
    if direction == 1:
        if indicators.bullish_engulfing(df["open"], df["close"]).iloc[-1]:
            passed.append("Bullish engulfing")
        elif indicators.is_pin_bar(df["open"], df["high"], df["low"], df["close"], 1).iloc[-1]:
            passed.append("Bullish pin bar")
    else:
        if indicators.bearish_engulfing(df["open"], df["close"]).iloc[-1]:
            passed.append("Bearish engulfing")
        elif indicators.is_pin_bar(df["open"], df["high"], df["low"], df["close"], -1).iloc[-1]:
            passed.append("Bearish pin bar")

    # 3d. Volume — OBV direction + expanding volume
    obv_series = indicators.obv(df["close"], df["volume"])
    vol_osc    = indicators.volume_oscillator(df["volume"])
    obv_rising = obv_series.iloc[-1] > obv_series.iloc[-3]
    vol_expand = vol_osc.iloc[-1] > 0

    if direction == 1  and obv_rising and vol_expand:
        passed.append("OBV rising + vol expanding")
    elif direction == -1 and not obv_rising and vol_expand:
        passed.append("OBV falling + vol expanding")

    return len(passed) >= 2, passed


# ══════════════════════════════════════════════════════════════════════════════
# Data validation before ANY analysis
# ══════════════════════════════════════════════════════════════════════════════

def _validate_data(pair: str, df: pd.DataFrame) -> bool:
    """Hard reject bad data before running any indicator."""
    if df is None or len(df) < MIN_CANDLES:
        logger.debug("%s: insufficient candles (%s)", pair, len(df) if df is not None else 0)
        return False

    quality = indicators.data_quality_score(df)
    if quality < 1.0:
        logger.warning("%s: data quality score %.2f — skipping", pair, quality)
        return False

    # Reject zero-volume candles (stale / weekend data)
    zero_vol = (df["volume"] == 0).sum()
    if zero_vol > len(df) * 0.05:   # >5% zero-volume bars
        logger.warning("%s: %d zero-volume bars — skipping", pair, zero_vol)
        return False

    # Reject if spread (high-low) is degenerate
    avg_spread = (df["high"] - df["low"]).mean()
    if avg_spread < 1e-6:
        logger.warning("%s: degenerate spread — skipping", pair)
        return False

    return True


# ══════════════════════════════════════════════════════════════════════════════
# Composite signal generator
# ══════════════════════════════════════════════════════════════════════════════

def generate_signal(pair: str, df: pd.DataFrame) -> Signal | None:
    """
    Triple-gate confirmation.
    All three gates must pass; strength is computed from sub-check density.
    """
    if not _validate_data(pair, df):
        return None

    pip      = indicators.pip_value(pair)
    atr_val  = float(indicators.atr(df["high"], df["low"], df["close"],
                                    config.ATR_PERIOD).iloc[-1])
    price    = float(df["close"].iloc[-1])

    # ── Gate 1: trend ────────────────────────────────────────────────────────
    direction = _gate_trend(df)
    if direction == 0:
        return None

    # ── Gate 2: momentum ─────────────────────────────────────────────────────
    mom_ok, mom_reasons = _gate_momentum(df, direction)
    if not mom_ok:
        logger.debug("%s: momentum gate failed (%d/4)", pair, len(mom_reasons))
        return None

    # ── Gate 3: entry / price action ─────────────────────────────────────────
    entry_ok, entry_reasons = _gate_entry(df, direction)
    if not entry_ok:
        logger.debug("%s: entry gate failed (%d/4)", pair, len(entry_reasons))
        return None

    # ── All gates passed — build signal ──────────────────────────────────────
    all_reasons = (
        [f"{'BUY' if direction==1 else 'SELL'} trend confirmed"]
        + mom_reasons
        + entry_reasons
    )
    strength = round((len(mom_reasons)/4 + len(entry_reasons)/4) / 2, 2)

    sl_dist = max(config.STOP_LOSS_PIPS   * pip, atr_val * 1.5)
    tp_dist = max(config.TAKE_PROFIT_PIPS * pip, atr_val * 3.0)

    if direction == 1:
        stop_loss, take_profit = price - sl_dist, price + tp_dist
    else:
        stop_loss, take_profit = price + sl_dist, price - tp_dist

    logger.info(
        "SIGNAL %s %s @ %.5f  strength=%.0f%%  [%s]",
        "BUY" if direction == 1 else "SELL", pair, price,
        strength * 100, " | ".join(all_reasons),
    )

    return Signal(
        pair        = pair,
        direction   = direction,
        price       = price,
        stop_loss   = stop_loss,
        take_profit = take_profit,
        reason      = " | ".join(all_reasons),
        strength    = strength,
    )


def scan_pairs(data: dict[str, pd.DataFrame]) -> list[Signal]:
    signals = []
    for pair, df in data.items():
        sig = generate_signal(pair, df)
        if sig:
            signals.append(sig)
    signals.sort(key=lambda s: s.strength, reverse=True)
    return signals
