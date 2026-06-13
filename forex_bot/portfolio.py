"""
Paper-trading portfolio with daily P&L tracking and portfolio heat monitoring.
"""

import uuid
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from forex_bot import config, risk_manager, indicators

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    id:          str
    pair:        str
    direction:   int
    entry_price: float
    units:       int
    stop_loss:   float
    take_profit: float
    reason:      str
    rr_ratio:    float = 0.0
    opened_at:   datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at:   datetime | None = None
    exit_price:  float | None    = None
    pnl:         float = 0.0

    def is_open(self) -> bool:
        return self.closed_at is None

    def unrealised_pnl(self, current_price: float) -> float:
        return (current_price - self.entry_price) * self.direction * self.units

    def should_close(self, current_price: float) -> tuple[bool, str]:
        if self.direction == 1:
            if current_price <= self.stop_loss:   return True, "stop_loss"
            if current_price >= self.take_profit: return True, "take_profit"
        else:
            if current_price >= self.stop_loss:   return True, "stop_loss"
            if current_price <= self.take_profit: return True, "take_profit"
        return False, ""


class Portfolio:
    def __init__(self, starting_balance: float = config.STARTING_BALANCE):
        self.balance        = starting_balance
        self.peak_balance   = starting_balance
        self.open_trades:   list[Trade] = []
        self.closed_trades: list[Trade] = []

    # ── Daily P&L (for daily loss limit check) ────────────────────────────

    @property
    def daily_pnl(self) -> float:
        today = datetime.now(timezone.utc).date()
        return sum(
            t.pnl for t in self.closed_trades
            if t.closed_at and t.closed_at.date() == today
        )

    # ── Portfolio heat ────────────────────────────────────────────────────

    @property
    def portfolio_heat(self) -> float:
        """Fraction of balance at risk if all stops are hit simultaneously."""
        heat = sum(abs(t.entry_price - t.stop_loss) * t.units for t in self.open_trades)
        return heat / self.balance if self.balance > 0 else 0

    # ── Order management ──────────────────────────────────────────────────

    def open_trade(self, signal) -> Trade | None:
        ok, reason = risk_manager.validate_signal(
            signal, self.balance, self.peak_balance,
            self.open_trades, self.daily_pnl,
        )
        if not ok:
            logger.info("Signal rejected (%s): %s", signal.pair, reason)
            return None

        # No double position on same pair
        if any(t.pair == signal.pair for t in self.open_trades):
            logger.info("Already open on %s — skipping", signal.pair)
            return None

        sl_dist = abs(signal.price - signal.stop_loss)
        units   = risk_manager.position_size(
            self.balance, sl_dist, signal.price, signal.pair,
            rr_ratio=signal.rr_ratio,
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
            rr_ratio    = signal.rr_ratio,
        )
        self.open_trades.append(trade)
        logger.info(
            "[OPEN]  %s %s @ %.5f  SL=%.5f  TP=%.5f  R:R=%.1f  units=%d",
            "BUY" if trade.direction == 1 else "SELL",
            trade.pair, trade.entry_price,
            trade.stop_loss, trade.take_profit, trade.rr_ratio, trade.units,
        )
        return trade

    def update(self, prices: dict[str, float]):
        for trade in list(self.open_trades):
            price = prices.get(trade.pair)
            if price is None:
                continue
            hit, reason = trade.should_close(price)
            if hit:
                self._close(trade, price, reason)

    def _close(self, trade: Trade, exit_price: float, reason: str):
        trade.exit_price = exit_price
        trade.closed_at  = datetime.now(timezone.utc)
        trade.pnl        = trade.unrealised_pnl(exit_price)
        self.balance    += trade.pnl
        self.peak_balance = max(self.peak_balance, self.balance)
        self.open_trades.remove(trade)
        self.closed_trades.append(trade)
        logger.info(
            "[CLOSE] %s %s @ %.5f  reason=%-12s  PnL=%+.2f  balance=%.2f  heat=%.1f%%",
            "BUY" if trade.direction == 1 else "SELL",
            trade.pair, exit_price, reason,
            trade.pnl, self.balance, self.portfolio_heat * 100,
        )

    # ── Metrics ───────────────────────────────────────────────────────────

    def equity(self, prices: dict[str, float]) -> float:
        unrealised = sum(
            t.unrealised_pnl(prices[t.pair])
            for t in self.open_trades if t.pair in prices
        )
        return self.balance + unrealised

    def stats(self) -> dict:
        trades  = self.closed_trades
        if not trades:
            return {"trades": 0, "balance": round(self.balance, 2)}
        pnls    = [t.pnl for t in trades]
        winners = [p for p in pnls if p > 0]
        losers  = [p for p in pnls if p <= 0]
        pf      = (sum(winners) / abs(sum(losers))) if losers else float("inf")
        avg_rr  = sum(t.rr_ratio for t in trades) / len(trades)
        dd_pct  = (self.peak_balance - self.balance) / self.peak_balance * 100
        return {
            "trades":        len(trades),
            "open":          len(self.open_trades),
            "win_rate":      round(len(winners) / len(trades) * 100, 1),
            "avg_win":       round(sum(winners) / max(len(winners), 1), 2),
            "avg_loss":      round(sum(losers)  / max(len(losers),  1), 2),
            "profit_factor": round(pf, 2),
            "avg_rr":        round(avg_rr, 2),
            "total_pnl":     round(sum(pnls), 2),
            "daily_pnl":     round(self.daily_pnl, 2),
            "portfolio_heat":f"{self.portfolio_heat*100:.1f}%",
            "balance":       round(self.balance, 2),
            "peak_balance":  round(self.peak_balance, 2),
            "drawdown_pct":  round(dd_pct, 2),
        }
