"""
ICT / Smart Money Concepts strategy engine — 4-gate system.

Research sources:
  - ICT (Inner Circle Trader): order blocks, FVGs, liquidity sweeps, BOS/CHoCH
  - Paul Tudor Jones: 5:1 R:R target, cut losers immediately
  - Stanley Druckenmiller: pyramid winners, concentrate in high-conviction setups
  - Session research: killzone peak = 14:00-16:00 UTC (adversarially verified)
  - DXY: confluence only (leading-indicator claim refuted — EUR = 57.6% of DXY)

Four gates — ALL must pass before a signal is generated:

  Gate 1 — STRUCTURE   (4H HTF) : BOS/CHoCH confirms trend bias
  Gate 2 — POINT OF INTEREST (4H): price inside unmitigated order block or FVG
  Gate 3 — TIMING + SWEEP (1H)  : active killzone + liquidity sweep detected
  Gate 4 — MOMENTUM    (1H)     : RSI/MACD/ADX confluence aligned
"""

from __future__ import annotations
import logging
from dataclasses import dataclass

import pandas as pd

from forex_bot import config, indicators as ind

logger = logging.getLogger(__name__)

MIN_LTF = max(config.EMA_SLOW, config.BB_PERIOD, config.RSI_PERIOD, 60) + 10
MIN_HTF = 60   # ~10 days of 4H data for reliable swing-point detection


@dataclass
class Signal:
    pair:        str
    direction:   int           # 1 = buy, -1 = sell
    price:       float
    stop_loss:   float
    take_profit: float
    reason:      str
    strength:    float = 0.0   # 0–1 composite confidence
    rr_ratio:    float = 0.0
    killzone:    str   = ""


# ══════════════════════════════════════════════════════════════════════════════
# Gate 1 — Market Structure (4H HTF)
# ══════════════════════════════════════════════════════════════════════════════

def _gate_structure(df_4h: pd.DataFrame) -> int:
    """
    BOS/CHoCH on the 4H chart.
    Requires 3 consistent swing highs+lows to confirm a structure.
    Returns 1 (bullish), -1 (bearish), 0 (unclear).
    """
    bias = ind.market_structure_bias(df_4h, config.SWING_LOOKBACK)

    # ADX confluence — research showed ADX is lagging but useful as a filter
    adx_val, di_pos, di_neg = ind.adx(df_4h["high"], df_4h["low"], df_4h["close"],
                                       config.ATR_PERIOD)
    adx_ok = adx_val.iloc[-1] >= config.ACTIVE_PROFILE["adx_min"]

    if bias == 1  and adx_ok and di_pos.iloc[-1] > di_neg.iloc[-1]: return 1
    if bias == -1 and adx_ok and di_neg.iloc[-1] > di_pos.iloc[-1]: return -1
    return 0


# ══════════════════════════════════════════════════════════════════════════════
# Gate 2 — Point of Interest (4H HTF)
# ══════════════════════════════════════════════════════════════════════════════

def _gate_poi(df_4h: pd.DataFrame, df_1h: pd.DataFrame,
              direction: int) -> tuple[bool, dict | None, str]:
    """
    Price must be inside an unmitigated 4H order block OR a 4H fair value gap.
    Uses the 1H close as the 'current price' for the check.
    """
    price = float(df_1h["close"].iloc[-1])

    obs  = ind.find_order_blocks(df_4h, direction)
    fvgs = ind.find_fair_value_gaps(df_4h, direction)

    in_ob,  ob_zone  = ind.price_in_zone(price, obs)
    in_fvg, fvg_zone = ind.price_in_zone(price, fvgs)

    if in_ob:
        return True, ob_zone, "4H Order Block"
    if in_fvg:
        return True, fvg_zone, "4H FVG"
    return False, None, ""


# ══════════════════════════════════════════════════════════════════════════════
# Gate 3 — Timing & Liquidity Sweep (1H LTF)
# ══════════════════════════════════════════════════════════════════════════════

def _gate_timing(df_1h: pd.DataFrame, direction: int) -> tuple[bool, list[str]]:
    """
    Two sub-checks:
    a) Active ICT killzone (Asian/London/NY/Peak)
    b) Liquidity sweep on 1H — price wicked through swing, closed back
       (Research: sweep alone has only ~65% win rate; killzone confluence raises it)
    """
    profile = config.ACTIVE_PROFILE
    passed  = []

    kz_ok, kz_name = ind.in_killzone()
    if kz_ok:
        passed.append(f"Killzone: {kz_name}")
    elif profile["require_killzone"]:
        return False, []

    sweep = ind.detect_liquidity_sweep(df_1h, direction)
    if sweep:
        passed.append("Liquidity sweep")
    elif profile["require_sweep"]:
        return False, []

    return bool(passed), passed


# ══════════════════════════════════════════════════════════════════════════════
# Gate 4 — Momentum Confirmation (1H LTF)
# ══════════════════════════════════════════════════════════════════════════════

def _gate_momentum(df_1h: pd.DataFrame, direction: int) -> tuple[bool, list[str]]:
    """
    RSI, MACD histogram, Stochastic cross, candlestick pattern.
    Threshold controlled by profile (safe: 3/4, aggressive: 2/4).
    """
    needed = config.ACTIVE_PROFILE["momentum_needed"]
    passed = []

    # RSI — not in extreme opposing zone
    rsi_v = ind.rsi(df_1h["close"], config.RSI_PERIOD).iloc[-1]
    if direction == 1  and 35 < rsi_v < config.RSI_OVERBOUGHT:
        passed.append(f"RSI {rsi_v:.0f}")
    elif direction == -1 and config.RSI_OVERSOLD < rsi_v < 65:
        passed.append(f"RSI {rsi_v:.0f}")

    # MACD histogram direction
    _, _, hist = ind.macd(df_1h["close"], config.MACD_FAST,
                          config.MACD_SLOW, config.MACD_SIGNAL)
    macd_ok = (direction == 1 and hist.iloc[-1] > 0) or \
              (direction == -1 and hist.iloc[-1] < 0)
    if macd_ok:
        cross = ((direction == 1  and hist.iloc[-2] < 0) or
                 (direction == -1 and hist.iloc[-2] > 0))
        passed.append("MACD" + (" cross↑" if cross and direction==1
                                 else " cross↓" if cross else ""))

    # Stochastic cross in non-extreme zone
    k, d = ind.stochastic(df_1h["high"], df_1h["low"], df_1h["close"])
    kv = k.iloc[-1]
    if direction == 1  and kv < 80 and k.iloc[-1] > d.iloc[-1] and k.iloc[-2] <= d.iloc[-2]:
        passed.append(f"Stoch {kv:.0f} ↑")
    elif direction == -1 and kv > 20 and k.iloc[-1] < d.iloc[-1] and k.iloc[-2] >= d.iloc[-2]:
        passed.append(f"Stoch {kv:.0f} ↓")

    # Candlestick confirmation at the POI
    if direction == 1:
        if ind.bullish_engulfing(df_1h["open"], df_1h["close"]).iloc[-1]:
            passed.append("Engulfing ↑")
        elif ind.is_pin_bar(df_1h["open"], df_1h["high"],
                            df_1h["low"], df_1h["close"], 1).iloc[-1]:
            passed.append("Pin bar ↑")
    else:
        if ind.bearish_engulfing(df_1h["open"], df_1h["close"]).iloc[-1]:
            passed.append("Engulfing ↓")
        elif ind.is_pin_bar(df_1h["open"], df_1h["high"],
                            df_1h["low"], df_1h["close"], -1).iloc[-1]:
            passed.append("Pin bar ↓")

    return len(passed) >= needed, passed


# ══════════════════════════════════════════════════════════════════════════════
# Data validation
# ══════════════════════════════════════════════════════════════════════════════

def _validate(pair: str, df_1h: pd.DataFrame, df_4h: pd.DataFrame) -> bool:
    if df_1h is None or len(df_1h) < MIN_LTF:
        return False
    if df_4h is None or len(df_4h) < MIN_HTF:
        logger.debug("%s: insufficient 4H data (%s candles)", pair,
                     len(df_4h) if df_4h is not None else 0)
        return False
    if ind.data_quality_score(df_1h) < 1.0 or ind.data_quality_score(df_4h) < 1.0:
        logger.warning("%s: data quality check failed", pair)
        return False
    zero_vol = (df_1h["volume"] == 0).sum()
    if zero_vol > len(df_1h) * 0.05:
        return False
    return True


# ══════════════════════════════════════════════════════════════════════════════
# Composite signal — all 4 gates must pass
# ══════════════════════════════════════════════════════════════════════════════

def generate_signal(pair: str,
                    df_1h: pd.DataFrame,
                    df_4h: pd.DataFrame) -> Signal | None:
    """
    ICT 4-gate signal.  All gates are mandatory.
    R:R is validated against the profile's minimum (PTJ-inspired: 3:1 safe / 2:1 aggressive).
    """
    if not _validate(pair, df_1h, df_4h):
        return None

    profile = config.ACTIVE_PROFILE
    pip     = ind.pip_value(pair)
    price   = float(df_1h["close"].iloc[-1])
    atr_val = float(ind.atr(df_1h["high"], df_1h["low"], df_1h["close"],
                             config.ATR_PERIOD).iloc[-1])

    # ── Gate 1: 4H market structure ──────────────────────────────────────────
    direction = _gate_structure(df_4h)
    if direction == 0:
        return None

    # ── Gate 2: price at 4H point of interest ────────────────────────────────
    poi_ok, poi_zone, poi_label = _gate_poi(df_4h, df_1h, direction)
    if not poi_ok:
        return None

    # ── Gate 3: killzone + liquidity sweep ───────────────────────────────────
    timing_ok, timing_reasons = _gate_timing(df_1h, direction)
    if not timing_ok:
        return None

    # ── Gate 4: momentum ─────────────────────────────────────────────────────
    mom_ok, mom_reasons = _gate_momentum(df_1h, direction)
    if not mom_ok:
        return None

    # ── SL: just beyond the POI zone ─────────────────────────────────────────
    buf = atr_val * 0.3   # small buffer beyond zone
    if direction == 1:
        sl_price = poi_zone.get("low", poi_zone.get("bottom")) - buf
        sl_price = min(sl_price, price - profile["stop_loss_pips"] * pip)
    else:
        sl_price = poi_zone.get("high", poi_zone.get("top")) + buf
        sl_price = max(sl_price, price + profile["stop_loss_pips"] * pip)

    sl_dist = abs(price - sl_price)

    # ── TP: next structural target on 4H ─────────────────────────────────────
    tp_price = ind.next_structure_target(df_4h, direction, config.SWING_LOOKBACK)
    if tp_price is None:
        tp_dist  = profile["take_profit_pips"] * pip
        tp_price = price + tp_dist if direction == 1 else price - tp_dist

    tp_dist  = abs(tp_price - price)
    rr_ratio = tp_dist / sl_dist if sl_dist > 0 else 0

    # ── R:R gate (PTJ rule: minimum 3:1 safe / 2:1 aggressive) ──────────────
    if rr_ratio < profile["min_rr"]:
        logger.debug("%s: R:R %.2f below minimum %.1f", pair, rr_ratio, profile["min_rr"])
        return None

    # ── Strength score ────────────────────────────────────────────────────────
    strength = round(min(len(timing_reasons) / 2 + len(mom_reasons) / 4, 1.0), 2)
    if strength < profile["min_strength"]:
        return None

    all_reasons = (
        [f"{'BUY' if direction==1 else 'SELL'} structure (4H BOS)"]
        + [poi_label]
        + timing_reasons
        + mom_reasons
    )
    _, kz_name = ind.in_killzone()

    logger.info(
        "SIGNAL %s %s @ %.5f  SL=%.5f  TP=%.5f  R:R=%.1f  strength=%.0f%%  [%s]",
        "BUY" if direction == 1 else "SELL", pair, price,
        sl_price, tp_price, rr_ratio, strength * 100,
        " | ".join(all_reasons),
    )

    return Signal(
        pair        = pair,
        direction   = direction,
        price       = price,
        stop_loss   = sl_price,
        take_profit = tp_price,
        reason      = " | ".join(all_reasons),
        strength    = strength,
        rr_ratio    = round(rr_ratio, 2),
        killzone    = kz_name,
    )


def scan_pairs(ltf_data: dict[str, pd.DataFrame],
               htf_data: dict[str, pd.DataFrame]) -> list[Signal]:
    signals = []
    for pair, df_1h in ltf_data.items():
        df_4h = htf_data.get(pair)
        sig   = generate_signal(pair, df_1h, df_4h)
        if sig:
            signals.append(sig)
    return sorted(signals, key=lambda s: (s.rr_ratio, s.strength), reverse=True)
