"""
Paper-trading portfolio: tracks open/closed positions and P&L.
"""

import uuid
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from forex_bot import config, risk_manager, indicators

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    id:          str
    pair:        str
    direction:   int          # 1 long / -1 short
    entry_price: float
    units:       int
    stop_loss:   float
    take_profit: float
    reason:      str
    opened_at:   datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at:   datetime | None = None
    exit_price:  float | None = None
    pnl:         float = 0.0

    def is_open(self) -> bool:
        return self.closed_at is None

    def unrealised_pnl(self, current_price: float) -> float:
        pip = indicators.pip_value(self.pair)
        diff = (current_price - self.entry_price) * self.direction
        return diff * self.units

    def should_close(self, current_price: float) -> tuple[bool, str]:
        if self.direction == 1:
            if current_price <= self.stop_loss:
                return True, "stop_loss"
            if current_price >= self.take_profit:
                return True, "take_profit"
        else:
            if current_price >= self.stop_loss:
                return True, "stop_loss"
            if current_price <= self.take_profit:
                return True, "take_profit"
        return False, ""


class Portfolio:
    def __init__(self, starting_balance: float = config.STARTING_BALANCE):
        self.balance      = starting_balance
        self.peak_balance = starting_balance
        self.open_trades:   list[Trade] = []
        self.closed_trades: list[Trade] = []

    # ── Order entry ────────────────────────────────────────────────────────

    def open_trade(self, signal) -> Trade | None:
        ok, reason = risk_manager.validate_signal(
            signal, self.balance, self.peak_balance, len(self.open_trades)
        )
        if not ok:
            logger.info("Signal rejected for %s: %s", signal.pair, reason)
            return None

        # Don't double up on the same pair
        open_pairs = {t.pair for t in self.open_trades}
        if signal.pair in open_pairs:
            logger.info("Already have an open trade on %s", signal.pair)
            return None

        sl_dist = abs(signal.price - signal.stop_loss)
        units   = risk_manager.position_size(
            self.balance, sl_dist, signal.price, signal.pair
        )

        trade = Trade(
            id          = str(uuid.uuid4())[:8],
            pair        = signal.pair,
            direction   = signal.direction,
            entry_price = signal.price,
            units       = units,
            stop_loss   = signal.stop_loss,
            take_profit = signal.take_profit,
            reason      = signal.reason,
        )
        self.open_trades.append(trade)
        logger.info(
            "[OPEN]  %s %s @ %.5f  SL=%.5f  TP=%.5f  units=%d",
            "BUY" if trade.direction == 1 else "SELL",
            trade.pair, trade.entry_price,
            trade.stop_loss, trade.take_profit, trade.units,
        )
        return trade

    # ── Position management ────────────────────────────────────────────────

    def update(self, prices: dict[str, float]):
        """Check open trades against current prices; close if SL/TP hit."""
        for trade in list(self.open_trades):
            price = prices.get(trade.pair)
            if price is None:
                continue
            should_close, reason = trade.should_close(price)
            if should_close:
                self._close_trade(trade, price, reason)

    def _close_trade(self, trade: Trade, exit_price: float, reason: str):
        trade.exit_price = exit_price
        trade.closed_at  = datetime.now(timezone.utc)
        trade.pnl        = trade.unrealised_pnl(exit_price)
        self.balance    += trade.pnl
        self.peak_balance = max(self.peak_balance, self.balance)
        self.open_trades.remove(trade)
        self.closed_trades.append(trade)
        logger.info(
            "[CLOSE] %s %s @ %.5f  reason=%s  PnL=%.2f  balance=%.2f",
            "BUY" if trade.direction == 1 else "SELL",
            trade.pair, exit_price, reason, trade.pnl, self.balance,
        )

    # ── Summary ────────────────────────────────────────────────────────────

    def equity(self, prices: dict[str, float]) -> float:
        unrealised = sum(t.unrealised_pnl(prices[t.pair])
                         for t in self.open_trades if t.pair in prices)
        return self.balance + unrealised

    def stats(self) -> dict:
        if not self.closed_trades:
            return {"trades": 0}
        pnls    = [t.pnl for t in self.closed_trades]
        winners = [p for p in pnls if p > 0]
        losers  = [p for p in pnls if p <= 0]
        win_rate = len(winners) / len(pnls) * 100
        avg_win  = sum(winners) / len(winners) if winners else 0
        avg_loss = sum(losers)  / len(losers)  if losers  else 0
        profit_factor = (sum(winners) / abs(sum(losers))) if losers else float("inf")
        drawdown = (self.peak_balance - self.balance) / self.peak_balance * 100
        return {
            "trades":        len(self.closed_trades),
            "open":          len(self.open_trades),
            "win_rate":      round(win_rate, 1),
            "avg_win":       round(avg_win, 2),
            "avg_loss":      round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "total_pnl":     round(sum(pnls), 2),
            "balance":       round(self.balance, 2),
            "peak_balance":  round(self.peak_balance, 2),
            "drawdown_pct":  round(drawdown, 2),
        }
