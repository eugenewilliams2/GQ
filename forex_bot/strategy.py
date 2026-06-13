"""
Triple-gate signal engine — thresholds driven by the active risk profile.

Gate 1 — TREND    : ADX, DEMA+EMA structure, DI alignment
Gate 2 — MOMENTUM : RSI, MACD, Stochastic, CCI
Gate 3 — ENTRY    : Bollinger Band, Keltner, candlestick, OBV+volume
"""

import logging
from dataclasses import dataclass

import pandas as pd

from forex_bot import config, indicators

logger = logging.getLogger(__name__)

MIN_CANDLES = max(
    config.EMA_SLOW, config.BB_PERIOD, config.RSI_PERIOD, 50
) + 10


@dataclass
class Signal:
    pair:        str
    direction:   int
    price:       float
    stop_loss:   float
    take_profit: float
    reason:      str
    strength:    float = 0.0


# ── Gate 1: Trend ─────────────────────────────────────────────────────────

def _gate_trend(df: pd.DataFrame) -> int:
    profile  = config.ACTIVE_PROFILE
    adx_val, di_pos, di_neg = indicators.adx(
        df["high"], df["low"], df["close"], config.ATR_PERIOD
    )
    if adx_val.iloc[-1] < profile["adx_min"]:
        return 0

    fast_dema = indicators.dema(df["close"], config.EMA_FAST)
    slow_dema = indicators.dema(df["close"], config.EMA_SLOW)
    fast_ema  = indicators.ema(df["close"],  config.EMA_FAST)
    slow_ema  = indicators.ema(df["close"],  config.EMA_SLOW)

    bullish = (
        di_pos.iloc[-1]      > di_neg.iloc[-1]
        and fast_dema.iloc[-1] > slow_dema.iloc[-1]
        and fast_ema.iloc[-1]  > slow_ema.iloc[-1]
    )
    bearish = (
        di_neg.iloc[-1]      > di_pos.iloc[-1]
        and fast_dema.iloc[-1] < slow_dema.iloc[-1]
        and fast_ema.iloc[-1]  < slow_ema.iloc[-1]
    )
    if bullish: return 1
    if bearish: return -1
    return 0


# ── Gate 2: Momentum ──────────────────────────────────────────────────────

def _gate_momentum(df: pd.DataFrame, direction: int) -> tuple[bool, list[str]]:
    needed = config.ACTIVE_PROFILE["momentum_needed"]
    passed = []

    rsi_val = indicators.rsi(df["close"], config.RSI_PERIOD).iloc[-1]
    if direction == 1  and 40 < rsi_val < config.RSI_OVERBOUGHT:
        passed.append(f"RSI {rsi_val:.0f}")
    elif direction == -1 and config.RSI_OVERSOLD < rsi_val < 60:
        passed.append(f"RSI {rsi_val:.0f}")

    _, _, hist = indicators.macd(
        df["close"], config.MACD_FAST, config.MACD_SLOW, config.MACD_SIGNAL
    )
    if (direction == 1 and hist.iloc[-1] > 0) or (direction == -1 and hist.iloc[-1] < 0):
        label = "MACD" + (" cross" if (
            (direction == 1  and hist.iloc[-2] < 0)
            or (direction == -1 and hist.iloc[-2] > 0)
        ) else "")
        passed.append(label)

    k, d = indicators.stochastic(df["high"], df["low"], df["close"])
    if direction == 1  and k.iloc[-1] < 80 and k.iloc[-1] > d.iloc[-1] and k.iloc[-2] <= d.iloc[-2]:
        passed.append(f"Stoch cross {k.iloc[-1]:.0f}")
    elif direction == -1 and k.iloc[-1] > 20 and k.iloc[-1] < d.iloc[-1] and k.iloc[-2] >= d.iloc[-2]:
        passed.append(f"Stoch cross {k.iloc[-1]:.0f}")

    cci_val = indicators.cci(df["high"], df["low"], df["close"]).iloc[-1]
    if direction == 1  and 0 < cci_val < 200:
        passed.append(f"CCI {cci_val:.0f}")
    elif direction == -1 and -200 < cci_val < 0:
        passed.append(f"CCI {cci_val:.0f}")

    return len(passed) >= needed, passed


# ── Gate 3: Entry / price action ──────────────────────────────────────────

def _gate_entry(df: pd.DataFrame, direction: int) -> tuple[bool, list[str]]:
    needed = config.ACTIVE_PROFILE["entry_needed"]
    passed = []

    upper, mid, lower = indicators.bollinger_bands(
        df["close"], config.BB_PERIOD, config.BB_STD
    )
    price    = df["close"].iloc[-1]
    bb_width = (upper.iloc[-1] - lower.iloc[-1]) / mid.iloc[-1]
    if direction == 1  and price <= lower.iloc[-1] * 1.001:
        passed.append("BB lower")
    elif direction == -1 and price >= upper.iloc[-1] * 0.999:
        passed.append("BB upper")
    elif bb_width > 0.003:
        if direction == 1  and price > mid.iloc[-1]: passed.append("BB breakout ↑")
        elif direction == -1 and price < mid.iloc[-1]: passed.append("BB breakout ↓")

    kc_upper, kc_mid, kc_lower = indicators.keltner_channel(
        df["high"], df["low"], df["close"]
    )
    if direction == 1  and price > kc_mid.iloc[-1]: passed.append("Keltner ↑")
    elif direction == -1 and price < kc_mid.iloc[-1]: passed.append("Keltner ↓")

    if direction == 1:
        if indicators.bullish_engulfing(df["open"], df["close"]).iloc[-1]:
            passed.append("Engulfing ↑")
        elif indicators.is_pin_bar(df["open"], df["high"], df["low"], df["close"], 1).iloc[-1]:
            passed.append("Pin bar ↑")
    else:
        if indicators.bearish_engulfing(df["open"], df["close"]).iloc[-1]:
            passed.append("Engulfing ↓")
        elif indicators.is_pin_bar(df["open"], df["high"], df["low"], df["close"], -1).iloc[-1]:
            passed.append("Pin bar ↓")

    obv_series = indicators.obv(df["close"], df["volume"])
    vol_osc    = indicators.volume_oscillator(df["volume"])
    obv_up     = obv_series.iloc[-1] > obv_series.iloc[-3]
    vol_expand = vol_osc.iloc[-1] > 0
    if direction == 1  and obv_up    and vol_expand: passed.append("OBV ↑ vol+")
    elif direction == -1 and not obv_up and vol_expand: passed.append("OBV ↓ vol+")

    return len(passed) >= needed, passed


# ── Data validation ───────────────────────────────────────────────────────

def _validate_data(pair: str, df: pd.DataFrame) -> bool:
    if df is None or len(df) < MIN_CANDLES:
        return False
    if indicators.data_quality_score(df) < 1.0:
        logger.warning("%s: data quality check failed — skipped", pair)
        return False
    zero_vol = (df["volume"] == 0).sum()
    if zero_vol > len(df) * 0.05:
        logger.warning("%s: >5%% zero-volume bars — skipped", pair)
        return False
    if (df["high"] - df["low"]).mean() < 1e-6:
        return False
    return True


# ── Composite signal ──────────────────────────────────────────────────────

def generate_signal(pair: str, df: pd.DataFrame) -> Signal | None:
    if not _validate_data(pair, df):
        return None

    profile  = config.ACTIVE_PROFILE
    pip      = indicators.pip_value(pair)
    atr_val  = float(indicators.atr(df["high"], df["low"], df["close"],
                                    config.ATR_PERIOD).iloc[-1])
    price    = float(df["close"].iloc[-1])

    direction = _gate_trend(df)
    if direction == 0:
        return None

    mom_ok, mom_reasons = _gate_momentum(df, direction)
    if not mom_ok:
        return None

    entry_ok, entry_reasons = _gate_entry(df, direction)
    if not entry_ok:
        return None

    all_reasons = (
        [f"{'BUY' if direction==1 else 'SELL'} trend (ADX confirmed)"]
        + mom_reasons + entry_reasons
    )
    strength = round((len(mom_reasons) / 4 + len(entry_reasons) / 4) / 2, 2)

    if strength < profile["min_strength"]:
        logger.debug("%s: strength %.0f%% below threshold — skipped", pair, strength * 100)
        return None

    sl_dist = max(profile["stop_loss_pips"]   * pip, atr_val * 1.5)
    tp_dist = max(profile["take_profit_pips"] * pip, atr_val * 3.0)

    stop_loss   = price - sl_dist if direction == 1 else price + sl_dist
    take_profit = price + tp_dist if direction == 1 else price - tp_dist

    return Signal(
        pair=pair, direction=direction, price=price,
        stop_loss=stop_loss, take_profit=take_profit,
        reason=" | ".join(all_reasons), strength=strength,
    )


def scan_pairs(data: dict[str, pd.DataFrame]) -> list[Signal]:
    signals = [s for pair, df in data.items()
               if (s := generate_signal(pair, df)) is not None]
    return sorted(signals, key=lambda s: s.strength, reverse=True)
