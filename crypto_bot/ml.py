"""
Neural-network strategy — a small multilayer perceptron, in pure NumPy.

This is the honest, local "deep learning" path (no third-party platform, no
accounts, no keys). An MLP is trained to predict next-bar direction from causal
technical features, then traded — and judged by the SAME walk-forward + Deflated
Sharpe gauntlet as everything else.

Discipline baked in:
  • features are strictly causal (only past/known-at-close data)
  • predictions are walk-forward: bar i is scored by a model trained ONLY on bars
    before its fold — no look-ahead, no training on the test set
  • one fixed architecture (no hyperparameter grid) so the Deflated Sharpe isn't
    inflated by multiple testing

Expect the same verdict the rest of the harness gives: ML cannot manufacture edge
from data that has none, and it overfits more eagerly than rules. The point is to
find that out honestly, locally, on data you own.
"""

from __future__ import annotations
import numpy as np
import pandas as pd

from crypto_bot import indicators as ind
from crypto_bot.strategy_base import Strategy, StratSignal

WARMUP = 60


# ── Features & labels (causal) ────────────────────────────────────────────────

def build_features(df: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    c, h, l = df["close"], df["high"], df["low"]
    ema_f, ema_s = ind.ema(c, 9), ind.ema(c, 21)
    _, _, macd_h = ind.macd(c)
    k, d = ind.stochastic(h, l, c)
    atr = ind.atr(h, l, c, 14)
    rsi = ind.rsi(c, 14)
    # volume features — real signal for crypto, inert (0) for volumeless FX.
    v = df["volume"]
    vmean = v.rolling(20).mean()
    vol_z = ((v - vmean) / v.rolling(20).std().replace(0, np.nan)).fillna(0.0)
    vol_chg = v.pct_change().replace([np.inf, -np.inf], 0).fillna(0.0).clip(-5, 5)
    obv = ind.obv(c, v)
    obv_slope = ((obv - obv.shift(10)) / vmean.replace(0, np.nan)).fillna(0.0)

    feats = {
        "r1": c.pct_change(1),
        "r3": c.pct_change(3),
        "r5": c.pct_change(5),
        "r10": c.pct_change(10),
        "rsi": rsi / 100 - 0.5,
        "macd_h": macd_h / c,
        "stoch_k": k / 100 - 0.5,
        "stoch_kd": (k - d) / 100,
        "atr_pct": atr / c,
        "ema_dist": (ema_f - ema_s) / c,
        "px_vs_ema50": (c - ind.ema(c, 50)) / c,
        "vol20": c.pct_change().rolling(20).std(),
        "range": (h - l) / c,
        "vol_z": vol_z,
        "vol_chg": vol_chg,
        "obv_slope": obv_slope,
    }
    # time-of-day / day-of-week — lets the net learn intraday crypto seasonality
    # (strong hours ~21-23 UTC, weekday effects). Cyclically encoded so 23->0 is
    # continuous. On daily data the hour is constant, so these are simply inert.
    idx = df.index
    hour = idx.hour.to_numpy()
    dow = idx.dayofweek.to_numpy()
    feats["hour_sin"] = pd.Series(np.sin(2 * np.pi * hour / 24), index=idx)
    feats["hour_cos"] = pd.Series(np.cos(2 * np.pi * hour / 24), index=idx)
    feats["dow"] = pd.Series(dow / 6 - 0.5, index=idx)

    X = pd.DataFrame(feats).to_numpy(dtype=float)
    return X, list(feats)


def build_labels(df: pd.DataFrame, horizon: int = 1) -> np.ndarray:
    fwd = df["close"].shift(-horizon) / df["close"] - 1
    return (fwd > 0).astype(float).to_numpy()


# ── Pure-NumPy MLP ────────────────────────────────────────────────────────────

class MLP:
    """Binary classifier: ReLU hidden layers, sigmoid output, BCE loss, Adam."""

    def __init__(self, layer_sizes, lr=5e-3, epochs=220, l2=1e-4, seed=0):
        self.sizes = layer_sizes
        self.lr, self.epochs, self.l2, self.seed = lr, epochs, l2, seed
        rng = np.random.default_rng(seed)
        self.W = [rng.standard_normal((a, b)) * np.sqrt(2 / a)
                  for a, b in zip(layer_sizes[:-1], layer_sizes[1:])]
        self.b = [np.zeros(b) for b in layer_sizes[1:]]
        self.mu = self.sd = None

    def _forward(self, X):
        acts, z = [X], X
        for i in range(len(self.W) - 1):
            z = np.maximum(0, acts[-1] @ self.W[i] + self.b[i])
            acts.append(z)
        out = 1 / (1 + np.exp(-(acts[-1] @ self.W[-1] + self.b[-1])))
        acts.append(out)
        return acts

    def fit(self, X, y):
        self.mu, self.sd = X.mean(0), X.std(0) + 1e-8
        Xs = (X - self.mu) / self.sd
        y = y.reshape(-1, 1)
        mW = [np.zeros_like(w) for w in self.W]; vW = [np.zeros_like(w) for w in self.W]
        mb = [np.zeros_like(b) for b in self.b]; vb = [np.zeros_like(b) for b in self.b]
        b1, b2, eps = 0.9, 0.999, 1e-8
        n = len(Xs)
        for t in range(1, self.epochs + 1):
            acts = self._forward(Xs)
            out = acts[-1]
            delta = (out - y) / n                       # dL/dz for BCE+sigmoid
            gW, gb = [None] * len(self.W), [None] * len(self.b)
            for i in reversed(range(len(self.W))):
                gW[i] = acts[i].T @ delta + self.l2 * self.W[i]
                gb[i] = delta.sum(0)
                if i > 0:
                    delta = (delta @ self.W[i].T) * (acts[i] > 0)
            for i in range(len(self.W)):
                for g, m, v, p in ((gW[i], mW, vW, self.W), (gb[i], mb, vb, self.b)):
                    m[i] = b1 * m[i] + (1 - b1) * g
                    v[i] = b2 * v[i] + (1 - b2) * g * g
                    mh = m[i] / (1 - b1 ** t); vh = v[i] / (1 - b2 ** t)
                    p[i] -= self.lr * mh / (np.sqrt(vh) + eps)
        return self

    def predict_proba(self, X):
        Xs = (X - self.mu) / self.sd
        return self._forward(Xs)[-1].ravel()


# ── Walk-forward causal predictions ───────────────────────────────────────────

def walkforward_predict(df: pd.DataFrame, n_splits=4, horizon=1,
                        hidden=(24, 12), seed=0) -> np.ndarray:
    """Return per-bar P(up), trained walk-forward (NaN where no model applies)."""
    X, names = build_features(df)
    y = build_labels(df, horizon)
    n = len(df)
    preds = np.full(n, np.nan)
    fold = n // (n_splits + 1)

    for k in range(1, n_splits + 1):
        tr_lo, tr_hi = 0, fold * k
        te_lo, te_hi = fold * k, min(fold * (k + 1), n)
        if te_hi - te_lo < 20:
            continue
        # training rows: valid features, valid (non-future) labels, within train window
        rows = np.arange(WARMUP, tr_hi - horizon)
        rows = rows[np.isfinite(X[rows]).all(1) & np.isfinite(y[rows])]
        if len(rows) < 100:
            continue
        net = MLP([X.shape[1], *hidden, 1], seed=seed).fit(X[rows], y[rows])
        te = np.arange(te_lo, te_hi)
        te = te[np.isfinite(X[te]).all(1)]
        preds[te] = net.predict_proba(X[te])
    return preds


# ── ML strategy + cost-aware walk-forward backtest ────────────────────────────

class MLStrategy(Strategy):
    """Trades a precomputed walk-forward P(up) array: long when the net is
    confident up, short when confident down. ATR stop, R-multiple target."""
    name = "ml"

    def __init__(self, preds=None, thr=0.06, atr_mult=2.0, rr=1.5, atr_period=14,
                 aggressive=False, agg_gain=12.0, max_mult=3.0):
        super().__init__(thr=thr, atr_mult=atr_mult, rr=rr, atr_period=atr_period,
                         aggressive=aggressive, agg_gain=agg_gain, max_mult=max_mult)
        self._preds = preds

    def warmup(self) -> int:
        return WARMUP + 2

    def prepare(self, df) -> None:
        self.df = df
        self.atr = ind.atr(df["high"], df["low"], df["close"], self.params["atr_period"]).to_numpy()
        self.close = df["close"].to_numpy()
        if self._preds is None:
            self._preds = np.full(len(df), np.nan)

    def _risk_scale(self, conf: float) -> float:
        """1.0 at the trade threshold, scaling up with the net's conviction
        (distance of P(up) from 0.5), capped. Only active when aggressive=True."""
        if not self.params["aggressive"]:
            return 1.0
        extra = max(0.0, conf - self.params["thr"]) * self.params["agg_gain"]
        return float(min(self.params["max_mult"], 1.0 + extra))

    def signal_at(self, i: int) -> StratSignal | None:
        p, a, c = self._preds[i], self.atr[i], self.close[i]
        if np.isnan(p) or np.isnan(a) or a <= 0:
            return None
        thr, am, rr = self.params["thr"], self.params["atr_mult"], self.params["rr"]
        scale = self._risk_scale(abs(p - 0.5))
        if p > 0.5 + thr:
            return StratSignal(1, c - am * a, c + am * a * rr, risk_scale=scale,
                               meta={"conf": round(p, 3)})
        if p < 0.5 - thr:
            return StratSignal(-1, c + am * a, c - am * a * rr, risk_scale=scale,
                               meta={"conf": round(p, 3)})
        return None


def run_ml(data: dict, cost=None, risk_cfg=None, n_splits=4, thr=0.06,
           hidden=(24, 12), ppy: float = 252, aggressive=False):
    """Walk-forward NN per pair, cost-aware backtest over the OOS region, pooled.
    Predictions are cached per pair so flat vs aggressive sizing is an apples-to-
    apples comparison (same trades, different size)."""
    from crypto_bot import metrics
    from crypto_bot.engine import backtest
    from crypto_bot.costs import CostModel
    from crypto_bot.risk import RiskConfig
    cost = cost or CostModel()
    risk_cfg = risk_cfg or RiskConfig(risk_per_trade=0.01, max_leverage=30)

    pooled_rets, pooled_pnls = [], []
    per_pair = {}
    for pair, (df, _) in data.items():
        preds = walkforward_predict(df, n_splits=n_splits, hidden=hidden)
        if not np.isfinite(preds).any():
            continue
        strat = MLStrategy(preds, thr=thr, aggressive=aggressive)
        res = backtest(df, strat, pair, cost, risk_cfg)
        first = int(np.argmax(np.isfinite(preds)))      # OOS region start
        pooled_rets.append(metrics.returns_from_equity(res.equity[first:]))
        pooled_pnls += res.trade_pnls
        per_pair[pair] = len(res.trades)

    rets = np.concatenate(pooled_rets) if pooled_rets else np.array([])
    equity = 10_000 * np.cumprod(1 + rets) if len(rets) else np.array([10_000.0])
    perf = metrics.summarize(equity, pooled_pnls, ppy, n_trials=1)
    return perf, per_pair


import json as _json
import os as _os

BEST_NN_PATH = _os.path.join(_os.path.dirname(__file__), ".best_nn.json")


def nn_search(data: dict, asset: str, cost=None, risk_cfg=None, ppy: float = 365,
              n_splits: int = 4):
    """Deep-learning search: train the NN under several architectures/thresholds,
    score each OUT-OF-SAMPLE after costs, and rank by Deflated Sharpe PENALIZED for
    the number of configs tried. 'Keeping the best' means saving the top config by
    that honest metric — not the prettiest backtest. Returns the ranked list."""
    from crypto_bot import metrics
    from crypto_bot.engine import backtest
    from crypto_bot.costs import CryptoCostModel, CostModel
    from crypto_bot.risk import RiskConfig
    cost = cost or (CryptoCostModel() if asset == "crypto" else CostModel())
    risk_cfg = risk_cfg or RiskConfig(risk_per_trade=0.01, max_leverage=30)

    configs = [{"hidden": h, "thr": t}
               for h in [(16, 8), (24, 12), (32, 16, 8)]
               for t in [0.04, 0.06, 0.10]]
    N = len(configs)
    ranked = []
    for cfg in configs:
        pooled, pnls = [], []
        for pair, (df, _) in data.items():
            preds = walkforward_predict(df, n_splits=n_splits, hidden=cfg["hidden"])
            if not np.isfinite(preds).any():
                continue
            res = backtest(df, MLStrategy(preds, thr=cfg["thr"]), pair, cost, risk_cfg)
            first = int(np.argmax(np.isfinite(preds)))
            pooled.append(metrics.returns_from_equity(res.equity[first:]))
            pnls += res.trade_pnls
        rets = np.concatenate(pooled) if pooled else np.array([])
        eq = 10_000 * np.cumprod(1 + rets) if len(rets) else np.array([10_000.0])
        perf = metrics.summarize(eq, pnls, ppy, n_trials=N)        # penalized by #configs
        ranked.append((cfg, perf))

    ranked.sort(key=lambda x: x[1].deflated_sharpe, reverse=True)
    best_cfg, best_perf = ranked[0]
    kept = {"asset": asset, "hidden": list(best_cfg["hidden"]), "thr": best_cfg["thr"],
            "sharpe": best_perf.sharpe, "deflated_sharpe": best_perf.deflated_sharpe,
            "profit_factor": best_perf.profit_factor, "n_configs": N,
            "edge": bool(best_perf.deflated_sharpe >= 0.95 and best_perf.sharpe > 0)}
    with open(BEST_NN_PATH, "w") as f:
        _json.dump(kept, f, indent=2)
    return ranked, kept


def load_best_nn():
    if _os.path.exists(BEST_NN_PATH):
        try:
            with open(BEST_NN_PATH) as f:
                return _json.load(f)
        except Exception:
            pass
    return None


def holdout_ml(data: dict, cost=None, risk_cfg=None, train_frac=0.7, thr=0.06,
               hidden=(24, 12), ppy: float = 252, aggressive=False, horizon=1):
    """Strict single holdout: train each net ONCE on the first `train_frac`,
    predict the untouched remainder one time, backtest the OOS region. The most
    conservative test — one model, one evaluation, n_trials=1."""
    from crypto_bot import metrics
    from crypto_bot.engine import backtest
    from crypto_bot.costs import CostModel
    from crypto_bot.risk import RiskConfig
    cost = cost or CostModel()
    risk_cfg = risk_cfg or RiskConfig(risk_per_trade=0.01, max_leverage=30)

    pooled_rets, pooled_pnls = [], []
    for pair, (df, _) in data.items():
        X, _ = build_features(df)
        y = build_labels(df, horizon)
        n = len(df)
        cut = int(n * train_frac)
        rows = np.arange(WARMUP, cut - horizon)
        rows = rows[np.isfinite(X[rows]).all(1) & np.isfinite(y[rows])]
        if len(rows) < 100:
            continue
        net = MLP([X.shape[1], *hidden, 1]).fit(X[rows], y[rows])
        preds = np.full(n, np.nan)
        te = np.arange(cut, n)
        te = te[np.isfinite(X[te]).all(1)]
        preds[te] = net.predict_proba(X[te])
        res = backtest(df, MLStrategy(preds, thr=thr, aggressive=aggressive),
                       pair, cost, risk_cfg)
        pooled_rets.append(metrics.returns_from_equity(res.equity[cut:]))
        pooled_pnls += res.trade_pnls

    rets = np.concatenate(pooled_rets) if pooled_rets else np.array([])
    equity = 10_000 * np.cumprod(1 + rets) if len(rets) else np.array([10_000.0])
    return metrics.summarize(equity, pooled_pnls, ppy, n_trials=1)

