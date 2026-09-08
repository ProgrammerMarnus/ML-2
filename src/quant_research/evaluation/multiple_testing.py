"""Multiple-hypothesis correction and deflated statistics."""

from __future__ import annotations

import math

import numpy as np
from scipy import stats

EULER_GAMMA = 0.5772156649


def bonferroni(pvalues: list[float]) -> list[float]:
    n = len(pvalues)
    return [min(1.0, p * n) for p in pvalues]


def benjamini_hochberg(pvalues: list[float]) -> list[float]:
    """BH FDR-adjusted p-values (step-up)."""
    n = len(pvalues)
    order = np.argsort(pvalues)
    ranked = np.asarray(pvalues)[order]
    adj = ranked * n / (np.arange(n) + 1)
    adj = np.minimum.accumulate(adj[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.clip(adj, 0, 1)
    return [float(x) for x in out]


def holm(pvalues: list[float]) -> list[float]:
    """Holm step-down adjusted p-values."""
    n = len(pvalues)
    order = np.argsort(pvalues)
    ranked = np.asarray(pvalues)[order]
    adj = np.maximum.accumulate((n - np.arange(n)) * ranked)
    out = np.empty(n)
    out[order] = np.clip(adj, 0, 1)
    return [float(x) for x in out]


def expected_max_sharpe(n_trials: int, n_obs: int) -> float:
    """Expected maximum annualized Sharpe under the pure-noise null.

    Bailey/Lopez de Prado-style: E[max SR] ~ sqrt(V) * ((1-g)*Z(1-1/N) + g*Z(1-1/(N*e)))
    where V = 1/(n_obs-1) for annualized SR of daily returns.
    """
    if n_trials < 1 or n_obs < 2:
        return float("nan")
    v = 1.0 / (n_obs - 1)
    n = max(n_trials, 2)
    z1 = stats.norm.ppf(1.0 - 1.0 / n)
    z2 = stats.norm.ppf(1.0 - 1.0 / (n * math.e))
    return float(np.sqrt(v) * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2))


def deflated_sharpe_pvalue(observed_sharpe: float, n_trials: int, n_obs: int,
                           skew: float = 0.0, kurtosis: float = 3.0) -> float:
    """P(observed Sharpe | no edge, after `n_trials` attempts).

    Uses the DSR probabilistic correction (Bailey & Lopez de Prado 2014):
    SR0 = expected max Sharpe under null; test statistic accounts for skew/kurt.
    """
    if not np.isfinite(observed_sharpe) or n_trials < 1 or n_obs < 2:
        return float("nan")
    sr0 = expected_max_sharpe(n_trials, n_obs)
    denom = np.sqrt(max(1.0 - skew / 3.0 + (kurtosis - 3.0) / 24.0, 1e-12))
    t_stat = np.sqrt(n_obs - 1) * (observed_sharpe / np.sqrt(TRADING_DAYS_SCALE) - sr0) / denom
    return float(1.0 - stats.norm.cdf(t_stat))


TRADING_DAYS_SCALE = 252.0
