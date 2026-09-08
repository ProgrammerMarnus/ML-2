"""Risk engine: structured risk report, fully traceable to its inputs."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..evaluation.metrics import TRADING_DAYS, beta, max_drawdown, tail_loss


def historical_var(returns: pd.Series, q: float = 0.05) -> float:
    r = pd.Series(returns).dropna()
    if len(r) == 0:
        return float("nan")
    return float(-r.quantile(q))


def historical_cvar(returns: pd.Series, q: float = 0.05) -> float:
    r = pd.Series(returns).dropna()
    if len(r) == 0:
        return float("nan")
    cutoff = r.quantile(q)
    tail = r[r <= cutoff]
    return float(-tail.mean()) if len(tail) else float("nan")


def concentration_hhi(weights: pd.Series) -> float:
    w = weights.abs().dropna()
    if w.sum() == 0:
        return 0.0
    share = w / w.sum()
    return float((share ** 2).sum())


def cross_sectional_hhi(weight_matrix: pd.DataFrame) -> pd.Series:
    """Cross-sectional concentration per timestamp over an asset weight matrix.

    Rows are timestamps, columns are assets.  Returns the HHI of the absolute
    weight distribution at each timestamp (a per-timestamp series), which is a
    proper portfolio-concentration measure.
    """
    w = weight_matrix.abs()
    share = w.div(w.sum(axis=1), axis=0).replace([np.inf, -np.inf], np.nan)
    hhi = (share ** 2).sum(axis=1)
    return hhi.fillna(0.0)


def risk_report(net_returns: pd.Series, weights: pd.Series | None = None,
                benchmark: pd.Series | None = None,
                weight_matrix: pd.DataFrame | None = None) -> dict:
    """Structured risk diagnostics for one return stream.

    ``weights`` (a single time series) is used for EXPOSURE/activity metrics
    only; pass the ACTUAL executed position ledger (e.g. ``baseline.oos_positions``)
    -- never a synthetic/proxy position schedule.  Turnover follows the
    engine's convention: the first bar charges |position| as its entry, so
    ``annual_turnover`` reconciles exactly with the backtester's charged
    turnover.  ``benchmark`` must be the same realized interval the strategy
    actually earns (forward close-to-close).

    Cross-sectional concentration HHI is MEANINGFUL only over a real
    per-timestamp weight MATRIX (``weight_matrix``); when it is not supplied we
    explicitly report ``concentration_hhi=None`` rather than a misleading
    number computed over a single pseudo-position's time series.
    """
    r = pd.Series(net_returns, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
    out = {
        "annualized_vol": float(r.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(r) > 1 else float("nan"),
        "max_drawdown": max_drawdown(r),
        "var_95_daily": historical_var(r),
        "cvar_95_daily": historical_cvar(r),
        "tail_loss_5pct": tail_loss(r),
        "worst_single_day": float(r.min()) if len(r) else float("nan"),
        "n_obs": int(len(r)),
    }
    if benchmark is not None:
        out["beta_to_benchmark"] = beta(r, benchmark)
    if weights is not None:
        out["avg_gross_exposure"] = float(weights.abs().mean())
        out["max_gross_exposure"] = float(weights.abs().max())
        turnover = weights.diff().abs()
        if len(turnover):
            turnover.iloc[0] = abs(weights.iloc[0])  # engine ledger convention
        out["annual_turnover"] = float(turnover.sum() / max(len(weights) / TRADING_DAYS, 1e-9))
    # Cross-sectional concentration only when a real weight matrix is present.
    if weight_matrix is not None and len(weight_matrix) > 0 and weight_matrix.shape[1] >= 1:
        hhi = cross_sectional_hhi(weight_matrix)
        out["concentration_hhi"] = float(hhi.median())
        out["concentration_hhi_worst"] = float(hhi.max())
        out["concentration_hhi_median"] = float(hhi.median())
    else:
        out["concentration_hhi"] = None          # no true weight matrix
        out["concentration_hhi_median"] = None
        out["concentration_hhi_worst"] = None
    # gap risk proxy: largest single-day loss; correlation spike proxy:
    if benchmark is not None:
        b = pd.Series(benchmark).dropna()
        common = r.index.intersection(b.index)
        if len(common) > 60:
            corr = r.loc[common].rolling(60).corr(b.loc[common])
            out["max_60d_correlation"] = float(corr.max())
    return out
