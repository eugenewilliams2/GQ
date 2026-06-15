"""
Funding-rate carry — a STRUCTURAL strategy, not a price prediction.

Perpetual futures pay a periodic funding rate between longs and shorts to keep the
perp pinned to spot. Cash-and-carry harvests it market-neutrally: hold spot, short
the perp (or vice-versa) so you have ~no price exposure and simply collect funding.
This is a real risk premium (you're paid to provide leverage/liquidity), unlike the
direction-prediction strategies the harness has repeatedly shown have no edge.

Data: OKX public funding-rate-history (free, no key, reachable here; Binance is
geo-blocked). Honest caveats baked into the report: this model collects |funding|
on the receiving side each period minus a flip cost, but IGNORES basis P&L
(spot-perp convergence), the short leg's borrow cost, and liquidation risk — so the
real net is somewhat below this. Still, it's the most legitimate edge avenue tested.
"""

from __future__ import annotations
import time

import numpy as np
import pandas as pd

from forex_bot import metrics

OKX = "https://www.okx.com/api/v5/public/funding-rate-history"
PERIODS_PER_YEAR = 3 * 365            # funding every ~8h


def fetch_okx_funding(inst: str, pages: int = 30) -> pd.Series:
    """Funding-rate series for an OKX swap (e.g. 'BTC-USD-SWAP'), newest->oldest paginated."""
    import requests
    rows, after = [], None
    for _ in range(pages):
        params = {"instId": inst, "limit": 100}
        if after:
            params["after"] = after
        try:
            r = requests.get(OKX, params=params, timeout=20, headers={"User-Agent": "gq"})
            data = r.json().get("data", []) if r.status_code == 200 else []
        except Exception:
            break
        if not data:
            break
        rows += data
        after = data[-1]["fundingTime"]
        time.sleep(0.15)
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows)
    s = pd.Series(df["fundingRate"].astype(float).values,
                  index=pd.to_datetime(df["fundingTime"].astype(np.int64), unit="ms", utc=True))
    return s[~s.index.duplicated()].sort_index()


def carry_backtest(funding: dict[str, pd.Series], starting: float = 10_000.0,
                   entry_bps: float = 10.0):
    """Static cash-and-carry: hold long-spot / short-perp continuously across an
    equal-weight basket. The short-perp side RECEIVES +funding when funding is
    positive (longs pay shorts), which is the historical norm — so no flipping,
    no churn. One round-trip entry/exit cost is charged at the end."""
    if not funding:
        return np.array([starting]), 0.0
    mat = pd.DataFrame(funding).sort_index()
    if len(mat) < 30:
        return np.array([starting]), 0.0
    eq = starting
    equity = [eq]
    gross_funding = 0.0
    for _, row in mat.iterrows():
        vals = row.dropna()
        if len(vals):
            r = float(vals.mean())             # short-perp receives +funding
            eq *= 1 + r
            gross_funding += r
        equity.append(eq)
    eq *= 1 - 2 * entry_bps / 10_000           # one entry + one exit on the basket
    equity[-1] = eq
    return np.array(equity), gross_funding


def run_funding(coins=("BTC", "ETH", "SOL", "DOGE", "XRP"),
                flip_cost_bps: float = 10.0, pages: int = 40):
    funding = {}
    got = []
    for c in coins:
        s = fetch_okx_funding(f"{c}-USD-SWAP", pages=pages)
        if len(s):
            funding[c] = s
            got.append(c)
    equity, gross = carry_backtest(funding, entry_bps=flip_cost_bps)
    perf = metrics.summarize(equity, [], PERIODS_PER_YEAR, n_trials=1)
    return perf, got, gross, len(equity)
