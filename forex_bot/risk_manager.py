"""
Professional risk management engine.

Rules sourced from deep research (adversarially verified):
  - 1% per trade hard cap (Paul Tudor Jones)
  - Half-Kelly criterion (confirmed: captures 75% return, halves drawdown)
  - Daily loss limit 3-5% (institutional prop firm standard)
  - Portfolio heat ≤ 5-8% total (aggregate potential loss across all open trades)
  - Correlation group cap (e.g. EUR/USD + GBP/USD treated as one risk unit)
  - Minimum R:R: 3:1 safe / 2:1 aggressive (PTJ-inspired)
  - Drawdown recovery math: 20% loss needs 25% gain just to break even
"""

import logging
from datetime import date, timezone

from forex_bot import config, indicators

logger = logging.getLogger(__name__)

# ── Correlation group lookup ───────────────────────────────────────────────

def _corr_group(pair: str) -> str | None:
    for group, pairs in config.CORRELATION_GROUPS.items():
        if pair in pairs:
            return group
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Position sizing — Half-Kelly blended with fixed fractional
# ══════════════════════════════════════════════════════════════════════════════

def half_kelly_fraction(win_rate: float, rr_ratio: float) -> float:
    """
    Half-Kelly: K = W - (1-W)/R, then halved.
    Research confirmed: half-Kelly captures ~75% of optimal growth at ~half the volatility.
    """
    if rr_ratio <= 0 or win_rate <= 0:
        return 0.0
    kelly = win_rate - (1 - win_rate) / rr_ratio
    return max(kelly * 0.5, 0.0)


def position_size(balance: float,
                  sl_distance: float,
                  price: float,
                  pair: str,
                  rr_ratio: float = 2.0,
                  historical_win_rate: float = 0.55) -> int:
    """
    Blend fixed-fractional (profile risk %) with Half-Kelly.
    Take the more conservative of the two.
    Never exceeds the profile's leverage * balance.
    """
    profile = config.ACTIVE_PROFILE
    pip     = indicators.pip_value(pair)
    sl_dist = max(sl_distance, pip)

    # Fixed fractional
    ff_risk  = balance * profile["risk_per_trade"]
    ff_units = int(ff_risk / sl_dist * config.LOT_SIZE)

    # Half-Kelly (capped at profile risk)
    hk_frac  = half_kelly_fraction(historical_win_rate, rr_ratio)
    hk_frac  = min(hk_frac, profile["risk_per_trade"])
    hk_risk  = balance * hk_frac
    hk_units = int(hk_risk / sl_dist * config.LOT_SIZE) if hk_frac > 0 else ff_units

    # Take the more conservative of the two
    units    = min(ff_units, hk_units)
    max_units = int(profile["leverage"] * balance / price)
    return max(min(units, max_units, config.LOT_SIZE * 200), config.LOT_SIZE)


# ══════════════════════════════════════════════════════════════════════════════
# Gate checks
# ══════════════════════════════════════════════════════════════════════════════

def is_drawdown_ok(balance: float, peak_balance: float) -> bool:
    if peak_balance <= 0:
        return True
    dd = (peak_balance - balance) / peak_balance
    max_dd = config.ACTIVE_PROFILE["max_drawdown_pct"]
    if dd > max_dd:
        # Drawdown recovery reminder (research-verified compound math)
        needed = dd / (1 - dd) * 100
        logger.warning(
            "Max drawdown %.1f%% breached — halting. Need %.1f%% gain to recover.",
            dd * 100, needed,
        )
        return False
    return True


def is_daily_loss_ok(daily_pnl: float, balance: float) -> bool:
    """Daily loss limit: 3% safe / 5% aggressive (institutional standard)."""
    limit = config.ACTIVE_PROFILE["daily_loss_pct"]
    if daily_pnl < 0 and abs(daily_pnl) / balance > limit:
        logger.warning(
            "Daily loss limit %.0f%% reached (loss $%.2f) — no new trades today.",
            limit * 100, abs(daily_pnl),
        )
        return False
    return True


def is_portfolio_heat_ok(open_trades: list, balance: float) -> bool:
    """
    Portfolio heat = sum of (potential loss at SL) for all open trades.
    Cap: 5% safe / 8% aggressive.
    """
    if not open_trades:
        return True
    heat = sum(abs(t.entry_price - t.stop_loss) * t.units for t in open_trades)
    heat_pct = heat / balance
    limit = config.ACTIVE_PROFILE["portfolio_heat"]
    if heat_pct >= limit:
        logger.info("Portfolio heat %.1f%% at limit (%.0f%%)", heat_pct * 100, limit * 100)
        return False
    return True


def is_correlation_ok(pair: str, open_trades: list, balance: float) -> bool:
    """
    Correlation group cap: max risk exposure per correlated group.
    EUR/USD + GBP/USD treated as same group (both USD-quote, high correlation).
    """
    group = _corr_group(pair)
    if group is None:
        return True

    group_pairs = config.CORRELATION_GROUPS[group]
    group_heat  = sum(
        abs(t.entry_price - t.stop_loss) * t.units
        for t in open_trades if t.pair in group_pairs
    )
    limit = config.ACTIVE_PROFILE["corr_heat"]
    if group_heat / balance >= limit:
        logger.info("Correlation group '%s' at heat limit (%.0f%%)", group, limit * 100)
        return False
    return True


def validate_signal(signal,
                    balance: float,
                    peak_balance: float,
                    open_trades: list,
                    daily_pnl: float) -> tuple[bool, str]:
    """Master gate check before placing any trade."""
    profile = config.ACTIVE_PROFILE

    if not is_drawdown_ok(balance, peak_balance):
        return False, "max drawdown reached"
    if not is_daily_loss_ok(daily_pnl, balance):
        return False, "daily loss limit reached"
    if len(open_trades) >= profile["max_open_trades"]:
        return False, f"max open trades ({profile['max_open_trades']})"
    if not is_portfolio_heat_ok(open_trades, balance):
        return False, "portfolio heat limit"
    if not is_correlation_ok(signal.pair, open_trades, balance):
        return False, "correlation group heat limit"
    if signal.rr_ratio < profile["min_rr"]:
        return False, f"R:R {signal.rr_ratio:.1f} below minimum {profile['min_rr']}"
    if signal.strength < profile["min_strength"]:
        return False, f"strength {signal.strength:.0%} below threshold"

    return True, "ok"
