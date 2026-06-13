"""
Risk management — all thresholds pulled from the active profile.
"""

import logging

from forex_bot import config, indicators

logger = logging.getLogger(__name__)


def position_size(balance: float, stop_loss_distance: float,
                  price: float, pair: str) -> int:
    profile  = config.ACTIVE_PROFILE
    pip      = indicators.pip_value(pair)
    risk_amt = balance * profile["risk_per_trade"]
    sl_dist  = max(stop_loss_distance, pip)
    units    = int(risk_amt / sl_dist * config.LOT_SIZE)
    max_units = int(profile["leverage"] * balance / price)
    return max(min(units, max_units, config.LOT_SIZE * 200), config.LOT_SIZE)


def is_drawdown_ok(balance: float, peak_balance: float) -> bool:
    if peak_balance <= 0:
        return True
    dd = (peak_balance - balance) / peak_balance
    if dd > config.ACTIVE_PROFILE["max_drawdown_pct"]:
        logger.warning(
            "Max drawdown breached (%.1f%% > %.0f%%) — trading halted",
            dd * 100, config.ACTIVE_PROFILE["max_drawdown_pct"] * 100,
        )
        return False
    return True


def validate_signal(signal, balance: float, peak_balance: float,
                    open_trades: int) -> tuple[bool, str]:
    profile = config.ACTIVE_PROFILE
    if not is_drawdown_ok(balance, peak_balance):
        return False, "max drawdown reached"
    if open_trades >= profile["max_open_trades"]:
        return False, f"max open trades ({profile['max_open_trades']}) reached"
    if signal.strength < profile["min_strength"]:
        return False, f"strength {signal.strength:.0%} below threshold"
    return True, "ok"
