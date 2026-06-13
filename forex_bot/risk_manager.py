"""
Risk management: position sizing, drawdown guard, trade validation.
"""

import logging

from forex_bot import config, indicators

logger = logging.getLogger(__name__)


def position_size(balance: float, stop_loss_distance: float,
                  price: float, pair: str) -> int:
    """
    Calculate lot size (units) using fixed-fractional position sizing.

    risk_amount = balance * RISK_PER_TRADE
    units       = risk_amount / (stop_loss_distance / price * lot_size)
    Capped at LEVERAGE * balance / price.
    """
    pip      = indicators.pip_value(pair)
    risk_amt = balance * config.RISK_PER_TRADE

    # stop distance in price terms
    sl_dist  = max(stop_loss_distance, pip)  # at least 1 pip

    units = int(risk_amt / sl_dist * config.LOT_SIZE)
    max_units = int(config.LEVERAGE * balance / price)
    units = min(units, max_units, config.LOT_SIZE * 100)  # hard cap: 100 micro-lots
    return max(units, config.LOT_SIZE)


def is_drawdown_ok(balance: float, peak_balance: float) -> bool:
    """Return False if drawdown exceeds the configured maximum."""
    if peak_balance <= 0:
        return True
    dd = (peak_balance - balance) / peak_balance
    if dd > config.MAX_DRAWDOWN_PCT:
        logger.warning("Max drawdown breached: %.1f%% — trading halted", dd * 100)
        return False
    return True


def can_open_trade(open_trades: int) -> bool:
    return open_trades < config.MAX_OPEN_TRADES


def validate_signal(signal, balance: float, peak_balance: float,
                    open_trades: int) -> tuple[bool, str]:
    """
    Gate check before sending an order.
    Returns (ok, reason_string).
    """
    if not is_drawdown_ok(balance, peak_balance):
        return False, "max drawdown reached"
    if not can_open_trade(open_trades):
        return False, f"max open trades ({config.MAX_OPEN_TRADES}) reached"
    if signal.strength < 0.5:
        return False, f"signal strength too low ({signal.strength})"
    return True, "ok"
