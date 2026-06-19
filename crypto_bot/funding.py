"""
Funding-rate carry — with the risks that actually kill it modelled.

Static cash-and-carry: long spot + short perp, equal notional, delta-neutral. Its
total return is NOT just funding:

    per period  =  funding_received  +  (basis_t-1 - basis_t)  -  financing
    where basis = (perp - spot) / spot

The directional move cancels (long spot, short perp), leaving the BASIS change as
price P&L — and that's the real risk: during a vol spike the perp can blow to a
large premium/discount, so a forced exit (or just mark-to-market) at a bad basis
can erase months of funding in hours. We also charge a financing/borrow drag and
entry/exit fees on both legs, and report TAIL metrics (worst period, 5% CVaR),
because carry has negative skew and Sharpe alone flatters it.

Data: OKX public funding + candles (Binance geo-blocked).
"""

from __future__ import annotations
import time

import numpy as np
import pandas as pd

from crypto_bot import metrics

OKX_FUND = "https://www.okx.com/api/v5/public/funding-rate-history"
OKX_CANDLES = "https://www.okx.com/api/v5/market/history-candles"
PERIODS_PER_YEAR = 3 * 365


def _get(url, params):
    import requests
    try:
        r = requests.get(url, params=params, timeout=20, headers={"User-Agent": "gq"})
        return r.json().get("data", []) if r.status_code == 200 else []
    except Exception:
        return []


def fetch_okx_funding(inst: str, pages: int = 40) -> pd.Series:
    rows, after = [], None
    for _ in range(pages):
        p = {"instId": inst, "limit": 100}
        if after:
            p["after"] = after
        data = _get(OKX_FUND, p)
        if not data:
            break
        rows += data
        after = data[-1]["fundingTime"]
        time.sleep(0.12)
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows)
    s = pd.Series(df["fundingRate"].astype(float).values,
                  index=pd.to_datetime(df["fundingTime"].astype(np.int64), unit="ms", utc=True))
    return s[~s.index.duplicated()].sort_index()


def fetch_okx_price(inst: str, pages: int = 40) -> pd.Series:
    """1H close series via OKX history-candles (paginated newest->oldest)."""
    rows, after = [], None
    for _ in range(pages):
        p = {"instId": inst, "bar": "1H", "limit": 100}
        if after:
            p["after"] = after
        data = _get(OKX_CANDLES, p)
        if not data:
            break
        rows += data
        after = data[-1][0]
        time.sleep(0.12)
    if not rows:
        return pd.Series(dtype=float)
    df = pd.DataFrame(rows)
    s = pd.Series(df[4].astype(float).values,
                  index=pd.to_datetime(df[0].astype(np.int64), unit="ms", utc=True))
    return s[~s.index.duplicated()].sort_index()


def carry_with_basis(coin: str, funding: pd.Series, perp: pd.Series, spot: pd.Series,
                     financing_apr: float = 0.05) -> pd.Series:
    """Per-period total carry return for one coin: funding + basis change - financing."""
    if funding.empty or perp.empty or spot.empty:
        return pd.Series(dtype=float)
    # basis at each funding timestamp (nearest known prices)
    p = perp.reindex(funding.index, method="ffill")
    s = spot.reindex(funding.index, method="ffill")
    basis = ((p - s) / s).dropna()
    f = funding.reindex(basis.index)
    basis_change = basis.shift(1) - basis            # +ve when premium compresses (we gain)
    fin = financing_apr / PERIODS_PER_YEAR
    ret = f + basis_change - fin
    return ret.dropna()


def run_funding(coins=("BTC", "ETH", "SOL", "DOGE", "XRP"),
                entry_bps: float = 10.0, financing_apr: float = 0.05, pages: int = 40):
    per_coin = {}
    got = []
    for c in coins:
        fund = fetch_okx_funding(f"{c}-USDT-SWAP", pages=pages)
        perp = fetch_okx_price(f"{c}-USDT-SWAP", pages=pages)
        spot = fetch_okx_price(f"{c}-USDT", pages=pages)
        r = carry_with_basis(c, fund, perp, spot, financing_apr)
        if len(r) > 20:
            per_coin[c] = r
            got.append(c)
    if not per_coin:
        return None, [], {}, 0

    mat = pd.DataFrame(per_coin).sort_index()
    port = mat.mean(axis=1).dropna()                 # equal-weight basket per period
    equity = 10_000 * np.cumprod(1 + port.values)
    equity[-1] *= 1 - 2 * entry_bps / 10_000         # round-trip entry/exit on the basket
    perf = metrics.summarize(equity, [], PERIODS_PER_YEAR, n_trials=1)

    # tail metrics — carry's real danger is the downside, not the vol
    r = port.values
    worst = float(r.min())
    cvar5 = float(r[r <= np.percentile(r, 5)].mean()) if len(r) >= 20 else worst
    tail = {"worst_period": worst, "cvar5": cvar5, "basis_vol": float(mat.std().mean())}
    return perf, got, tail, len(port)
