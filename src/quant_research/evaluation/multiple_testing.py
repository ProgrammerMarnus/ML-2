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


TRADING_DAYS_SCALE = 252.0


def expected_max_sharpe(n_trials: int, n_obs: int,
                        sharpe_variance: float | None = None) -> float:
    """Expected maximum PERIODIC (daily) Sharpe under the pure-noise null.

    Bailey/Lopez de Prado: E[max SR] ~ sqrt(V) * ((1-g)*Z(1-1/N) + g*Z(1-1/(N*e)))
    where ``V`` is the variance of the per-period Sharpe estimates ACROSS
    TRIALS.  When ``sharpe_variance`` is not supplied it defaults to the
    normal-moments simplification V = 1/(n_obs-1).  The output is in PERIOD
    units (daily for daily bars), NOT annualized -- annualize by multiplying
    sqrt(252) if a comparable annualized figure is needed.
    """
    if n_trials < 1 or n_obs < 2:
        return float("nan")
    if sharpe_variance is not None and np.isfinite(sharpe_variance) and sharpe_variance > 0:
        v = float(sharpe_variance)
    else:
        v = 1.0 / (n_obs - 1)
    # B17: Handle one-trial boundary explicitly. For n_trials=1, the expected
    # maximum of a single zero-mean null variable is 0, not the two-trial penalty.
    # The max(n_trials, 2) was incorrectly applying a two-trial penalty to
    # one-trial hypotheses.
    if n_trials == 1:
        return 0.0  # E[max of one N(0,V)] = 0
    n = n_trials
    z1 = stats.norm.ppf(1.0 - 1.0 / n)
    z2 = stats.norm.ppf(1.0 - 1.0 / (n * math.e))
    return float(np.sqrt(v) * ((1 - EULER_GAMMA) * z1 + EULER_GAMMA * z2))


def deflated_sharpe_pvalue(observed_sharpe: float, n_trials: int, n_obs: int,
                           skew: float = 0.0, kurtosis: float = 3.0,
                           sharpe_variance: float | None = None) -> float:
    """P(observed annualized Sharpe | no edge, after `n_trials` attempts).

    Published DSR/PSR correction (Bailey & Lopez de Prado 2014, eq. 2):

        PSR(SR*) = Z( (SR - SR*) * sqrt(n - 1)
                      / sqrt(1 - skew*SR + (kurt - 1)/4 * SR^2) )

    with SR (the candidate's per-period Sharpe, i.e. annualized / sqrt(252))
    and SR* (the expected maximum across trials) in the SAME per-period
    units.  The denominator is the published probabilistic-Sharpe variance
    term -- it scales with the ESTIMATED Sharpe and the return's skew and
    kurtosis, not with fixed 1/3 and 1/24 constants.  The null benchmark's
    Sharpe variance ``V`` is taken from ``sharpe_variance`` when supplied
    (the cross-trial estimate, when trial Sharpes are available); otherwise
    it is estimated from the candidate's own moments, the published
    single-strategy estimator:  V = (1 - skew*SR + (kurt-1)/4*SR^2)/(n-1).
    """
    if not np.isfinite(observed_sharpe) or n_trials < 1 or n_obs < 2:
        return float("nan")
    sr = float(observed_sharpe) / np.sqrt(TRADING_DAYS_SCALE)  # per-period
    var_term = 1.0 - skew * sr + (kurtosis - 1.0) / 4.0 * sr * sr
    denom = np.sqrt(max(var_term, 1e-12))
    if sharpe_variance is not None and np.isfinite(sharpe_variance) and sharpe_variance > 0:
        v = float(sharpe_variance)
    else:
        v = max(var_term, 1e-12) / (n_obs - 1)
    sr0 = expected_max_sharpe(n_trials, n_obs, sharpe_variance=v)
    t_stat = np.sqrt(n_obs - 1) * (sr - sr0) / denom
    return float(1.0 - stats.norm.cdf(t_stat))
