"""
Transaction-cost model — spread, commission, and slippage.

The single most common reason a profitable-looking backtest loses money live is
that it modelled zero trading costs. Every fill here is degraded realistically:

  • Spread  — you buy at the ask (mid + half-spread), sell at the bid
              (mid - half-spread). Always pay the spread, both legs.
  • Slippage — fills land a little worse than intended, more so in fast markets.
              Modelled as extra adverse pips on entry and exit.
  • Commission — per-notional charge some brokers apply on top of spread.

All costs are expressed in pips and converted via the pair's pip value, so the
model works for both 4-decimal pairs and JPY pairs.
"""

from __future__ import annotations
from dataclasses import dataclass

from fx_bot import indicators as ind


@dataclass(frozen=True)
class CostModel:
    """Realistic execution costs. Defaults reflect a typical retail ECN account
    on major pairs; widen them for exotics or news-driven entries."""
    spread_pips:        float = 0.8     # round-trip cost is paid as half on each leg
    slippage_pips:      float = 0.3     # adverse fill drift per leg
    commission_per_lot: float = 7.0     # USD per standard lot (100k) round-trip
    standard_lot:       int   = 100_000

    # ── Fills ──────────────────────────────────────────────────────────────
    def fill_price(self, mid: float, direction: int, pair: str,
                   is_entry: bool) -> float:
        """
        Degrade a mid price into a realistic fill.

        Entry:  a buy (dir=+1) pays UP (ask + slippage); a sell pays DOWN.
        Exit:   closing a long is a sell → fills DOWN; closing a short → UP.
        Either way the trader is always on the wrong side of the spread.
        """
        pip = ind.pip_value(pair)
        half_spread = self.spread_pips / 2 * pip
        slip = self.slippage_pips * pip

        # Sign of the price degradation from the trader's perspective.
        # Entry long / exit short  -> price pushed UP (you pay more / buy back higher)
        # Entry short / exit long  -> price pushed DOWN (you receive less)
        adverse_up = direction == 1 if is_entry else direction == -1
        delta = half_spread + slip
        return mid + delta if adverse_up else mid - delta

    # ── Commission ───────────────────────────────────────────────────────────
    def commission(self, units: int) -> float:
        """Round-trip commission for a position of `units` base-currency units."""
        return abs(units) / self.standard_lot * self.commission_per_lot

    # ── Round-trip cost estimate (for filtering / R:R sanity) ────────────────
    def round_trip_pips(self) -> float:
        """Total pip cost of opening and closing once (both legs)."""
        return self.spread_pips + 2 * self.slippage_pips


# A frictionless model — only for proving that costs are what kill a strategy.
ZERO_COST = CostModel(spread_pips=0.0, slippage_pips=0.0, commission_per_lot=0.0)


@dataclass(frozen=True)
class CryptoCostModel:
    """
    Percentage-based costs for crypto (no pips). Exchange fees dwarf FX costs:
    a retail taker pays ~0.1% PER SIDE, plus spread and slippage. All costs are
    folded into the fill price (as basis points of price) so the engine needs no
    changes; commission() returns 0. Round-trip here is ~0.36% — ~50x the FX cost,
    which is exactly why high-frequency crypto strategies bleed.
    """
    spread_bps:    float = 6.0      # total bid/ask spread (0.06%)
    slippage_bps:  float = 5.0      # adverse fill drift per leg
    fee_bps:       float = 10.0     # taker fee per side (0.10%)

    def fill_price(self, mid: float, direction: int, pair: str, is_entry: bool) -> float:
        adverse_up = direction == 1 if is_entry else direction == -1
        frac = (self.spread_bps / 2 + self.slippage_bps + self.fee_bps) / 10_000
        return mid * (1 + frac) if adverse_up else mid * (1 - frac)

    def commission(self, units: int) -> float:
        return 0.0                  # folded into fill_price

    def round_trip_pips(self) -> float:
        # not pips, but the round-trip cost in bps — kept for interface parity
        return self.spread_bps + 2 * (self.slippage_bps + self.fee_bps)


CRYPTO_ZERO_COST = CryptoCostModel(spread_bps=0.0, slippage_bps=0.0, fee_bps=0.0)
